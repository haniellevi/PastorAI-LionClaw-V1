"""Guided public lookup through persisted inbound, real worker and transport."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import delete, select

from app.db.models import Celula, ConsentRecord, Message, Pessoa
from tests.test_prayer_requests_pg import (
    prayer as _prayer_fixture,
    msg_engine_fx as msg_engine_fx,
    rls_database_url as rls_database_url,
    TENANT,
    FOREIGN,
    send,
    inbound,
    _enable_s3_for_prayer_contact,
    _ClassifiedEvolution,
)

prayer = _prayer_fixture

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def guided(prayer, monkeypatch):
    from app.cell_suggest import policy

    monkeypatch.setenv("CELL_SUGGEST_ENABLED_IGREJA_IDS", str(TENANT))
    monkeypatch.setattr(policy, "CELL_SUGGEST_APPROVED_RELEASE_ID", "synthetic-only")
    with prayer.factory.begin() as db:
        row = db.get(Celula, prayer.cell)
        row.bairro = "São José"
        row.nome = "Esperança"
        row.divulgar_whatsapp = True
        row.dia_reuniao = "terca"
        row.horario = "19:30"
        row.endereco = "Rua Proibida 123"
        row.link_grupo = "https://chat.whatsapp.com/PRIVADO"
        row.link_localizacao = "https://maps.example.test/PRIVADO"
        leader = db.get(Pessoa, row.lider_id)
        leader.nome = "LiderPrivadoSintetico"
        leader.telefone = "5500000000088"
    return prayer


def add_cell(p, *, bairro="São José", nome="Paz", tenant=TENANT, **kwargs):
    with p.factory.begin() as db:
        db.add(
            Celula(
                id=uuid.uuid4(),
                igreja_id=tenant,
                nome=nome,
                bairro=bairro,
                cobertura_espiritual="Sintético",
                divulgar_whatsapp=kwargs.pop("divulgar_whatsapp", True),
                ativo=kwargs.pop("ativo", True),
                **kwargs,
            )
        )


def assert_reply(p, text):
    _, reply, transport = send(p, text)
    assert len(transport.calls) == 1
    assert reply.agent_reply_state == "ia"
    assert reply.agent_privilege_context["kind"] == "cell_suggest"
    return reply.texto


def test_guided_one_cell_and_no_private_leak(guided):
    assert "bairro" in assert_reply(guided, "Quero encontrar uma célula").lower()
    result = assert_reply(guided, "SAO JOSE")
    assert "Esperança" in result and "19:30" in result
    for forbidden in [
        "Rua Proibida",
        "123",
        "LiderPrivadoSintetico",
        "5500000000088",
        "https://",
        "mais próxima",
    ]:
        assert forbidden not in result
    with guided.factory() as db:
        assert db.get(Pessoa, guided.person).celula_id is None


def test_multiple_cells_and_private_inactive_foreign_excluded(guided):
    add_cell(guided)
    add_cell(guided, nome="Oculta", divulgar_whatsapp=False)
    add_cell(guided, nome="Inativa", ativo=False)
    add_cell(guided, nome="OutraIgreja", tenant=FOREIGN)
    result = assert_reply(guided, "Indique uma célula no bairro São José")
    assert "Esperança" in result and "Paz" in result
    assert all(x not in result for x in ["Oculta", "Inativa", "OutraIgreja"])


def test_ambiguous_bairro_asks_again_then_resolves(guided):
    add_cell(guided, bairro="São João", nome="Alegria")
    ask = assert_reply(guided, "Quero encontrar uma célula")
    ambiguous = assert_reply(guided, "São")
    assert "bairro completo" in ambiguous.lower()
    assert "cidade" not in ask.lower()
    assert "cidade" not in ambiguous.lower()
    resolved = assert_reply(guided, "São João")
    assert "Alegria" in resolved
    assert "cidade" not in resolved.lower()


def test_unknown_bairro_hands_off_without_inventing_neighbors(guided):
    assert_reply(guided, "Quero encontrar uma célula")
    result = assert_reply(guided, "Bairro inexistente")
    assert "equipe" in result.lower()
    from app.db.models import Conversation

    with guided.factory() as db:
        assert db.get(Conversation, guided.conv).estado == "humano"
    assert "Esperança" not in result


def test_unaccepted_contact_is_not_handled(guided):
    from app.cell_suggest.turn import run_cell_suggest_turn

    with guided.factory.begin() as db:
        db.execute(
            delete(ConsentRecord).where(ConsentRecord.pessoa_id == guided.person)
        )
    outcome = inbound(guided, "Quero encontrar uma célula")
    assert (
        run_cell_suggest_turn(
            guided.factory,
            guided.factory,
            outcome,
            igreja_id=TENANT,
            uses_dedicated_agent_session=False,
            ownership_guard=None,
            evolution_client=_ClassifiedEvolution(),
        )
        is None
    )


@pytest.mark.parametrize("body", ["Quero parar de receber mensagens", "Quero me matar"])
def test_optout_and_crisis_keep_priority(guided, body):
    assert_reply(guided, "Quero encontrar uma célula")
    _, reply, _ = send(guided, body)
    assert not (reply.agent_privilege_context or {}).get("kind") == "cell_suggest"


def test_disabled_before_any_session_or_provider(prayer):
    from app.cell_suggest.turn import run_cell_suggest_turn

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled feature touched dependency")

    assert (
        run_cell_suggest_turn(
            forbidden,
            forbidden,
            object(),
            igreja_id=TENANT,
            uses_dedicated_agent_session=False,
            ownership_guard=forbidden,
            evolution_client=forbidden,
        )
        is None
    )


def test_live_guided_does_not_capture_s3_sim(guided, monkeypatch):
    from app.db.models import AgentActionProposal

    assert_reply(guided, "Quero encontrar uma célula")
    _, proposal_id, _ = _enable_s3_for_prayer_contact(guided, monkeypatch)
    _, reply, transport = send(guided, "SIM")
    assert "Comprovante:" in transport.calls[0][2]
    assert reply.agent_privilege_context["kind"] == "receipt"
    with guided.factory() as db:
        assert db.get(AgentActionProposal, proposal_id).state == "executada"


def test_live_guided_does_not_capture_prayer_sim(guided):
    from tests.test_prayer_requests_pg import create_request

    assert_reply(guided, "Quero encontrar uma célula")
    row = create_request(guided)
    assert row.state == "open"


def test_expired_state_does_not_capture_bairro(guided):
    from app.cell_suggest.turn import run_cell_suggest_turn

    assert_reply(guided, "Quero encontrar uma célula")
    with guided.factory.begin() as db:
        reply = db.execute(
            select(Message).where(
                Message.conversation_id == guided.conv, Message.direcao == "out"
            )
        ).scalar_one()
        reply.criado_em = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    assert (
        run_cell_suggest_turn(
            guided.factory,
            guided.factory,
            inbound(guided, "São José"),
            igreja_id=TENANT,
            uses_dedicated_agent_session=False,
            ownership_guard=None,
            evolution_client=_ClassifiedEvolution(),
        )
        is None
    )


@pytest.mark.parametrize(
    "unsafe_name",
    ["https://chat.whatsapp.com/PRIVADO", "Mapa www.example.test", "Casa 123"],
)
def test_unsafe_public_label_never_becomes_location_or_link(guided, unsafe_name):
    with guided.factory.begin() as db:
        db.get(Celula, guided.cell).nome = unsafe_name
    result = assert_reply(guided, "Indique uma célula no bairro São José")
    assert unsafe_name not in result
    assert "equipe" in result.lower()


def test_publication_revoked_before_retry_is_suppressed(guided):
    from app.cell_suggest.turn import reply_still_authorized

    assert_reply(guided, "Indique uma célula no bairro São José")
    from app.db.models import Conversation

    with guided.factory.begin() as db:
        reply = db.scalars(
            select(Message).where(
                Message.conversation_id == guided.conv, Message.direcao == "out"
            )
        ).one()
        db.get(Celula, guided.cell).divulgar_whatsapp = False
        db.flush()
        assert not reply_still_authorized(
            db,
            reply,
            conversation=db.get(Conversation, guided.conv),
            recipient_phone="5500000000000",
            instance="prayer-test",
        )


def test_live_prompt_yields_real_fonovisita_command(guided):
    from app.cell_suggest.turn import run_cell_suggest_turn

    assert_reply(guided, "Quero encontrar uma célula")
    transport = _ClassifiedEvolution()
    assert (
        run_cell_suggest_turn(
            guided.factory,
            guided.factory,
            inbound(guided, "marcar fonovisita feita"),
            igreja_id=TENANT,
            uses_dedicated_agent_session=False,
            ownership_guard=None,
            evolution_client=transport,
        )
        is None
    )
    assert transport.calls == []


def test_unknown_location_is_not_copied_to_workflow_metadata(guided):
    _, reply, transport = send(guided, "Indique célula no bairro Rua Proibida 123")
    assert transport.calls
    assert reply.agent_privilege_context["stage"] == "handoff"
    assert reply.agent_privilege_context["bairro"] is None
    assert "Rua Proibida" not in reply.texto


def test_new_publication_after_commit_suppresses_missing_and_handoff(guided):
    from sqlalchemy import event, update
    from app.db.models import Conversation
    from app.workers import queue_worker as worker
    from app.domain.agent_reply import AGENT_REPLY_PENDING, AGENT_REPLY_SUPPRESSED

    with guided.factory.begin() as db:
        db.get(Celula, guided.cell).divulgar_whatsapp = False
    outcome = inbound(guided, "Indique célula no bairro São José")
    published = []

    def publish_after_missing_commit(session):
        # Real second transaction between durable reply commit and transport.
        if published:
            return
        with guided.engine.begin() as conn:
            pending = conn.scalar(
                select(Message.id).where(
                    Message.igreja_id == TENANT,
                    Message.conversation_id == guided.conv,
                    Message.agent_reply_state == AGENT_REPLY_PENDING,
                    Message.agent_privilege_context["stage"].astext == "handoff",
                )
            )
            if pending is not None:
                conn.execute(
                    update(Celula)
                    .where(
                        Celula.id == guided.cell,
                        Celula.igreja_id == TENANT,
                    )
                    .values(divulgar_whatsapp=True)
                )
                published.append(pending)

    transport = _ClassifiedEvolution()
    event.listen(guided.factory.class_, "after_commit", publish_after_missing_commit)
    try:
        worker.run_agent_for_message(
            guided.factory, outcome, evolution_client=transport
        )
    finally:
        event.remove(
            guided.factory.class_, "after_commit", publish_after_missing_commit
        )
    assert len(published) == 1
    assert transport.calls == []
    with guided.factory() as db:
        assert db.get(Message, published[0]).agent_reply_state == AGENT_REPLY_SUPPRESSED
        assert db.get(Message, published[0]).agent_privilege_context["bairro"] is None
        assert db.get(Conversation, guided.conv).estado == "ia"

"""V2a Agenda service against PostgreSQL RLS, with no new migration."""
from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

from app.db.models import (
    AgentIdentityChallenge,
    AppUser,
    Conversation,
    Event,
    Igreja,
    Message,
    UserRole,
)
from app.db.tenant_session import mark_tenant_scoped
from app.services import whatsapp_agenda
from app.services import agent_identity
from app.services.agent_identity import confirm_identity_challenge
from app.services.llm import LLMClient, LLMUsage, TypedChoiceResult
from app.services.whatsapp_privilege import PrivilegeContext
from app.workers import queue_worker as worker_module
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_messages_inbound_idempotency import _factory, msg_engine_fx
from tests.test_agent_privileged_turn_pg import (
    _ClassifiedEvolution,
    _IGREJA,
    _inbound,
    s3_turn,
)


pytestmark = pytest.mark.rls_integration

_TENANT_A = uuid.UUID("9a9a9a9a-0000-4000-8000-000000000001")
_TENANT_B = uuid.UUID("9b9b9b9b-0000-4000-8000-000000000001")


def _context(tenant: uuid.UUID) -> PrivilegeContext:
    return PrivilegeContext(
        igreja_id=tenant,
        conversation_id=uuid.UUID("00000000-0000-0000-0000-000000000701"),
        inbound_message_id=uuid.UUID("00000000-0000-0000-0000-000000000702"),
        pessoa_id=uuid.UUID("00000000-0000-0000-0000-000000000703"),
        app_user_id=uuid.UUID("00000000-0000-0000-0000-000000000704"),
        roles=frozenset({"membro"}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint="credential",
        phone_fingerprint="phone",
        authorization_fingerprint="authorization",
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="scope",
        context_fingerprint="context",
    )


@pytest.fixture
def agenda_rls(msg_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch):
    factory = _factory(msg_engine_fx)
    now = dt.datetime.now(dt.UTC)
    with factory.begin() as session:
        for tenant in (_TENANT_A, _TENANT_B):
            session.add(Igreja(id=tenant, nome=f"Igreja {tenant.hex[:1]}"))
        session.flush()
        authors = {}
        for tenant in (_TENANT_A, _TENANT_B):
            author_id = uuid.uuid5(tenant, "agenda-author")
            authors[tenant] = author_id
            session.add(AppUser(
                id=author_id,
                igreja_id=tenant,
                pessoa_id=None,
                clerk_user_id=f"clerk-{tenant.hex}",
                nome="Autor Sintético",
                email=f"agenda-{tenant.hex}@example.test",
                status="ativo",
            ))
        session.flush()
        for tenant in (_TENANT_A, _TENANT_B):
            author_id = authors[tenant]
            session.add(UserRole(igreja_id=tenant, user_id=author_id, papel="pastor"))
            session.add(Event(
                id=uuid.uuid5(tenant, "agenda-event"),
                igreja_id=tenant,
                titulo="Encontro com Deus" if tenant == _TENANT_A else "Festa da Ana",
                tipo="culto",
                status="confirmado",
                data=now.date() + dt.timedelta(days=1),
                hora="19:30",
                recorrencia="pontual",
                confirmado_em=now - dt.timedelta(minutes=1),
                confirmado_por=author_id,
            ))
        # Legacy confirmed rows are visible as a safe type only, never title.
        session.add(Event(
            id=uuid.uuid5(_TENANT_A, "legacy"),
            igreja_id=_TENANT_A,
            titulo="Festa da Ana",
            tipo="especial",
            status="confirmado",
            data=now.date() + dt.timedelta(days=2),
            hora="20:00",
            recorrencia="pontual",
            confirmado_em=now - dt.timedelta(minutes=1),
            confirmado_por=None,
        ))
    with msg_engine_fx.begin() as connection:
        connection.exec_driver_sql("alter table events enable row level security")
        connection.exec_driver_sql("alter table events force row level security")
        connection.exec_driver_sql("drop policy if exists tenant_isolation on events")
        connection.exec_driver_sql(
            "create policy tenant_isolation on events for all "
            "using (igreja_id = current_igreja_id()) "
            "with check (igreja_id = current_igreja_id())"
        )
    monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", "agenda-test")
    monkeypatch.setattr(whatsapp_agenda, "privilege_enabled_from_environment", lambda _tenant: True)
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", f"{_TENANT_A},{_TENANT_B}")
    return factory


def test_confirmed_agenda_uses_rls_and_falls_back_for_legacy_title(agenda_rls):
    session = agenda_rls()
    try:
        mark_tenant_scoped(session, _TENANT_A, source="v2a_agenda_pg")
        # Direct SQLAlchemy read without a WHERE proves the policy, separately
        # from the service's own tenant predicate.
        direct = session.execute(select(Event).order_by(Event.id)).scalars().all()
        assert direct and all(row.igreja_id == _TENANT_A for row in direct)
        reply = whatsapp_agenda.resolve_agenda_reply(
            session,
            context=_context(_TENANT_A),
            text="agenda próximos 7 dias",
            now=dt.datetime.now(dt.UTC),
        )
        assert reply is not None
        assert "Encontro com Deus" in reply.response
        assert "Festa da Ana" not in reply.response
        assert "Evento especial da igreja" in reply.response
    finally:
        session.rollback()
        session.close()


def test_other_tenant_cannot_read_or_project_event(agenda_rls):
    session = agenda_rls()
    try:
        mark_tenant_scoped(session, _TENANT_B, source="v2a_agenda_pg")
        direct = session.execute(select(Event)).scalars().all()
        assert direct and all(row.igreja_id == _TENANT_B for row in direct)
        reply = whatsapp_agenda.resolve_agenda_reply(
            session,
            context=_context(_TENANT_B),
            text="agenda",
            now=dt.datetime.now(dt.UTC),
        )
        assert reply is not None
        assert "Encontro com Deus" not in reply.response
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def agenda_turn(s3_turn, monkeypatch: pytest.MonkeyPatch):
    """Real worker fixture with a member requester and server-confirmed events."""

    monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", "agenda-test")
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", str(_IGREJA))
    author_id = uuid.uuid4()
    with s3_turn.factory.begin() as session:
        session.execute(delete(UserRole).where(
            UserRole.igreja_id == _IGREJA,
            UserRole.user_id == s3_turn.app_user_id,
        ))
        session.add(UserRole(
            igreja_id=_IGREJA,
            user_id=s3_turn.app_user_id,
            papel="membro",
        ))
        session.add(AppUser(
            id=author_id,
            igreja_id=_IGREJA,
            pessoa_id=None,
            clerk_user_id="clerk-agenda-author-synthetic",
            nome="Autor da agenda sintético",
            email="agenda-author@example.test",
            status="ativo",
        ))
        session.flush()
        session.add(UserRole(igreja_id=_IGREJA, user_id=author_id, papel="pastor"))
        session.add(Event(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            titulo="Encontro com Deus",
            tipo="culto",
            status="confirmado",
            data=dt.date.today() + dt.timedelta(days=1),
            hora="19:30",
            recorrencia="pontual",
            confirmado_em=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
            confirmado_por=author_id,
        ))
    return s3_turn


def _agenda_choices(monkeypatch: pytest.MonkeyPatch, turn) -> list[str]:
    stages: list[str] = []

    def choose(_self, _system, prompt, *, schema_name, choices, timeout_seconds):
        assert turn.engine.pool.checkedout() == 0
        assert timeout_seconds > 0
        stages.append(schema_name)
        payload = json.loads(prompt)
        assert "Encontro com Deus" not in prompt
        assert "descricao" not in prompt and "mensagem_confirmacao" not in prompt
        if schema_name == "s3_route":
            answer = "restrita"
        elif schema_name == "s3_tool":
            assert "consultar_agenda" in payload["ferramentas"]
            answer = "consultar_agenda"
        else:
            pytest.fail(f"D indevido para capacidade de agenda: {schema_name}")
        assert answer in choices
        return TypedChoiceResult(
            answer,
            LLMUsage(modelo="agenda-synthetic", tokens_in=2, tokens_out=1, custo=0.0),
        )

    monkeypatch.setattr(LLMClient, "generate_typed", choose)
    return stages


def _agenda_outbound(turn):
    with turn.factory() as session:
        rows = session.execute(select(Message).where(
            Message.igreja_id == _IGREJA,
            Message.direcao == "out",
            Message.autor == "ia",
        )).scalars().all()
    return [
        row for row in rows
        if type(row.agent_privilege_context) is dict
        and row.agent_privilege_context.get("kind") == "agenda"
    ]


def _set_agenda_turn_role(turn, role: str) -> None:
    with turn.factory.begin() as session:
        session.execute(delete(UserRole).where(
            UserRole.igreja_id == _IGREJA,
            UserRole.user_id == turn.app_user_id,
        ))
        session.add(UserRole(
            igreja_id=_IGREJA,
            user_id=turn.app_user_id,
            papel=role,
        ))


def _assert_agenda_delivery(turn, evolution, outbound: list[Message]) -> None:
    assert len(outbound) == 1
    assert len(evolution.calls) == 1
    assert evolution.calls[0][2] == outbound[0].texto
    with turn.factory() as session:
        persisted = session.get(Message, outbound[0].id)
        conversation = session.get(Conversation, turn.conversation_id)
        assert persisted is not None
        assert persisted.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
        assert conversation is not None and conversation.estado == "ia"


def test_member_agenda_turn_uses_generic_choice_then_real_projection(agenda_turn, monkeypatch):
    prompts = _agenda_choices(monkeypatch, agenda_turn)
    evolution = _ClassifiedEvolution()
    inbound = _inbound(agenda_turn, "AGENDA-MEMBER", "agenda próximos 7 dias")

    assert worker_module.run_agent_for_message(
        agenda_turn.factory,
        inbound,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED

    outbound = _agenda_outbound(agenda_turn)
    _assert_agenda_delivery(agenda_turn, evolution, outbound)
    assert "Encontro com Deus" in outbound[0].texto
    assert outbound[0].public_info_reply is False
    assert outbound[0].agent_privilege_context["kind"] == "agenda"
    assert prompts == ["s3_route", "s3_tool"]


def test_leader_agenda_turn_uses_generic_choice_then_real_projection(agenda_turn, monkeypatch):
    _set_agenda_turn_role(agenda_turn, "lider_celula")
    prompts = _agenda_choices(monkeypatch, agenda_turn)
    evolution = _ClassifiedEvolution()
    inbound = _inbound(agenda_turn, "AGENDA-LEADER", "agenda próximos 7 dias")

    assert worker_module.run_agent_for_message(
        agenda_turn.factory,
        inbound,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED

    outbound = _agenda_outbound(agenda_turn)
    _assert_agenda_delivery(agenda_turn, evolution, outbound)
    assert "Encontro com Deus" in outbound[0].texto
    assert outbound[0].agent_privilege_context["kind"] == "agenda"
    assert prompts == ["s3_route", "s3_tool"]


def test_empty_agenda_prepares_existing_secretary_offer_then_sim_handoffs(agenda_turn, monkeypatch):
    with agenda_turn.factory.begin() as session:
        session.execute(delete(Event).where(Event.igreja_id == _IGREJA))
    prompts = _agenda_choices(monkeypatch, agenda_turn)
    evolution = _ClassifiedEvolution()
    request = _inbound(agenda_turn, "AGENDA-EMPTY", "agenda")

    assert worker_module.run_agent_for_message(
        agenda_turn.factory,
        request,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED
    outbound = _agenda_outbound(agenda_turn)
    assert len(outbound) == 1
    assert prompts == ["s3_route", "s3_tool"]
    with agenda_turn.factory() as session:
        conversation = session.get(Conversation, agenda_turn.conversation_id)
        assert conversation is not None
        assert conversation.secretaria_oferta_estado == "pendente"
        assert conversation.secretaria_oferta_message_id == outbound[0].id

    confirmation = _inbound(agenda_turn, "AGENDA-EMPTY-SIM", "SIM")
    assert worker_module.run_agent_for_message(
        agenda_turn.factory,
        confirmation,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED
    with agenda_turn.factory() as session:
        conversation = session.get(Conversation, agenda_turn.conversation_id)
        assert conversation is not None and conversation.estado == "humano"


def test_pending_agenda_reply_is_suppressed_when_event_changes_before_retry(agenda_turn, monkeypatch):
    prompts = _agenda_choices(monkeypatch, agenda_turn)
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    inbound = _inbound(agenda_turn, "AGENDA-RETRY", "agenda")

    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(
            agenda_turn.factory,
            inbound,
            evolution_client=evolution,
        )
    assert prompts == ["s3_route", "s3_tool"] and len(evolution.calls) == 1
    with agenda_turn.factory.begin() as session:
        event = session.execute(select(Event).where(Event.igreja_id == _IGREJA)).scalar_one()
        event.titulo = "Festa da Ana"

    assert worker_module.run_agent_for_message(
        agenda_turn.factory,
        inbound,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert prompts == ["s3_route", "s3_tool"]
    assert len(evolution.calls) == 1


@pytest.fixture
def agenda_pastor_turn(s3_turn, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", "agenda-test")
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", str(_IGREJA))
    # S3's worker fixture patches its imported settings accessors. The proof
    # verifier imports the accessor independently, so keep this synthetic
    # tenant's term and HMAC source identical at confirmation and resolution.
    settings = SimpleNamespace(
        agent_term_version="s3-test-v1",
        agent_trusted_inbound_identity_enabled=False,
        effective_session_secret="s3-secret-synthetic",
    )
    monkeypatch.setattr(agent_identity, "get_settings", lambda: settings)
    with s3_turn.factory.begin() as session:
        session.add(Event(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            titulo="Festa da Ana",
            tipo="culto",
            status="a_confirmar",
            data=dt.date.today() + dt.timedelta(days=1),
            hora="19:30",
            recorrencia="pontual",
            confirmado_em=None,
            confirmado_por=None,
        ))
    return s3_turn


def _confirm_current_challenge(turn) -> None:
    """Consume the real challenge through the local Clerk-proof service."""

    from app.db.rls import set_tenant_context_for_igreja

    now = dt.datetime.now(dt.UTC)
    with turn.factory.begin() as session:
        # The fixture mirrors a worker schema whose `current_igreja_id()` reads
        # the explicit worker GUC. The confirmation adds its Clerk claim after
        # this trusted scope is present.
        set_tenant_context_for_igreja(session, str(_IGREJA))
        challenge = session.execute(select(AgentIdentityChallenge).where(
            AgentIdentityChallenge.igreja_id == _IGREJA,
            AgentIdentityChallenge.conversation_id == turn.conversation_id,
        ).order_by(AgentIdentityChallenge.sequence.desc())).scalar_one()
        user = session.get(AppUser, turn.app_user_id)
        assert user is not None and type(user.clerk_user_id) is str
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=user.id,
            clerk_user_id=user.clerk_user_id,
            session_claims={
                "iat": (now - dt.timedelta(minutes=1)).timestamp(),
                "exp": (now + dt.timedelta(minutes=1)).timestamp(),
            },
            challenge=str(challenge.id),
            session_secret="s3-secret-synthetic",
            now=now,
        )


def test_draft_agenda_requires_clerk_proof_then_projects_only_type(agenda_pastor_turn, monkeypatch):
    prompts = _agenda_choices(monkeypatch, agenda_pastor_turn)
    evolution = _ClassifiedEvolution()
    before_proof = _inbound(agenda_pastor_turn, "AGENDA-DRAFT-CHALLENGE", "agenda rascunhos")

    assert worker_module.run_agent_for_message(
        agenda_pastor_turn.factory,
        before_proof,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED
    with agenda_pastor_turn.factory() as session:
        challenge = session.execute(select(AgentIdentityChallenge).where(
            AgentIdentityChallenge.igreja_id == _IGREJA,
        )).scalar_one()
        outbound = session.execute(select(Message).where(
            Message.igreja_id == _IGREJA,
            Message.agent_privilege_context["kind"].astext == "challenge",
        )).scalar_one()
        assert challenge.issued_from_message_id == before_proof.inbound_message_id
        assert "Festa da Ana" not in outbound.texto
    _confirm_current_challenge(agenda_pastor_turn)

    after_proof = _inbound(agenda_pastor_turn, "AGENDA-DRAFT-READ", "agenda rascunhos")
    with agenda_pastor_turn.factory() as session:
        worker_module._scope_agent_execution_session(session, after_proof, dedicated=False)
        from app.services.whatsapp_privilege import resolve_whatsapp_privilege_context

        sensitive = resolve_whatsapp_privilege_context(
            session,
            igreja_id=_IGREJA,
            conversation_id=agenda_pastor_turn.conversation_id,
            inbound_message_id=after_proof.inbound_message_id,
            sensitive=True,
        )
        assert type(sensitive) is PrivilegeContext
        assert sensitive.sensitive is True and sensitive.proof_id is not None
    assert worker_module.run_agent_for_message(
        agenda_pastor_turn.factory,
        after_proof,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED
    outbound = _agenda_outbound(agenda_pastor_turn)
    assert len(outbound) == 1
    assert "Rascunho: Culto" in outbound[0].texto
    assert "Festa da Ana" not in outbound[0].texto
    assert prompts == ["s3_route", "s3_tool", "s3_route", "s3_tool"]


@pytest.mark.parametrize("revocation", ("role", "agenda_release"))
def test_pending_agenda_reply_rechecks_role_and_feature_gate(agenda_turn, monkeypatch, revocation):
    prompts = _agenda_choices(monkeypatch, agenda_turn)
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    inbound = _inbound(agenda_turn, f"AGENDA-RETRY-{revocation}", "agenda")

    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(
            agenda_turn.factory,
            inbound,
            evolution_client=evolution,
        )
    if revocation == "role":
        with agenda_turn.factory.begin() as session:
            session.execute(delete(UserRole).where(
                UserRole.igreja_id == _IGREJA,
                UserRole.user_id == agenda_turn.app_user_id,
            ))
    else:
        monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", None)

    assert worker_module.run_agent_for_message(
        agenda_turn.factory,
        inbound,
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert prompts == ["s3_route", "s3_tool"]
    assert len(evolution.calls) == 1

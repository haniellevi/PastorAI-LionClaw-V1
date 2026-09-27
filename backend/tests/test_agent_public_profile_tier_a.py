"""PG17 proof of canonical public facts revalidated after Tier A's HTTP wait.

The disposable owner seeds fixtures. Runtime and editor sessions use the
synthetic authenticated role; no canonical row lock spans the external wait.
"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.agent import runtime
from app.agent.nodes import empty_turn_effects
from app.db.models import (
    AgentConfig,
    AgentConversationLog,
    AiUsageLog,
    Celula,
    Conversation,
    Igreja,
    LlmCredential,
)
from app.workers import queue_worker
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_messages_inbound_idempotency import (
    _IGREJA_A,
    _agent_outcome,
    _factory,
    _seed_igreja_with_connection,
    _seed_tier_a_handoff_anchor,
    msg_engine_fx,
)

pytestmark = pytest.mark.rls_integration


def _seed_public_plan(
    factory: sessionmaker, *, cell_lookup: bool = False
) -> tuple[queue_worker.IngestionOutcome, runtime.AgentTurnPlan, uuid.UUID | None]:
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-s2b")
    question = "Tem uma célula no bairro Centro?" if cell_lookup else "Que horas começa o culto?"
    conversation_id, pessoa_id, inbound_message_id = _seed_tier_a_handoff_anchor(
        factory,
        igreja_id=_IGREJA_A,
        provider_message_id="S2B-PUBLIC-TIER-A",
        texto=question,
    )
    session = factory()
    try:
        session.execute(
            update(Igreja)
            .where(Igreja.id == _IGREJA_A)
            .values(
                endereco_institucional="Rua institucional, 100",
                horarios_culto="Sábado, 18:00",
            )
        )
        cell_id = uuid.uuid4() if cell_lookup else None
        if cell_id is not None:
            session.add(
                Celula(
                    id=cell_id,
                    igreja_id=_IGREJA_A,
                    nome="Esperança",
                    bairro="Centro",
                    divulgar_whatsapp=True,
                    ativo=True,
                    dia_reuniao="Terça-feira",
                    horario="19:00",
                    cobertura_espiritual="Pastor sintético",
                    endereco="RUA-RESIDENCIAL-PRIVADA",
                )
            )
        config = AgentConfig(
            igreja_id=_IGREJA_A,
            comportamento="Tom público sintético.",
            ativo=True,
            informacoes_publicas={"horarios_culto": "LEGADO-NAO-PUBLICAR"},
        )
        credential = LlmCredential(
            igreja_id=_IGREJA_A,
            provedor="synthetic",
            modelo="synthetic",
            api_key_encrypted="synthetic",
            validado=True,
            ativo=True,
        )
        session.add_all((config, credential))
        session.commit()
        outcome = _agent_outcome(
            conversation_id,
            provider_message_id="S2B-PUBLIC-TIER-A",
            claim_id="s2b-public-tier-a",
            inbound_message_id=inbound_message_id,
        )
        draft = (
            "Há uma célula com informações públicas no bairro Centro: Esperança. "
            "Encontro: Terça-feira, 19:00. Quer falar com a secretaria da igreja "
            "para entrar em contato com o líder da célula?"
            if cell_lookup
            else "Horário de culto: Sábado, 18:00."
        )
        return outcome, runtime.AgentTurnPlan(
            igreja_id=_IGREJA_A,
            conversation_id=conversation_id,
            pessoa_id=pessoa_id,
            inbound_message_id=inbound_message_id,
            provider_message_id="S2B-PUBLIC-TIER-A",
            current_text=question,
            tier_a_input_within_limit=True,
            config_id=config.id,
            config_comportamento=config.comportamento,
            credential_id=credential.id,
            credential_provedor=credential.provedor,
            credential_model=credential.modelo,
            credential_key_encrypted=credential.api_key_encrypted,
            accepted_consent_version=None,
            term_version="s2b-public-profile",
            effects=empty_turn_effects(),
            draft_response=draft,
            system_prompt="sistema sintético",
            user_prompt="mensagem sintética",
            public_info_reply=True,
            public_info_secretaria_offer=cell_lookup,
        ), cell_id
    finally:
        session.close()


def _scope(session, outcome: queue_worker.IngestionOutcome) -> None:
    queue_worker._scope_agent_session(session, outcome)
    assert session.execute(text("select current_user")).scalar_one() == "authenticated"


def _artifacts(
    factory: sessionmaker,
    outcome: queue_worker.IngestionOutcome,
) -> tuple[list[AgentConversationLog], list[AiUsageLog], str]:
    session = factory()
    try:
        _scope(session, outcome)
        public_audit = session.execute(
            select(AgentConversationLog).where(
                AgentConversationLog.igreja_id == _IGREJA_A,
                AgentConversationLog.conversation_id == outcome.conversation_id,
                AgentConversationLog.evento == "agent_public_info_reply",
            )
        ).scalars().all()
        usages = session.execute(
            select(AiUsageLog).where(AiUsageLog.igreja_id == _IGREJA_A)
        ).scalars().all()
        estado = session.execute(
            select(Conversation.estado).where(
                Conversation.id == outcome.conversation_id,
                Conversation.igreja_id == _IGREJA_A,
            )
        ).scalar_one()
        return public_audit, usages, estado
    finally:
        session.close()


def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(agent_term_version="s2b-public-profile"),
    )


def test_canonical_hours_changed_before_apply_suppress_stale_draft(
    msg_engine_fx: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old ORM identity map cannot release a pre-HTTP church answer."""

    factory = _factory(msg_engine_fx)
    outcome, plan, _ = _seed_public_plan(factory)
    _settings(monkeypatch)
    worker_session = factory()
    editor_session = factory()
    try:
        _scope(worker_session, outcome)
        stale_church = worker_session.execute(
            select(Igreja).where(Igreja.id == _IGREJA_A)
        ).scalar_one()
        assert stale_church.horarios_culto == "Sábado, 18:00"
        worker_session.commit()  # release the pretransport transaction

        _scope(editor_session, outcome)
        editor_session.execute(
            update(Igreja)
            .where(Igreja.id == _IGREJA_A)
            .values(horarios_culto="Domingo, 19:00")
        )
        editor_session.commit()
        assert stale_church.horarios_culto == "Sábado, 18:00"

        _scope(worker_session, outcome)
        result = runtime.apply_agent_turn_plan(
            worker_session, plan=plan, response=plan.draft_response
        )
    finally:
        editor_session.close()
        worker_session.close()

    assert result.suppressed is True
    assert result.response is None
    assert result.reason == "tier_a_handoff"
    public_audit, usages, estado = _artifacts(factory, outcome)
    assert public_audit == []
    assert usages == []
    assert estado == "humano"


def test_published_cell_can_be_revoked_during_unlocked_http_wait(
    msg_engine_fx: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The editor commits before apply; the old cell answer is fenced."""

    factory = _factory(msg_engine_fx)
    outcome, plan, cell_id = _seed_public_plan(factory, cell_lookup=True)
    assert cell_id is not None
    _settings(monkeypatch)
    prepared = threading.Event()
    release_apply = threading.Event()
    editor_finished = threading.Event()
    errors: list[BaseException] = []
    results: list[runtime.AgentTurnResult] = []

    def apply_after_wait() -> None:
        session = factory()
        try:
            _scope(session, outcome)
            info = runtime.load_public_church_info(
                session, igreja_id=_IGREJA_A, bairro="centro", include_cells=True
            )
            assert info is not None and len(info.celulas) == 1
            resolution = runtime.resolve_canonical_public_info(plan.current_text, info)
            assert resolution is not None
            assert resolution.resposta == plan.draft_response
            assert resolution.oferece_secretaria is True
            session.commit()
            assert not session.in_transaction()
            prepared.set()
            assert release_apply.wait(timeout=10), "espera externa não foi liberada"
            _scope(session, outcome)
            results.append(
                runtime.apply_agent_turn_plan(
                    session, plan=plan, response=plan.draft_response
                )
            )
        except BaseException as exc:
            errors.append(exc)
            prepared.set()
        finally:
            session.close()

    def revoke_publication() -> None:
        session = factory()
        try:
            _scope(session, outcome)
            session.execute(
                update(Celula)
                .where(Celula.id == cell_id, Celula.igreja_id == _IGREJA_A)
                .values(divulgar_whatsapp=False)
            )
            session.commit()
            editor_finished.set()
        except BaseException as exc:
            errors.append(exc)
        finally:
            session.close()

    apply_thread = threading.Thread(target=apply_after_wait, daemon=True)
    editor_thread = threading.Thread(target=revoke_publication, daemon=True)
    try:
        apply_thread.start()
        assert prepared.wait(timeout=5), "pré-transporte não concluiu"
        assert not errors
        editor_thread.start()
        assert editor_finished.wait(timeout=5), "editor bloqueado durante espera externa"
    finally:
        release_apply.set()
        apply_thread.join(timeout=10)
        if editor_thread.ident is not None:
            editor_thread.join(timeout=10)

    assert not apply_thread.is_alive() and not editor_thread.is_alive()
    assert errors == []
    assert len(results) == 1
    assert results[0].suppressed is True
    assert results[0].response is None
    assert results[0].reason == "tier_a_handoff"
    public_audit, usages, estado = _artifacts(factory, outcome)
    assert public_audit == []
    assert usages == []
    assert estado == "humano"

    session = factory()
    try:
        _scope(session, outcome)
        assert session.execute(
            select(Celula.divulgar_whatsapp).where(
                Celula.id == cell_id, Celula.igreja_id == _IGREJA_A
            )
        ).scalar_one() is False
    finally:
        session.close()


def test_unchanged_canonical_hours_are_replied_without_llm_usage(
    msg_engine_fx: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching post-wait fact still yields the approved public answer."""

    factory = _factory(msg_engine_fx)
    outcome, plan, _ = _seed_public_plan(factory)
    _settings(monkeypatch)
    session = factory()
    try:
        _scope(session, outcome)
        result = runtime.apply_agent_turn_plan(
            session, plan=plan, response=plan.draft_response
        )
    finally:
        session.close()

    assert result.response == "Horário de culto: Sábado, 18:00."
    assert "LEGADO-NAO-PUBLICAR" not in result.response
    assert result.suppressed is False
    public_audit, usages, estado = _artifacts(factory, outcome)
    assert len(public_audit) == 1
    assert public_audit[0].payload is None
    assert usages == []
    assert estado == "ia"

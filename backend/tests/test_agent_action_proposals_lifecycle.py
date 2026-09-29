"""Transaction-local contracts for S3 proposal delivery and confirmation."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
import uuid

import pytest

from app.services.agent_action_proposals import (
    ActionEffect,
    AgentAction,
    ProposalDisposition,
    ProposalResolutionStatus,
    ProposalTarget,
    canonical_arguments_sha256,
    cancel_action_proposal_for_term_change,
    invalidate_action_proposal_for_delivery,
    promote_action_proposal_after_delivery,
    resolve_and_execute_action_proposal,
)
from app.services.whatsapp_privilege import PrivilegeContext


_NOW = dt.datetime(2026, 9, 27, 12, tzinfo=dt.timezone.utc)
_IGREJA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_CONVERSA = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_PROPOSTA = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
_SOURCE = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_SUMMARY = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
_CONFIRM = uuid.UUID("00000000-0000-0000-0000-0000000000d3")
_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
_USER = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


class _Result:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, values=()) -> None:
        self.values = list(values)
        self.added = []

    def execute(self, _statement):
        if not self.values:
            raise AssertionError("consulta inesperada")
        return _Result(self.values.pop(0))

    def add(self, value) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid.UUID("00000000-0000-0000-0000-0000000000a3")
        self.added.append(value)

    def flush(self) -> None:
        return None


def _context() -> PrivilegeContext:
    return PrivilegeContext(
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=_CONFIRM,
        pessoa_id=_PESSOA,
        app_user_id=_USER,
        roles=frozenset({"membro"}),
        role_snapshot=((uuid.UUID("00000000-0000-0000-0000-0000000000e1"), "membro"),),
        owned_cell_ids=(),
        credential_fingerprint="1" * 64,
        phone_fingerprint="2" * 64,
        authorization_fingerprint="3" * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="4" * 64,
        context_fingerprint="5" * 64,
    )


def _proposal(state: str = "pendente") -> SimpleNamespace:
    arguments = {"pessoa_id": str(_PESSOA), "vinculo": "celula", "celula_id": None}
    return SimpleNamespace(
        id=_PROPOSTA,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        actor_pessoa_id=_PESSOA,
        actor_app_user_id=_USER,
        source_message_id=_SOURCE,
        action="registrar_decisao",
        target_kind="pessoa",
        target_id=_PESSOA,
        arguments_json=arguments,
        arguments_sha256=canonical_arguments_sha256(arguments),
        scope_fingerprint="4" * 64,
        summary_sha256="a" * 64,
        state=state,
        summary_message_id=_SUMMARY,
        confirmation_message_id=None,
        delivered_at=_NOW - dt.timedelta(seconds=1),
        expires_at=_NOW + dt.timedelta(minutes=10),
        executed_at=None,
        terminal_reason=None,
    )


def _patch_resolution(monkeypatch, proposal, context=_context()) -> None:
    import app.services.agent_action_proposals as proposals

    monkeypatch.setattr(proposals, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        proposals,
        "_active_proposal_for_resolution",
        lambda *args, **kwargs: (SimpleNamespace(), proposal, None),
    )
    monkeypatch.setattr(proposals, "_database_now", lambda *_args, **_kwargs: _NOW)
    monkeypatch.setattr(proposals, "_confirmation_is_after_delivery", lambda *args, **kwargs: True)
    monkeypatch.setattr(proposals, "_confirmed_summary_is_current", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        proposals, "_proposal_context_is_current", lambda *args, **kwargs: context
    )
    monkeypatch.setattr(
        proposals,
        "_execution_context",
        lambda *args, **kwargs: SimpleNamespace(proposal_id=_PROPOSTA),
    )


def test_confirm_executes_once_and_creates_generic_receipt_in_same_session(monkeypatch) -> None:
    proposal = _proposal()
    _patch_resolution(monkeypatch, proposal)
    session = _Session()
    calls = []

    result = resolve_and_execute_action_proposal(
        session,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        confirmation_message_id=_CONFIRM,
        disposition=ProposalDisposition.CONFIRM,
        execute=lambda execution: (
            calls.append(execution)
            or ActionEffect(
                receipt_text="Registro confirmado.",
                opaque_effect_id=uuid.UUID("00000000-0000-0000-0000-0000000000e3"),
            )
        ),
    )

    assert result.status is ProposalResolutionStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.receipt_text == "Registro confirmado."
    assert len(calls) == 1
    assert proposal.state == "executada"
    assert proposal.confirmation_message_id == _CONFIRM
    assert len(session.added) == 1


def test_agenda_reminder_confirmation_keeps_the_distinct_receipt_and_one_effect(monkeypatch) -> None:
    proposal = _proposal()
    event_id = uuid.UUID("00000000-0000-0000-0000-0000000000e5")
    proposal.action = "configurar_lembrete_agenda"
    proposal.target_kind = "evento"
    proposal.target_id = event_id
    proposal.arguments_json = {
        "event_id": str(event_id),
        "occurrence_at": "2026-10-02T13:00:00.000000+00:00",
        "term_version": "lgpd-v2",
    }
    proposal.arguments_sha256 = canonical_arguments_sha256(proposal.arguments_json)
    _patch_resolution(monkeypatch, proposal)
    calls = []

    result = resolve_and_execute_action_proposal(
        _Session(),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        confirmation_message_id=_CONFIRM,
        disposition=ProposalDisposition.CONFIRM,
        execute=lambda execution: (
            calls.append(execution)
            or ActionEffect(
                receipt_text="Lembrete confirmado.",
                opaque_effect_id=uuid.UUID("00000000-0000-0000-0000-0000000000e6"),
            )
        ),
    )

    assert result.status is ProposalResolutionStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.receipt_text == "Lembrete confirmado."
    assert len(calls) == 1


def test_invalidated_context_never_calls_domain_executor(monkeypatch) -> None:
    proposal = _proposal()
    _patch_resolution(monkeypatch, proposal, context=None)
    session = _Session()

    result = resolve_and_execute_action_proposal(
        session,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        confirmation_message_id=_CONFIRM,
        disposition="confirm",
        execute=lambda _execution: pytest.fail("executor não pode rodar"),
    )

    assert result.status is ProposalResolutionStatus.CANCELLED
    assert proposal.state == "cancelada"
    assert proposal.confirmation_message_id == _CONFIRM


def test_confirmation_before_summary_delivery_stays_non_consuming(monkeypatch) -> None:
    proposal = _proposal(state="preparada")
    _patch_resolution(monkeypatch, proposal)

    result = resolve_and_execute_action_proposal(
        _Session(),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        confirmation_message_id=_CONFIRM,
        disposition="confirm",
        execute=lambda _execution: pytest.fail("executor não pode rodar"),
    )

    assert result.status is ProposalResolutionStatus.DELIVERY_UNCERTAIN
    assert proposal.state == "preparada"


def test_promote_requires_confirmed_summary_before_starting_ttl(monkeypatch) -> None:
    import app.services.agent_action_proposals as proposals

    proposal = _proposal(state="preparada")
    proposal.summary_message_id = _SUMMARY
    summary = SimpleNamespace(
        id=_SUMMARY,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        direcao="out",
        autor="ia",
        agent_reply_state="ia",
        texto="Resumo de proposta.",
    )
    import hashlib

    proposal.summary_sha256 = hashlib.sha256(summary.texto.encode()).hexdigest()
    monkeypatch.setattr(proposals, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(proposals, "_lock_conversation", lambda *args, **kwargs: object())
    session = _Session([proposal, summary])

    pending = promote_action_proposal_after_delivery(
        session,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        proposal_id=_PROPOSTA,
        summary_message_id=_SUMMARY,
        now=_NOW,
    )

    assert pending.expires_at == _NOW + dt.timedelta(minutes=10)
    assert proposal.state == "pendente"


def test_delivery_invalidation_cancels_active_but_never_resurrects_terminal(monkeypatch) -> None:
    import app.services.agent_action_proposals as proposals

    proposal = _proposal()
    monkeypatch.setattr(proposals, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(proposals, "_lock_conversation", lambda *args, **kwargs: object())
    result = invalidate_action_proposal_for_delivery(
        _Session([proposal]),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        proposal_id=_PROPOSTA,
    )

    assert result.status is ProposalResolutionStatus.CANCELLED
    assert proposal.state == "cancelada"


def test_stale_term_cancels_confirmation_before_the_lgpd_flow(monkeypatch) -> None:
    import app.services.agent_action_proposals as proposals

    proposal = _proposal()
    monkeypatch.setattr(proposals, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        proposals,
        "_active_proposal_for_resolution",
        lambda *args, **kwargs: (SimpleNamespace(), proposal, None),
    )
    monkeypatch.setattr(proposals, "_inbound_exists", lambda *args, **kwargs: object())

    result = cancel_action_proposal_for_term_change(
        _Session(),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=_CONFIRM,
    )

    assert result.status is ProposalResolutionStatus.CANCELLED
    assert proposal.confirmation_message_id == _CONFIRM
    assert proposal.terminal_reason == "term_changed"

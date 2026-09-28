"""Offline contract for S3's durable WhatsApp action proposals."""

from __future__ import annotations

import pytest
import uuid
import hashlib
from types import SimpleNamespace

from app.services.agent_action_proposals import (
    AgentAction,
    AgentActionProposal,
    AgentActionReceipt,
    ProposalTarget,
    ProposalContractError,
    ProposalDisposition,
    ActionEffect,
    PrivilegeContext,
    PreparedActionProposal,
    canonical_action_arguments,
    parse_agent_action,
    parse_proposal_disposition,
    prepare_action_proposal,
)


def test_action_catalog_is_closed_to_the_two_approved_actions() -> None:
    assert parse_agent_action("registrar_decisao") is AgentAction.REGISTRAR_DECISAO
    assert parse_agent_action("marcar_presenca") is AgentAction.MARCAR_PRESENCA

    for value in ("", "marcar_presencas", "financeiro", True, None):
        with pytest.raises(ProposalContractError):
            parse_agent_action(value)


def test_cell_report_action_uses_a_server_owned_meeting_target() -> None:
    meeting_id = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
    draft_id = uuid.UUID("00000000-0000-0000-0000-0000000000d2")

    assert parse_agent_action("enviar_relatorio_celula") is AgentAction.ENVIAR_RELATORIO_CELULA
    target = ProposalTarget(kind="reuniao", id=meeting_id)
    assert canonical_action_arguments(
        AgentAction.ENVIAR_RELATORIO_CELULA,
        target,
        {"reuniao_id": str(meeting_id), "rascunho_id": str(draft_id), "revisao": 3},
    ) == {
        "rascunho_id": str(draft_id),
        "reuniao_id": str(meeting_id),
        "revisao": 3,
    }

    with pytest.raises(ProposalContractError):
        canonical_action_arguments(
            AgentAction.ENVIAR_RELATORIO_CELULA,
            target,
            {"reuniao_id": str(meeting_id), "rascunho_id": str(draft_id), "texto": "forjado"},
        )


def test_confirmation_disposition_is_closed_before_any_router_or_model_call() -> None:
    assert parse_proposal_disposition("confirm") is ProposalDisposition.CONFIRM
    assert parse_proposal_disposition("reject") is ProposalDisposition.REJECT
    assert parse_proposal_disposition("other") is ProposalDisposition.OTHER
    for value in ("sim", "", None, True):
        with pytest.raises(ProposalContractError):
            parse_proposal_disposition(value)
    assert parse_proposal_disposition(ProposalDisposition.CONFIRM) is ProposalDisposition.CONFIRM


def test_action_enum_is_accepted_by_the_service_contract_and_receipt_is_generic() -> None:
    assert parse_agent_action(AgentAction.MARCAR_PRESENCA) is AgentAction.MARCAR_PRESENCA
    effect = ActionEffect(
        receipt_text="Registro confirmado.",
        opaque_effect_id=uuid.UUID("00000000-0000-0000-0000-0000000000e3"),
    )
    assert effect.receipt_text == "Registro confirmado."
    with pytest.raises(ProposalContractError):
        ActionEffect(receipt_text="detalhe privado", opaque_effect_id=uuid.uuid4())


def test_cell_report_receipt_is_closed_and_distinct_from_other_actions() -> None:
    effect = ActionEffect(
        receipt_text="Relatório confirmado.",
        opaque_effect_id=uuid.UUID("00000000-0000-0000-0000-0000000000e4"),
    )
    assert effect.receipt_text == "Relatório confirmado."


def test_proposal_models_bind_one_tenant_conversation_actor_and_receipt() -> None:
    proposal_constraints = {
        constraint.name for constraint in AgentActionProposal.__table__.constraints
    }
    receipt_constraints = {
        constraint.name for constraint in AgentActionReceipt.__table__.constraints
    }

    assert "agent_action_proposals_tenant_conversation_fkey" in proposal_constraints
    assert "agent_action_proposals_tenant_actor_pessoa_fkey" in proposal_constraints
    assert "agent_action_proposals_target_kind_closed" in proposal_constraints
    assert "agent_action_proposals_receipt_once_key" in receipt_constraints
    assert "agent_action_receipts_receipt_text_closed" in receipt_constraints
    assert {"effect_reference", "receipt_text", "confirmation_message_id"} <= set(
        AgentActionReceipt.__table__.columns.keys()
    )


def test_action_arguments_accept_only_the_two_server_adapter_shapes() -> None:
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
    reuniao_id = uuid.UUID("00000000-0000-0000-0000-0000000000e2")

    decision = canonical_action_arguments(
        AgentAction.REGISTRAR_DECISAO,
        ProposalTarget(kind="pessoa", id=pessoa_id),
        {"pessoa_id": str(pessoa_id), "vinculo": "celula", "celula_id": None},
    )
    assert decision == {
        "celula_id": None,
        "pessoa_id": str(pessoa_id),
        "vinculo": "celula",
    }

    attendance = canonical_action_arguments(
        AgentAction.MARCAR_PRESENCA,
        ProposalTarget(kind="pessoa", id=pessoa_id),
        {"pessoa_id": str(pessoa_id), "reuniao_id": str(reuniao_id)},
    )
    assert attendance["reuniao_id"] == str(reuniao_id)

    for invalid in (
        {"pessoa_id": str(pessoa_id), "vinculo": "celula", "origem": "forjada"},
        {"pessoa_id": str(pessoa_id), "vinculo": "outro", "celula_id": None},
        {"pessoa_id": str(pessoa_id), "reuniao_id": str(reuniao_id), "quantidade": 2},
    ):
        with pytest.raises(ProposalContractError):
            canonical_action_arguments(
                AgentAction.REGISTRAR_DECISAO
                if "vinculo" in invalid
                else AgentAction.MARCAR_PRESENCA,
                ProposalTarget(kind="pessoa", id=pessoa_id),
                invalid,
            )


def test_prepare_accepts_operational_context_without_clerk_proof(monkeypatch) -> None:
    import app.services.agent_action_proposals as proposals

    igreja_id = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    conversation_id = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
    inbound_message_id = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        pessoa_id=pessoa_id,
        app_user_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
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

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        def execute(self, _statement):
            return _Result()

        def add(self, value):
            value.id = uuid.UUID("00000000-0000-0000-0000-0000000000a2")

        def flush(self):
            return None

    monkeypatch.setattr(proposals, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        proposals,
        "_lock_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(
            estado="ia", assumido_por=None, secretaria_oferta_estado=None
        ),
    )
    monkeypatch.setattr(proposals, "_inbound_exists", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(proposals, "_load_active_proposal", lambda *_args, **_kwargs: None)

    prepared = prepare_action_proposal(
        _Session(),
        context=context,
        inbound_message_id=inbound_message_id,
        action=AgentAction.REGISTRAR_DECISAO,
        target=ProposalTarget(kind="pessoa", id=pessoa_id),
        arguments={"pessoa_id": str(pessoa_id), "vinculo": "celula", "celula_id": None},
        summary="Confirme o registro.",
    )
    assert isinstance(prepared, PreparedActionProposal)


def test_prepare_reuses_same_active_source_without_renewing_or_resurrecting(monkeypatch) -> None:
    import app.services.agent_action_proposals as proposals

    igreja_id = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    conversation_id = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
    inbound_message_id = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        pessoa_id=pessoa_id,
        app_user_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
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
    summary = "Confirme o registro."
    arguments = {"pessoa_id": str(pessoa_id), "vinculo": "celula", "celula_id": None}
    existing = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000a2"),
        conversation_id=conversation_id,
        action="registrar_decisao",
        target_kind="pessoa",
        target_id=pessoa_id,
        arguments_sha256=proposals.canonical_arguments_sha256(arguments),
        summary_sha256=hashlib.sha256(summary.encode()).hexdigest(),
        summary_message_id=None,
        state="pendente",
    )

    class _Result:
        def scalar_one_or_none(self):
            return existing

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(proposals, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        proposals,
        "_lock_conversation",
        lambda *_args, **_kwargs: SimpleNamespace(
            estado="ia", assumido_por=None, secretaria_oferta_estado=None
        ),
    )
    monkeypatch.setattr(proposals, "_inbound_exists", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        proposals,
        "_load_active_proposal",
        lambda *_args, **_kwargs: pytest.fail("não deve criar proposta concorrente"),
    )

    replay = prepare_action_proposal(
        _Session(),
        context=context,
        inbound_message_id=inbound_message_id,
        action=AgentAction.REGISTRAR_DECISAO,
        target=ProposalTarget(kind="pessoa", id=pessoa_id),
        arguments=arguments,
        summary=summary,
    )
    assert replay.proposal_id == existing.id

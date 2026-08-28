"""Adversarial tests for the inactive purpose-consent RBAC contract."""

from __future__ import annotations

import itertools
import pathlib
import uuid
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace

import pytest

from app.domain.purpose_consent import PurposeConsentPurpose
from app.domain.purpose_consent_security import (
    ConsentSecurityContext,
    KNOWN_PANEL_ROLES,
    PanelAccessStatus,
    PanelConsentContext,
    PurposeConsentAction,
    PurposeConsentCapability,
    PurposeConsentScope,
    WhatsAppSelfConsentContext,
    consent_action_allowed,
    consent_capabilities,
)


TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000002")
PERSON_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
OTHER_PERSON_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")
ACTOR_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
CONVERSATION_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
OTHER_CONVERSATION_ID = uuid.UUID("40000000-0000-0000-0000-000000000002")
MESSAGE_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")


def _whatsapp_context(**overrides: object) -> WhatsAppSelfConsentContext:
    values: dict[str, object] = {
        "igreja_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "conversation_igreja_id": TENANT_ID,
        "pessoa_id": PERSON_ID,
        "conversation_pessoa_id": PERSON_ID,
        "message_id": MESSAGE_ID,
        "message_igreja_id": TENANT_ID,
        "message_conversation_id": CONVERSATION_ID,
        "target_igreja_id": TENANT_ID,
        "target_pessoa_id": PERSON_ID,
        "message_is_inbound": True,
        "active_pessoa_match_count": 1,
        "sem_interesse": False,
    }
    values.update(overrides)
    return WhatsAppSelfConsentContext(**values)  # type: ignore[arg-type]


def _panel_context(role: str = "membro", **overrides: object) -> PanelConsentContext:
    values: dict[str, object] = {
        "igreja_id": TENANT_ID,
        "actor_app_user_id": ACTOR_ID,
        "actor_igreja_id": TENANT_ID,
        "actor_pessoa_id": PERSON_ID,
        "target_igreja_id": TENANT_ID,
        "target_pessoa_id": PERSON_ID,
        "roles": frozenset({role}),
        "access_status": PanelAccessStatus.ACTIVE,
        "authenticated_clerk_subject": "user_synthetic",
        "persisted_clerk_user_id": "user_synthetic",
        "usable_access_count": 1,
        "has_assigned_conversation_scope": True,
        "has_active_cell_scope": True,
        "has_responsibility_scope": True,
        "sem_interesse": False,
        "is_platform_admin": False,
    }
    values.update(overrides)
    return PanelConsentContext(**values)  # type: ignore[arg-type]


def _expected_panel_decision(
    role: str,
    purpose: PurposeConsentPurpose,
    action: PurposeConsentAction,
    scope: PurposeConsentScope,
) -> bool:
    if action is PurposeConsentAction.GRANT:
        return False
    if action is PurposeConsentAction.WITHDRAW:
        return scope is PurposeConsentScope.SELF
    if action is PurposeConsentAction.READ_AUDIT:
        return role == "admin" and scope is PurposeConsentScope.TENANT
    if action is not PurposeConsentAction.READ_EFFECTIVE:
        return False
    if scope is PurposeConsentScope.SELF:
        return True
    if scope is PurposeConsentScope.TENANT:
        return role in {"admin", "pastor"}
    if scope is PurposeConsentScope.RESPONSIBILITY:
        return role in {"lider_g12", "lider_consol"} and purpose in {
            PurposeConsentPurpose.CUIDADO_PASTORAL,
            PurposeConsentPurpose.TAREFAS_OPERACIONAIS,
        }
    if scope is PurposeConsentScope.ACTIVE_CELL:
        return role == "lider_celula" and purpose in {
            PurposeConsentPurpose.CUIDADO_PASTORAL,
            PurposeConsentPurpose.TAREFAS_OPERACIONAIS,
        }
    if scope is PurposeConsentScope.ASSIGNED_CONVERSATION:
        return (
            role == "operador"
            and purpose is PurposeConsentPurpose.ATENDIMENTO_SOLICITADO
        )
    return False


@pytest.mark.parametrize(
    ("role", "purpose", "action", "scope"),
    list(
        itertools.product(
            sorted(KNOWN_PANEL_ROLES),
            tuple(PurposeConsentPurpose),
            tuple(PurposeConsentAction),
            tuple(PurposeConsentScope),
        )
    ),
)
def test_panel_role_action_scope_product_is_deny_first(
    role: str,
    purpose: PurposeConsentPurpose,
    action: PurposeConsentAction,
    scope: PurposeConsentScope,
) -> None:
    assert consent_action_allowed(_panel_context(role), purpose, action, scope) is (
        _expected_panel_decision(role, purpose, action, scope)
    )


@pytest.mark.parametrize(
    ("purpose", "action", "scope"),
    list(
        itertools.product(
            tuple(PurposeConsentPurpose),
            tuple(PurposeConsentAction),
            tuple(PurposeConsentScope),
        )
    ),
)
def test_whatsapp_product_allows_only_self_effective_read_and_withdrawal(
    purpose: PurposeConsentPurpose,
    action: PurposeConsentAction,
    scope: PurposeConsentScope,
) -> None:
    expected = scope is PurposeConsentScope.SELF and action in {
        PurposeConsentAction.READ_EFFECTIVE,
        PurposeConsentAction.WITHDRAW,
    }
    assert consent_action_allowed(
        _whatsapp_context(), purpose, action, scope
    ) is expected


def test_contexts_are_frozen_and_slotted() -> None:
    whatsapp = _whatsapp_context()
    panel = _panel_context()

    assert not hasattr(whatsapp, "__dict__")
    assert not hasattr(panel, "__dict__")
    with pytest.raises(FrozenInstanceError):
        whatsapp.pessoa_id = OTHER_PERSON_ID  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        panel.roles = frozenset({"admin"})  # type: ignore[misc]


def test_capability_sets_are_explicit_and_never_contain_any_grant() -> None:
    assert consent_capabilities(_whatsapp_context()) == {
        PurposeConsentCapability.READ_SELF_EFFECTIVE,
        PurposeConsentCapability.RECORD_SELF_WITHDRAWAL,
    }
    assert consent_capabilities(_panel_context("admin")) == {
        PurposeConsentCapability.READ_SELF_EFFECTIVE,
        PurposeConsentCapability.READ_TENANT_EFFECTIVE,
        PurposeConsentCapability.READ_TENANT_AUDIT,
        PurposeConsentCapability.RECORD_SELF_WITHDRAWAL,
    }

    disabled = {
        PurposeConsentCapability.RECORD_SELF_GRANT_DISABLED,
        PurposeConsentCapability.RECORD_PANEL_GRANT_DISABLED,
        PurposeConsentCapability.RECORD_PANEL_WITHDRAWAL_DISABLED,
    }
    for role in KNOWN_PANEL_ROLES:
        assert consent_capabilities(_panel_context(role)).isdisjoint(disabled)


def test_accumulated_known_roles_union_only_explicit_capabilities() -> None:
    context = _panel_context(
        roles=frozenset({"membro", "operador", "lider_celula", "pastor"})
    )
    assert consent_capabilities(context) == {
        PurposeConsentCapability.READ_SELF_EFFECTIVE,
        PurposeConsentCapability.READ_ASSIGNED_EFFECTIVE,
        PurposeConsentCapability.READ_ACTIVE_CELL_EFFECTIVE,
        PurposeConsentCapability.READ_TENANT_EFFECTIVE,
        PurposeConsentCapability.RECORD_SELF_WITHDRAWAL,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conversation_igreja_id", OTHER_TENANT_ID),
        ("message_igreja_id", OTHER_TENANT_ID),
        ("target_igreja_id", OTHER_TENANT_ID),
        ("conversation_pessoa_id", OTHER_PERSON_ID),
        ("target_pessoa_id", OTHER_PERSON_ID),
        ("message_conversation_id", OTHER_CONVERSATION_ID),
        ("message_is_inbound", False),
        ("active_pessoa_match_count", 0),
        ("active_pessoa_match_count", 2),
        ("igreja_id", uuid.UUID(int=0)),
        ("conversation_id", uuid.UUID(int=0)),
        ("pessoa_id", uuid.UUID(int=0)),
        ("message_id", uuid.UUID(int=0)),
        ("sem_interesse", "false"),
    ],
)
def test_whatsapp_identity_or_context_divergence_denies_everything(
    field: str, value: object
) -> None:
    context = replace(_whatsapp_context(), **{field: value})
    assert consent_capabilities(context) == frozenset()
    for purpose, action, scope in itertools.product(
        tuple(PurposeConsentPurpose),
        tuple(PurposeConsentAction),
        tuple(PurposeConsentScope),
    ):
        assert consent_action_allowed(context, purpose, action, scope) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_igreja_id", OTHER_TENANT_ID),
        ("target_igreja_id", OTHER_TENANT_ID),
        ("access_status", PanelAccessStatus.INVITED),
        ("access_status", PanelAccessStatus.REVOKED),
        ("access_status", None),
        ("access_status", "legacy_active"),
        ("access_status", "ativo"),
        ("authenticated_clerk_subject", None),
        ("authenticated_clerk_subject", ""),
        ("authenticated_clerk_subject", " user_synthetic"),
        ("persisted_clerk_user_id", None),
        ("persisted_clerk_user_id", ""),
        ("persisted_clerk_user_id", "user_other"),
        ("usable_access_count", 0),
        ("usable_access_count", 2),
        ("usable_access_count", True),
        ("roles", frozenset()),
        ("roles", frozenset({"admin", "future_super_role"})),
        ("roles", {"admin"}),
        ("is_platform_admin", True),
        ("actor_app_user_id", uuid.UUID(int=0)),
        ("target_pessoa_id", uuid.UUID(int=0)),
        ("actor_pessoa_id", "not-a-uuid"),
        ("has_assigned_conversation_scope", 1),
        ("sem_interesse", 0),
    ],
)
def test_invalid_panel_identity_status_roles_or_platform_context_denies_everything(
    field: str, value: object
) -> None:
    context = replace(_panel_context("admin"), **{field: value})
    assert consent_capabilities(context) == frozenset()
    for purpose, action, scope in itertools.product(
        tuple(PurposeConsentPurpose),
        tuple(PurposeConsentAction),
        tuple(PurposeConsentScope),
    ):
        assert consent_action_allowed(context, purpose, action, scope) is False


def test_authenticated_subject_matches_exactly_one_linked_active_access() -> None:
    context = _panel_context("membro", access_status=PanelAccessStatus.ACTIVE)
    assert consent_action_allowed(
        context,
        PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        PurposeConsentAction.READ_EFFECTIVE,
        PurposeConsentScope.SELF,
    ) is True


def test_scope_evidence_is_required_for_restricted_panel_reads() -> None:
    cases = (
        (
            _panel_context("operador", has_assigned_conversation_scope=False),
            PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            PurposeConsentScope.ASSIGNED_CONVERSATION,
        ),
        (
            _panel_context("lider_celula", has_active_cell_scope=False),
            PurposeConsentPurpose.CUIDADO_PASTORAL,
            PurposeConsentScope.ACTIVE_CELL,
        ),
        (
            _panel_context("lider_g12", has_responsibility_scope=False),
            PurposeConsentPurpose.TAREFAS_OPERACIONAIS,
            PurposeConsentScope.RESPONSIBILITY,
        ),
    )
    for context, purpose, scope in cases:
        assert consent_action_allowed(
            context, purpose, PurposeConsentAction.READ_EFFECTIVE, scope
        ) is False


def test_self_scope_requires_actor_person_to_match_target() -> None:
    context = _panel_context(actor_pessoa_id=OTHER_PERSON_ID)
    assert consent_action_allowed(
        context,
        PurposeConsentPurpose.CUIDADO_PASTORAL,
        PurposeConsentAction.READ_EFFECTIVE,
        PurposeConsentScope.SELF,
    ) is False
    assert consent_action_allowed(
        context,
        PurposeConsentPurpose.CUIDADO_PASTORAL,
        PurposeConsentAction.WITHDRAW,
        PurposeConsentScope.SELF,
    ) is False


@pytest.mark.parametrize("factory", [_whatsapp_context, _panel_context])
def test_sem_interesse_preserves_self_read_and_withdrawal(
    factory: Callable[..., ConsentSecurityContext],
) -> None:
    context = factory(sem_interesse=True)
    for purpose, action in itertools.product(
        tuple(PurposeConsentPurpose),
        (PurposeConsentAction.READ_EFFECTIVE, PurposeConsentAction.WITHDRAW),
    ):
        assert consent_action_allowed(
            context,
            purpose,
            action,
            PurposeConsentScope.SELF,
        ) is True


@pytest.mark.parametrize("purpose", tuple(PurposeConsentPurpose))
def test_sem_interesse_removes_operational_reads_but_keeps_admin_audit(
    purpose: PurposeConsentPurpose,
) -> None:
    denied = (
        (_panel_context("admin", sem_interesse=True), PurposeConsentScope.TENANT),
        (_panel_context("pastor", sem_interesse=True), PurposeConsentScope.TENANT),
        (
            _panel_context("operador", sem_interesse=True),
            PurposeConsentScope.ASSIGNED_CONVERSATION,
        ),
        (
            _panel_context("lider_celula", sem_interesse=True),
            PurposeConsentScope.ACTIVE_CELL,
        ),
        (
            _panel_context("lider_g12", sem_interesse=True),
            PurposeConsentScope.RESPONSIBILITY,
        ),
    )
    for context, scope in denied:
        assert consent_action_allowed(
            context,
            purpose,
            PurposeConsentAction.READ_EFFECTIVE,
            scope,
        ) is False

    admin = _panel_context("admin", sem_interesse=True)
    assert consent_action_allowed(
        admin,
        purpose,
        PurposeConsentAction.READ_AUDIT,
        PurposeConsentScope.TENANT,
    ) is True
    assert consent_action_allowed(
        _panel_context("pastor", sem_interesse=True),
        purpose,
        PurposeConsentAction.READ_AUDIT,
        PurposeConsentScope.TENANT,
    ) is False


def test_raw_action_scope_unknown_context_and_subclasses_fail_closed() -> None:
    class ForgedPanelContext(PanelConsentContext):
        pass

    panel = _panel_context("admin")
    forged = ForgedPanelContext(
        **{
            field: getattr(panel, field)
            for field in panel.__dataclass_fields__
        }
    )
    assert consent_capabilities(object()) == frozenset()
    assert consent_capabilities(forged) == frozenset()
    assert consent_action_allowed(
        panel,
        "atendimento_solicitado",  # type: ignore[arg-type]
        PurposeConsentAction.READ_EFFECTIVE,
        PurposeConsentScope.TENANT,
    ) is False
    assert consent_action_allowed(
        panel,
        PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        "read_effective",  # type: ignore[arg-type]
        PurposeConsentScope.TENANT,
    ) is False
    assert consent_action_allowed(
        panel,
        PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        PurposeConsentAction.READ_EFFECTIVE,
        "tenant",  # type: ignore[arg-type]
    ) is False


def test_contract_has_no_channel_data_api_or_runtime_caller() -> None:
    repository_root = pathlib.Path(__file__).resolve().parents[2]
    roots = (
        repository_root / "backend" / "app" / "routers",
        repository_root / "backend" / "app" / "workers",
        repository_root / "backend" / "app" / "agent",
        repository_root / "frontend",
        repository_root / "supabase",
    )
    tokens = (
        "purpose_consent_security",
        "PurposeConsentAction",
        "PurposeConsentScope",
        "PurposeConsentCapability",
        "WhatsAppSelfConsentContext",
        "PanelConsentContext",
        "consent_action_allowed",
        "consent_capabilities",
        "append_purpose_consent_event",
        "load_purpose_consent_snapshot",
        "consentimento_finalidade_evento",
    )
    suffixes = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".sql",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
    }
    generated_directories = {"node_modules", ".next", "dist", "build", "coverage"}
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if any(part in generated_directories for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in tokens):
                offenders.append(path.relative_to(repository_root).as_posix())

    assert offenders == []

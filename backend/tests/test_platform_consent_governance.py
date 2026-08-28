"""Adversarial API tests for the D2B2b3A Master draft workspace."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.models import PlatformAuditLog
from app.deps import PlatformAdminUser
from app.domain.purpose_consent import (
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentPurpose,
)
from app.domain.purpose_consent_governance import (
    PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
    PurposeConsentGovernancePurposeSnapshot,
    PurposeConsentGovernanceSnapshot,
    PurposeConsentGovernanceStatus,
    empty_purpose_consent_governance_content,
)
from app.routers import platform_consent_governance as router_module
from app.services.purpose_consent_governance import (
    PurposeConsentGovernanceRevisionConflictError,
)


class _DB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


CHURCH_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
ACTOR_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")
ADMIN = PlatformAdminUser(
    app_user_id=str(ACTOR_ID),
    clerk_user_id="master-session-subject",
    email="master@example.invalid",
    nome="Master",
)


def _snapshot(*, revision: int = 1) -> PurposeConsentGovernanceSnapshot:
    now = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.timezone.utc)
    return PurposeConsentGovernanceSnapshot(
        igreja_id=CHURCH_ID,
        schema_version=PURPOSE_CONSENT_GOVERNANCE_SCHEMA_VERSION,
        revision=revision,
        purposes=tuple(
            PurposeConsentGovernancePurposeSnapshot(
                purpose=purpose,
                revision=revision,
                status=PurposeConsentGovernanceStatus.DRAFT_NOT_APPROVED,
                decision_payload=empty_purpose_consent_governance_content(),
            )
            for purpose in PURPOSE_CONSENT_PURPOSES
        ),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> _DB:
    db = _DB()
    monkeypatch.setattr(
        router_module,
        "get_settings",
        lambda: SimpleNamespace(
            purpose_consent_governance_drafts_enabled=False
        ),
    )
    return db


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router_module,
        "get_settings",
        lambda: SimpleNamespace(
            purpose_consent_governance_drafts_enabled=True
        ),
    )


def test_get_flag_off_returns_disabled_without_touching_draft_storage(
    db: _DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*_args, **_kwargs):
        raise AssertionError("flag off must not query governance storage")

    monkeypatch.setattr(
        router_module,
        "load_purpose_consent_governance",
        unexpected,
    )

    body = router_module.get_consent_governance(
        str(CHURCH_ID), db=db, admin=ADMIN
    )

    assert body == {
        "enabled": False,
        "initialized": False,
        "schemaVersion": router_module._SCHEMA_VERSION,
        "revision": 0,
        "purposes": [],
    }
    assert db.added == []
    assert db.commits == 0


@pytest.mark.parametrize("method", ["post", "put"])
def test_mutations_fail_before_storage_when_flag_off(
    db: _DB,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    def unexpected(*_args, **_kwargs):
        raise AssertionError("flag off must not call mutation service")

    monkeypatch.setattr(
        router_module,
        "initialize_purpose_consent_governance",
        unexpected,
    )
    monkeypatch.setattr(
        router_module,
        "update_purpose_consent_governance_draft",
        unexpected,
    )
    with pytest.raises(HTTPException) as caught:
        if method == "post":
            router_module.initialize_consent_governance(
                str(CHURCH_ID), db=db, admin=ADMIN
            )
        else:
            router_module.update_consent_governance_purpose(
                str(CHURCH_ID),
                PurposeConsentPurpose.COMUNICADOS,
                router_module.AdminConsentGovernanceUpdateRequest.model_validate(
                    {"expectedRevision": 1, "decisionPayload": {}}
                ),
                db=db,
                admin=ADMIN,
            )

    assert caught.value.status_code == 503
    assert db.added == []
    assert db.commits == 0


def test_initialize_binds_authenticated_actor_and_audits_metadata_only(
    db: _DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    captured: dict[str, object] = {}

    def initialize(_db, **kwargs):
        captured.update(kwargs)
        return _snapshot()

    monkeypatch.setattr(
        router_module,
        "initialize_purpose_consent_governance",
        initialize,
    )

    body = router_module.initialize_consent_governance(
        str(CHURCH_ID), db=db, admin=ADMIN
    )

    assert captured == {
        "igreja_id": CHURCH_ID,
        "actor_app_user_id": ACTOR_ID,
    }
    assert body["enabled"] is True
    assert len(body["purposes"]) == 4
    assert {item["purposeStatus"] for item in body["purposes"]} == {
        "DRAFT_NOT_APPROVED"
    }
    assert all(item["controllerApproved"] is False for item in body["purposes"])
    assert all(item["humanPacketComplete"] is False for item in body["purposes"])
    assert all(item["catalogReady"] is False for item in body["purposes"])
    assert all(item["writerEligible"] is False for item in body["purposes"])
    audit = next(item for item in db.added if isinstance(item, PlatformAuditLog))
    assert audit.actor_id == ACTOR_ID
    assert audit.actor_email is None
    assert audit.detalhe == {"revision": 1, "purposeCount": 4}
    assert "decision" not in str(audit.detalhe).lower()
    assert db.commits == 1


def test_update_rejects_mass_assignment_before_service(
    db: _DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("invalid body must fail before service")

    monkeypatch.setattr(
        router_module,
        "update_purpose_consent_governance_draft",
        unexpected,
    )

    with pytest.raises(ValidationError):
        router_module.AdminConsentGovernanceUpdateRequest.model_validate(
            {
                "expectedRevision": 1,
                "decisionPayload": {"openQuestions": "pendente"},
                "controllerApproved": True,
                "actorId": str(uuid.uuid4()),
                "igrejaId": str(uuid.uuid4()),
            }
        )
    assert db.added == []
    assert db.commits == 0


@pytest.mark.parametrize("invalid_revision", [True, "1", 1.0])
def test_update_rejects_coerced_revision_before_service(
    db: _DB,
    monkeypatch: pytest.MonkeyPatch,
    invalid_revision: object,
) -> None:
    _enable(monkeypatch)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("invalid revision must fail before service")

    monkeypatch.setattr(
        router_module,
        "update_purpose_consent_governance_draft",
        unexpected,
    )

    with pytest.raises(ValidationError):
        router_module.AdminConsentGovernanceUpdateRequest.model_validate(
            {
                "expectedRevision": invalid_revision,
                "decisionPayload": {},
            }
        )

    assert db.added == []
    assert db.commits == 0


def test_update_uses_purpose_revision_and_never_audits_content(
    db: _DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    captured: dict[str, object] = {}

    def update(_db, **kwargs):
        captured.update(kwargs)
        return _snapshot(revision=2)

    monkeypatch.setattr(
        router_module,
        "update_purpose_consent_governance_draft",
        update,
    )

    body = router_module.update_consent_governance_purpose(
        str(CHURCH_ID),
        PurposeConsentPurpose.COMUNICADOS,
        router_module.AdminConsentGovernanceUpdateRequest.model_validate(
            {
                "expectedRevision": 1,
                "decisionPayload": {
                    "operationalNeed": "Fluxo operacional em validação",
                    "openQuestions": None,
                },
            }
        ),
        db=db,
        admin=ADMIN,
    )

    assert body["enabled"] is True
    assert captured["igreja_id"] == CHURCH_ID
    assert captured["actor_app_user_id"] == ACTOR_ID
    assert captured["purpose"] is PurposeConsentPurpose.COMUNICADOS
    assert captured["expected_revision"] == 1
    audit = next(item for item in db.added if isinstance(item, PlatformAuditLog))
    assert audit.actor_email is None
    assert audit.detalhe == {
        "purpose": "comunicados",
        "revision": 2,
        "changedSections": ["openQuestions", "operationalNeed"],
    }
    assert "Fluxo operacional" not in str(audit.detalhe)
    assert db.commits == 1


def test_stale_revision_is_409_without_commit(
    db: _DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)

    def conflict(*_args, **_kwargs):
        raise PurposeConsentGovernanceRevisionConflictError("stale")

    monkeypatch.setattr(
        router_module,
        "update_purpose_consent_governance_draft",
        conflict,
    )

    with pytest.raises(HTTPException) as caught:
        router_module.update_consent_governance_purpose(
            str(CHURCH_ID),
            PurposeConsentPurpose.COMUNICADOS,
            router_module.AdminConsentGovernanceUpdateRequest.model_validate(
                {"expectedRevision": 1, "decisionPayload": {}}
            ),
            db=db,
            admin=ADMIN,
        )

    assert caught.value.status_code == 409
    assert db.added == []
    assert db.commits == 0

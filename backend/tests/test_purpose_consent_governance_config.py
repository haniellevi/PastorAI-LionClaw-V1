"""Rollout gate for the D2B2b3A Master draft workspace."""

from app.config import Settings


def test_purpose_consent_governance_drafts_default_off() -> None:
    settings = Settings(_env_file=None)

    assert settings.purpose_consent_governance_drafts_enabled is False


def test_purpose_consent_governance_drafts_requires_explicit_opt_in() -> None:
    settings = Settings(
        _env_file=None,
        purpose_consent_governance_drafts_enabled=True,
    )

    assert settings.purpose_consent_governance_drafts_enabled is True

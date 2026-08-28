"""Rollout gate for the D2B2b3A Master draft workspace."""

from pathlib import Path

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


def test_purpose_consent_governance_drafts_is_off_in_all_env_templates() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    expected = "PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED=false"

    for relative_path in (
        "backend/.env.example",
        "backend/.env.staging.example",
        "deploy/.env.example",
    ):
        lines = (repository_root / relative_path).read_text(encoding="utf-8").splitlines()
        assert lines.count(expected) == 1, relative_path

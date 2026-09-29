"""Offline guards for V3 consolidation WhatsApp activation and templates."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID


_IGREJA = UUID("00000000-0000-0000-0000-0000000000a1")


def test_consolidation_notification_gate_is_typed_and_off_by_default() -> None:
    from app.config import Settings

    assert Settings().consolidation_notify_enabled is False


def test_consolidation_s3_gate_requires_release_privilege_and_exact_allowlist(
    monkeypatch,
) -> None:
    from app.services import consolidation_whatsapp as service

    monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setattr(service, "privilege_enabled_from_environment", lambda _id: True)
    monkeypatch.setattr(service, "CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID", None)

    assert not service.consolidation_enabled_from_environment(_IGREJA)

    monkeypatch.setattr(
        service, "CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID", "v3-reviewed"
    )
    assert service.consolidation_enabled_from_environment(_IGREJA)

    monkeypatch.setenv(
        "CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", f"{_IGREJA},{_IGREJA}"
    )
    assert not service.consolidation_enabled_from_environment(_IGREJA)
    monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", "not-a-uuid")
    assert not service.consolidation_enabled_from_environment(_IGREJA)


def test_consolidation_transport_gate_is_cumulative(monkeypatch) -> None:
    from app.services import consolidation_whatsapp as service

    settings = SimpleNamespace(
        consolidation_notify_enabled=True,
        allow_real_sends=True,
        whatsapp_piloto=lambda igreja_id: igreja_id == _IGREJA,
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(service, "consolidation_enabled_from_environment", lambda _id: True)

    assert service.consolidation_delivery_enabled(_IGREJA)
    settings.allow_real_sends = False
    assert not service.consolidation_delivery_enabled(_IGREJA)
    settings.allow_real_sends = True
    settings.consolidation_notify_enabled = False
    assert not service.consolidation_delivery_enabled(_IGREJA)


def test_panel_link_is_fixed_authenticated_fragment_without_user_data() -> None:
    from app.services.consolidation_whatsapp import consolidation_panel_link

    assert (
        consolidation_panel_link("https://app.igreja12.example/")
        == "https://app.igreja12.example/#consolidar"
    )
    for invalid in (
        "",
        "app.igreja12.example",
        "https://app.igreja12.example/other",
        "https://app.igreja12.example/?pessoa=123",
        "https://user:pass@app.igreja12.example/",
        "https://app.igreja12.example/#outro",
        "https://[",
        "https://app.igreja12.example:bad/",
    ):
        assert consolidation_panel_link(invalid) is None


def test_first_name_template_projection_rejects_phone_and_keeps_only_first_name() -> None:
    from app.services.consolidation_whatsapp import template_first_name

    assert template_first_name("Maria da Silva") == "Maria"
    assert template_first_name("João-Pedro") == "João-Pedro"
    assert template_first_name("Joa\u0303o da Silva") == "João"
    assert template_first_name("+55 00 00000-0000") is None
    assert template_first_name("Maria\x00") is None


def test_consolidation_responsibility_is_type_scoped_without_opening_coordination() -> None:
    from app.services.consolidation_whatsapp import (
        consolidation_coordination_allowed,
        consolidation_responsible_task_types,
        consolidation_task_resolver_roles,
    )

    assert not consolidation_coordination_allowed(frozenset({"lider_celula"}))
    assert consolidation_responsible_task_types(frozenset({"lider_celula"})) == {
        "fonovisita"
    }
    assert consolidation_responsible_task_types(frozenset({"lider_g12"})) == {
        "conectar_celula",
        "fonovisita",
    }
    assert "lider_celula" not in consolidation_task_resolver_roles(
        "conectar_celula"
    )
    assert "lider_celula" in consolidation_task_resolver_roles("fonovisita")
    assert consolidation_coordination_allowed(frozenset({"lider_consol"}))

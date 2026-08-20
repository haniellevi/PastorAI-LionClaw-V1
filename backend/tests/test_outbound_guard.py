"""Testes do guard de envios não-produção (B2).

Garante que, fora de produção e sem override, os métodos de efeito externo
(WhatsApp, cobrança, e-mail, LLM, calendário) NÃO tocam a rede — retornam um
valor neutro e logam ``[OUTBOUND_DISABLED]`` sem expor segredo. Qualquer ambiente
só toca a rede com ``ALLOW_REAL_SENDS=true``.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.services.asaas import AsaasClient, AsaasError
from app.services.brevo import BrevoClient, BrevoError
from app.services.evolution import EvolutionClient, EvolutionError
from app.services.google_calendar import GoogleCalendarClient, GoogleCalendarError
from app.services.llm import LLMClient
from app.services.outbound_guard import (
    asaas_billing_writes_allowed,
    external_sends_allowed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings(**over) -> Settings:
    """Settings de não-produção COM credenciais — assim, se o guard falhasse, o
    método tentaria a rede e o transport bloqueante (abaixo) acusaria."""
    base = dict(
        app_env="staging",
        evolution_api_url="http://evo:8080",
        evolution_api_key="SECRET_EVO_KEY",
        evolution_webhook_secret="webhook-secret",
        evolution_webhook_callback_url="http://backend:8000/whatsapp/webhook",
        asaas_api_url="https://api.asaas.com/v3",
        asaas_api_key="SECRET_ASAAS_KEY",
        brevo_api_url="https://api.brevo.com/v3",
        brevo_api_key="SECRET_BREVO_KEY",
        brevo_from_email="no-reply@igreja12.com.br",
        google_calendar_api_url="https://www.googleapis.com/calendar/v3",
        google_calendar_access_token="SECRET_GCAL_TOKEN",
    )
    base.update(over)
    return Settings(**base)


def _block_network(monkeypatch) -> None:
    """Faz qualquer uso de httpx.Client FALHAR — prova que o guard cortou antes."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"httpx não deveria ser chamado em sandbox: {request.url}")

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)


def _capture_network(monkeypatch, response: httpx.Response) -> list[httpx.Request]:
    """Captura as requests httpx (override permitido) e responde `response`."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)
    return seen


# ---------------------------------------------------------------------------
# 1) A trava dupla (config / helper)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "app_env,allow,expected",
    [
        ("production", False, False),  # prod também exige ativação explícita
        ("production", True, True),
        ("staging", False, False),     # não-prod bloqueia por padrão
        ("staging", True, True),       # override explícito
        ("development", False, False),
        ("development", True, True),
        ("PRODUCTION", False, False),  # case-insensitive
    ],
)
def test_external_sends_enabled_matrix(app_env, allow, expected) -> None:
    s = Settings(app_env=app_env, allow_real_sends=allow)
    assert s.external_sends_enabled is expected
    assert external_sends_allowed(s) is expected


@pytest.mark.parametrize(
    "allow,billing,expected",
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_asaas_billing_requires_both_gates(allow, billing, expected) -> None:
    settings = Settings(
        allow_real_sends=allow,
        asaas_billing_enabled=billing,
    )

    assert settings.asaas_billing_writes_enabled is expected
    assert asaas_billing_writes_allowed(settings) is expected


def test_default_settings_block_sends() -> None:
    """O default (sem env) é seguro: development + allow_real_sends=False."""
    s = Settings()
    assert s.is_production is False
    assert s.allow_real_sends is False
    assert s.external_sends_enabled is False
    assert s.asaas_billing_enabled is False
    assert s.asaas_billing_writes_enabled is False


# ---------------------------------------------------------------------------
# 2) Bloqueio fora de produção — nenhum método toca a rede
# ---------------------------------------------------------------------------
def test_send_text_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert EvolutionClient(_settings()).send_text("igreja-1", "5511999990000", "oi") is False


def test_send_media_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    ok = EvolutionClient(_settings()).send_media(
        "igreja-1", "5511999990000", mediatype="image", media_base64="Zm9v"
    )
    assert ok is False


def test_set_webhook_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert EvolutionClient(_settings()).set_webhook("igreja-1") is True


def test_connect_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert EvolutionClient(_settings()).connect("igreja-1").status == "offline"


def test_reconnect_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert EvolutionClient(_settings()).reconnect("igreja-1").status == "offline"


def test_disconnect_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert EvolutionClient(_settings()).disconnect("igreja-1").status == "offline"


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.connect("igreja-1"),
        lambda client: client.reconnect("igreja-1"),
        lambda client: client.disconnect("igreja-1"),
        lambda client: client.set_webhook("igreja-1"),
    ],
    ids=["connect", "reconnect", "disconnect", "set-webhook"],
)
def test_evolution_mutations_fail_closed_in_production(
    monkeypatch, operation
) -> None:
    _block_network(monkeypatch)
    client = EvolutionClient(_settings(app_env="production"))

    with pytest.raises(EvolutionError, match="desabilitadas"):
        operation(client)


def test_create_checkout_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    result = AsaasClient(_settings()).create_checkout(
        nome="Igreja Teste", email="t@x.com", plano="ate_100", valor=49.9
    )
    assert result.subscription_id == "sandbox"
    assert result.status == "pendente"
    assert result.invoice_url is None


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.create_checkout(
            nome="Igreja Teste",
            email="t@x.com",
            plano="ate_100",
            valor=49.9,
        ),
        lambda client: client.update_subscription(
            "sub_1", valor=99.9, descricao="PastorAI — plano ate_100"
        ),
        lambda client: client.create_one_time_charge(
            customer_id="cus_1",
            valor=1000.0,
            description="PastorAI — taxa de setup",
            external_reference="op_1",
        ),
        lambda client: client.restore_payment("pay_1"),
    ],
    ids=["checkout", "plan-change", "one-time-charge", "restore-payment"],
)
@pytest.mark.parametrize(
    "allow,billing",
    [(False, False), (False, True), (True, False)],
    ids=["both-off", "global-off", "billing-off"],
)
def test_asaas_mutations_fail_closed_in_production(
    monkeypatch, operation, allow, billing
) -> None:
    _block_network(monkeypatch)
    client = AsaasClient(
        _settings(
            app_env="production",
            allow_real_sends=allow,
            asaas_billing_enabled=billing,
        )
    )

    with pytest.raises(AsaasError, match="desabilitadas"):
        operation(client)


def test_send_invite_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert (
        BrevoClient(_settings()).send_invite(
            to_email="t@x.com", nome="T", activation_link="http://x/a"
        )
        == ""
    )


def test_send_password_reset_blocked(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert (
        BrevoClient(_settings()).send_password_reset(
            to_email="t@x.com", reset_link="http://x/r"
        )
        == ""
    )


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.send_invite(
            to_email="t@x.com", nome="T", activation_link="http://x/a"
        ),
        lambda client: client.send_password_reset(
            to_email="t@x.com", reset_link="http://x/r"
        ),
    ],
    ids=["invite", "password-reset"],
)
def test_brevo_sends_fail_closed_in_production(monkeypatch, operation) -> None:
    _block_network(monkeypatch)
    client = BrevoClient(_settings(app_env="production"))

    with pytest.raises(BrevoError, match="desabilitado"):
        operation(client)


def test_create_event_blocked_raises(monkeypatch) -> None:
    """create_event sinaliza 'não sincronizado' via o erro que o caller já trata."""
    import datetime as dt

    _block_network(monkeypatch)
    with pytest.raises(GoogleCalendarError):
        GoogleCalendarClient(_settings()).create_event(
            titulo="Culto", data=dt.date(2026, 6, 14), hora=None, descricao=None
        )


def test_delete_event_blocked_noop(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert GoogleCalendarClient(_settings()).delete_event("evt-1") is None


def test_llm_complete_blocked(monkeypatch) -> None:
    """complete devolve resposta simulada de custo zero, sem tocar a OpenAI."""
    monkeypatch.setattr("app.services.llm.external_sends_allowed", lambda *a, **k: False)
    # Se o guard falhasse, _build_openai_client tentaria importar/usar a SDK:
    monkeypatch.setattr(
        "app.services.llm._build_openai_client",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("OpenAI não deveria ser usado")),
    )
    result = LLMClient("openai", "sk-secret", "gpt-5.6-luna").complete("sys", "user")
    assert "simulada" in result.texto.lower()
    assert result.usage.custo == 0.0
    assert result.usage.tokens_in == 0 and result.usage.tokens_out == 0


# ---------------------------------------------------------------------------
# 3) O override explícito preserva o comportamento real
# ---------------------------------------------------------------------------
def test_send_text_allowed_with_override(monkeypatch) -> None:
    seen = _capture_network(monkeypatch, httpx.Response(200, json={"key": {"id": "X"}}))
    ok = EvolutionClient(_settings(allow_real_sends=True)).send_text(
        "igreja-1", "5511999990000", "oi"
    )
    assert ok is True
    assert len(seen) == 1 and seen[0].url.path.endswith("/message/sendText/igreja-1")


def test_asaas_mutation_allowed_only_with_both_gates(monkeypatch) -> None:
    seen = _capture_network(
        monkeypatch,
        httpx.Response(
            200,
            json={"id": "sub_1", "value": 299.0, "description": "Plano 200"},
        ),
    )
    result = AsaasClient(
        _settings(allow_real_sends=True, asaas_billing_enabled=True)
    ).update_subscription("sub_1", valor=299.0, descricao="Plano 200")

    assert result is not None and result["id"] == "sub_1"
    assert len(seen) == 1
    assert seen[0].method == "PUT"


def test_asaas_read_is_independent_from_billing_write_gates(monkeypatch) -> None:
    seen = _capture_network(
        monkeypatch,
        httpx.Response(200, json={"id": "sub_1", "status": "ACTIVE"}),
    )
    result = AsaasClient(
        _settings(allow_real_sends=False, asaas_billing_enabled=False)
    ).get_subscription("sub_1")

    assert result is not None and result["status"] == "ACTIVE"
    assert len(seen) == 1
    assert seen[0].method == "GET"


def test_send_text_blocked_in_production_without_activation(monkeypatch) -> None:
    _block_network(monkeypatch)
    assert EvolutionClient(_settings(app_env="production")).send_text(
        "igreja-1", "5599", "oi"
    ) is False


def test_send_text_allowed_in_production_with_activation(monkeypatch) -> None:
    seen = _capture_network(monkeypatch, httpx.Response(200, json={}))
    EvolutionClient(_settings(app_env="production", allow_real_sends=True)).send_text(
        "igreja-1", "5599", "oi"
    )
    assert len(seen) == 1


def test_create_event_allowed_with_override(monkeypatch) -> None:
    import datetime as dt

    seen = _capture_network(monkeypatch, httpx.Response(200, json={"id": "g-evt-1"}))
    eid = GoogleCalendarClient(_settings(allow_real_sends=True)).create_event(
        titulo="Culto", data=dt.date(2026, 6, 14), hora=None, descricao=None
    )
    assert eid == "g-evt-1" and len(seen) == 1


# ---------------------------------------------------------------------------
# 4) O log [SANDBOX] não expõe segredo nem PII
# ---------------------------------------------------------------------------
def test_sandbox_log_has_no_secret_or_pii(monkeypatch, caplog) -> None:
    _block_network(monkeypatch)
    with caplog.at_level("INFO", logger="pastorai.outbound"):
        EvolutionClient(_settings()).send_text("igreja-1", "5511999990000", "texto secreto")
        BrevoClient(_settings()).send_invite(
            to_email="alguem@real.com", nome="N", activation_link="http://x/a"
        )
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "[OUTBOUND_DISABLED]" in blob
    assert "send_text" in blob
    # nem telefone, nem e-mail, nem chaves de API vazam para o log:
    for leak in ("5511999990000", "texto secreto", "alguem@real.com",
                 "SECRET_EVO_KEY", "SECRET_BREVO_KEY"):
        assert leak not in blob


# ---------------------------------------------------------------------------
# 5) Cobertura — todo método send/mutate respeita o guard (nada vai à rede)
# ---------------------------------------------------------------------------
def test_meta_all_guarded_methods_block_network(monkeypatch) -> None:
    import datetime as dt

    _block_network(monkeypatch)
    s = _settings()
    evo, asa, bre, gcal = (
        EvolutionClient(s), AsaasClient(s), BrevoClient(s), GoogleCalendarClient(s)
    )
    monkeypatch.setattr("app.services.llm.external_sends_allowed", lambda *a, **k: False)

    # cada um chama um método guardado; nenhum pode tocar a rede (AssertionError)
    calls = [
        lambda: evo.send_text("i", "5599", "x"),
        lambda: evo.send_media("i", "5599", mediatype="image", media_base64="Zm9v"),
        lambda: evo.set_webhook("i"),
        lambda: evo.connect("i"),
        lambda: evo.reconnect("i"),
        lambda: evo.disconnect("i"),
        lambda: asa.create_checkout(nome="n", email="e@x.com", plano="ate_100", valor=1.0),
        lambda: bre.send_invite(to_email="e@x.com", nome="n", activation_link="l"),
        lambda: bre.send_password_reset(to_email="e@x.com", reset_link="l"),
        lambda: LLMClient("openai", "k", "gpt-5.6-luna").complete("s", "u"),
        lambda: gcal.delete_event("evt"),
    ]
    for call in calls:
        call()  # não deve levantar AssertionError do transport bloqueante

    # create_event sinaliza via GoogleCalendarError (também sem tocar a rede)
    with pytest.raises(GoogleCalendarError):
        gcal.create_event(titulo="t", data=dt.date(2026, 6, 14), hora=None, descricao=None)

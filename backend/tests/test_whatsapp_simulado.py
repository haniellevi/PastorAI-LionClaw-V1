"""Modo ``WHATSAPP_TRANSPORTE=simulado`` e o simulador de Evolution.

Provam que o simulador libera o fluxo do WhatsApp sem abrir destino real: só o
host do simulador é alcançado, ``ALLOW_REAL_SENDS`` continua desligado para
LLM/agenda/cobrança, produção recusa o modo e o webhook simulado passa pela
autenticação real do backend.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.domain.conversations import parse_message_event
from app.domain.phone import normalize_phone
from app.routers import whatsapp as whatsapp_router
from app.services.evolution import EvolutionClient
from app.services.outbound_guard import external_sends_allowed
from devtools.simulador_whatsapp import NUMERO_OFICIAL_PADRAO, create_app

SIMULADOR = "http://simulador-whatsapp:8090"
SEGREDO = "segredo-webhook-teste"
CONTATO = normalize_phone("5500988887777")


def _settings(**over) -> Settings:
    base = dict(
        app_env="development",
        allow_real_sends=False,
        whatsapp_transporte="simulado",
        evolution_simulador_url=SIMULADOR,
        # Valores "reais" presentes de propósito: o modo simulado não pode usá-los.
        evolution_api_url="https://evolution.exemplo.com.br",
        evolution_api_key="chave-real-nao-usar",
        evolution_webhook_secret=SEGREDO,
    )
    base.update(over)
    return Settings(**base)


def _simulador(webhook_client=None) -> FastAPI:
    return create_app(
        webhook_url="http://backend:8000/whatsapp/webhook",
        webhook_secret=SEGREDO,
        webhook_client=webhook_client,
    )


def _cliente_no_simulador(settings: Settings, sim: FastAPI) -> EvolutionClient:
    """EvolutionClient cujo pool HTTP é o próprio app do simulador."""
    client = EvolutionClient(settings)
    base_url, _ = client._require_config()
    client._client = TestClient(sim, base_url=base_url)
    return client


# ---- Configuração ---------------------------------------------------------


def test_transporte_padrao_e_real() -> None:
    settings = Settings()
    assert settings.whatsapp_transporte == "real"
    assert settings.whatsapp_simulado is False


def test_transporte_desconhecido_e_recusado() -> None:
    with pytest.raises(ValidationError, match="WHATSAPP_TRANSPORTE"):
        _settings(whatsapp_transporte="fake")


def test_producao_recusa_simulador() -> None:
    with pytest.raises(ValidationError, match="proibido em produção"):
        _settings(app_env="production")


@pytest.mark.parametrize("modo", ["canary", "live", "LIVE"])
def test_simulado_exige_brevo_desligado(modo: str) -> None:
    with pytest.raises(ValidationError, match="BREVO_SEND_MODE=off"):
        _settings(brevo_send_mode=modo)


def test_simulado_exige_cobranca_asaas_desligada() -> None:
    with pytest.raises(ValidationError, match="ASAAS_BILLING_ENABLED=false"):
        _settings(asaas_billing_enabled=True)


def test_configuracao_sintetica_padrao_mantem_todos_os_gates_fechados() -> None:
    settings = _settings()
    assert settings.brevo_send_mode == "off"
    assert settings.asaas_billing_enabled is False
    assert settings.external_sends_enabled is False
    assert settings.asaas_billing_writes_enabled is False


# Destinos que o resolvedor do sistema ou um parser frouxo trataria como interno.
# `0x7f000001` e `2130706433` viram 127.0.0.1; `167772161` vira 10.0.0.1.
DESTINOS_RECUSADOS = [
    "https://evolution.exemplo.com.br",
    "http://10.0.0.5:8080",
    "http://192.168.0.10:8090",
    "http://[::ffff:10.0.0.1]:8090",
    "ftp://localhost:8090",
    "",
    "http://127.example.invalid:8090",
    "http://0x7f000001:8090",
    "http://2130706433:8090",
    "http://167772161:8090",
    "http://localhost.:8090",
    "http://outro-servico:8090",
    "http://usuario:senha@localhost:8090",
    "http://localhost:99999",
    "http://localhost:0",
]


@pytest.mark.parametrize("url", [*DESTINOS_RECUSADOS, "http://backend:8000"])
def test_backend_so_alcanca_a_evolution_falsa(url: str) -> None:
    with pytest.raises(ValidationError, match="EVOLUTION_SIMULADOR_URL"):
        _settings(evolution_simulador_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8090",
        "http://127.1.2.3:8090",
        "http://[::1]:8090",
        "http://localhost:8090",
        "http://LOCALHOST:8090",
        SIMULADOR,
    ],
)
def test_backend_aceita_loopback_e_nome_da_lista(url: str) -> None:
    assert _settings(evolution_simulador_url=url).whatsapp_simulado is True


@pytest.mark.parametrize(
    "url", [*DESTINOS_RECUSADOS, "http://simulador-whatsapp:8090/whatsapp/webhook"]
)
def test_simulador_so_alcanca_o_backend_local(url: str) -> None:
    with pytest.raises(ValueError, match="SIMULADOR_WEBHOOK_URL"):
        create_app(webhook_url=url, webhook_secret=SEGREDO)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/whatsapp/webhook",
        "http://[::1]:8000/whatsapp/webhook",
        "http://localhost:8000/whatsapp/webhook",
        "http://backend:8000/whatsapp/webhook",
    ],
)
def test_simulador_aceita_loopback_e_nome_da_lista(url: str) -> None:
    create_app(webhook_url=url, webhook_secret=SEGREDO)


def test_simulado_nao_libera_outros_provedores() -> None:
    settings = _settings()
    # LLM, Google Calendar e Asaas usam este gate: continua fechado.
    assert settings.external_sends_enabled is False
    assert external_sends_allowed(settings) is False
    assert settings.asaas_billing_writes_enabled is False


def test_simulado_nunca_usa_url_nem_chave_reais() -> None:
    base_url, api_key = EvolutionClient(_settings())._require_config()
    assert base_url == SIMULADOR
    assert api_key != "chave-real-nao-usar"


def test_transporte_real_sem_allow_real_sends_continua_suprimido() -> None:
    client = EvolutionClient(_settings(whatsapp_transporte="real"))
    result = client.send_agent_text("igreja-dev", "5500988887777", "oi")
    assert result.status == "suprimido"


# ---- Contrato EvolutionClient ↔ simulador ---------------------------------


def test_fetch_status_online_com_numero_oficial() -> None:
    client = _cliente_no_simulador(_settings(), _simulador())
    status = client.fetch_status("igreja-dev")
    assert status.status == "online"
    assert status.numero == NUMERO_OFICIAL_PADRAO


def test_resposta_do_agente_chega_ao_simulador() -> None:
    sim = _simulador()
    client = _cliente_no_simulador(_settings(), sim)

    result = client.send_agent_text("igreja-dev", "5500988887777", "Olá do bot")

    assert result.status == "aceito"
    [msg] = sim.state.simulador.mensagens
    assert (msg.direcao, msg.instance, msg.telefone, msg.texto) == (
        "saida",
        "igreja-dev",
        CONTATO,
        "Olá do bot",
    )


def test_send_text_e_operacoes_de_conexao() -> None:
    sim = _simulador()
    client = _cliente_no_simulador(_settings(), sim)

    assert client.send_text("igreja-dev", "5500988887777", "aviso") is True
    assert client.connect("igreja-dev").status == "online"
    assert client.disconnect("igreja-dev").status == "offline"
    assert client.fetch_status("igreja-dev").status == "offline"
    assert client.delete_instance("igreja-dev") is True
    assert client.fetch_profile_picture_url("igreja-dev", "5500988887777") is None


def test_falha_programada_vira_retentavel() -> None:
    sim = _simulador()
    client = _cliente_no_simulador(_settings(), sim)
    TestClient(sim).post("/simulador/falhas", json={"send_text": [503]})

    result = client.send_agent_text("igreja-dev", "5500988887777", "oi")

    assert result.status == "falhou_retentavel"
    assert sim.state.simulador.mensagens == []


def test_instancia_desconectada_nao_recebe_envio() -> None:
    sim = _simulador()
    client = _cliente_no_simulador(_settings(), sim)
    client.disconnect("igreja-dev")

    result = client.send_agent_text("igreja-dev", "5500988887777", "oi")

    assert result.status == "falhou_retentavel"
    assert result.error_class == "instancia_desconectada"


def test_excluir_instancia_a_mantem_fora_ate_recriar() -> None:
    sim = _simulador()
    http = TestClient(sim)
    client = _cliente_no_simulador(_settings(), sim)

    assert client.delete_instance("igreja-dev") is True

    # Ausência não volta a significar "open".
    assert client.fetch_status("igreja-dev").status == "offline"
    assert http.get("/instance/connect/igreja-dev").status_code == 404
    assert http.put("/instance/restart/igreja-dev").status_code == 404
    envio = client.send_agent_text("igreja-dev", "5500988887777", "oi")
    assert envio.error_class == "instancia_desconectada"
    assert sim.state.simulador.mensagens == []

    assert http.post("/instance/create", json={"instanceName": "igreja-dev"}).status_code == 201
    assert client.fetch_status("igreja-dev").status == "online"
    assert client.send_text("igreja-dev", "5500988887777", "de volta") is True


@pytest.mark.parametrize("derrubar", ["logout", "delete"])
def test_midia_e_entrada_respeitam_instancia_desconectada(derrubar: str) -> None:
    sim = _simulador()
    http = TestClient(sim)
    http.delete(f"/instance/{derrubar}/igreja-dev")

    midia = http.post(
        "/message/sendMedia/igreja-dev",
        json={"number": "5500988887777", "mediatype": "image", "caption": "foto"},
    )
    entrada = http.post(
        "/simulador/mensagens",
        json={"instance": "igreja-dev", "telefone": "5500988887777", "texto": "oi"},
    )

    assert midia.status_code == 400
    assert entrada.status_code == 409
    assert sim.state.simulador.mensagens == []


# ---- Webhook simulado passa pela autenticação real do backend -------------


class _FilaMemoria:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def enqueue(self, payload: dict) -> None:
        self.payloads.append(payload)


@pytest.fixture
def backend_webhook(monkeypatch):
    monkeypatch.setenv("EVOLUTION_WEBHOOK_SECRET", SEGREDO)
    get_settings.cache_clear()
    fila = _FilaMemoria()
    app = FastAPI()
    app.include_router(whatsapp_router.router)
    app.dependency_overrides[whatsapp_router.get_webhook_queue] = lambda: fila
    try:
        yield TestClient(app, base_url="http://backend:8000"), fila
    finally:
        get_settings.cache_clear()


def test_mensagem_do_contato_vira_webhook_autenticado(backend_webhook) -> None:
    backend, fila = backend_webhook
    sim = _simulador(webhook_client=backend)

    resposta = TestClient(sim).post(
        "/simulador/mensagens",
        json={"instance": "igreja-dev", "telefone": "5500988887777", "texto": "oi"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["webhook_status"] == 202
    [payload] = fila.payloads
    parsed = parse_message_event(payload)
    assert parsed is not None
    assert (parsed.instance, parsed.telefone, parsed.texto, parsed.from_me) == (
        "igreja-dev",
        CONTATO,
        "oi",
        False,
    )
    assert payload["data"]["key"]["remoteJid"] == "5500988887777@s.whatsapp.net"
    assert parsed.owner == normalize_phone(NUMERO_OFICIAL_PADRAO)


def test_segredo_errado_e_recusado_pelo_backend(backend_webhook) -> None:
    backend, fila = backend_webhook
    sim = create_app(
        webhook_url="http://backend:8000/whatsapp/webhook",
        webhook_secret="outro-segredo",
        webhook_client=backend,
    )

    resposta = TestClient(sim).post(
        "/simulador/mensagens",
        json={"instance": "igreja-dev", "telefone": "5500988887777", "texto": "oi"},
    )

    assert resposta.json()["webhook_status"] == 401
    assert fila.payloads == []


def test_simulador_recusa_webhook_publico() -> None:
    with pytest.raises(ValueError, match="SIMULADOR_WEBHOOK_URL"):
        create_app(webhook_url="https://api.igreja12.com.br/whatsapp/webhook", webhook_secret=SEGREDO)


def test_conversa_lista_entrada_e_saida_do_mesmo_contato(backend_webhook) -> None:
    backend, _fila = backend_webhook
    sim = _simulador(webhook_client=backend)
    client = _cliente_no_simulador(_settings(), sim)
    ui = TestClient(sim)

    ui.post(
        "/simulador/mensagens",
        json={"instance": "igreja-dev", "telefone": "5500988887777", "texto": "oi"},
    )
    client.send_agent_text("igreja-dev", "5500988887777", "resposta")
    client.send_agent_text("igreja-dev", "5500900001111", "outro contato")

    conversa = ui.get(
        "/simulador/mensagens", params={"instance": "igreja-dev", "telefone": "5500988887777"}
    ).json()
    assert [(m["direcao"], m["texto"]) for m in conversa] == [
        ("entrada", "oi"),
        ("saida", "resposta"),
    ]
    assert "Simulador de WhatsApp" in ui.get("/").text

"""B7: primeiro consentimento em vários turnos, com migrations reais.

O que prova: contato fictício novo → webhook do simulador → ``QueueWorker``
(inbound persistido, trigger de inbound) → ``run_agent_for_message`` (runtime,
grafo, roteador e ``consent_node`` reais) → termo; "Aceito" grava
``ConsentRecord`` da versão atual, visível a uma conexão observadora com RLS
depois do commit; o turno seguinte segue para o onboarding sem repetir o termo.

O trigger de inbound só concede a permissão básica (``pessoas.consentimento``)
e não grava aceite do termo: isso é intencional, não defeito.

O que NÃO prova: Redis (fila em memória, sem claim/ack/lease), Evolution real,
LLM (bloqueado por ``ALLOW_REAL_SENDS=false``) nem envio a número real.
"""

from __future__ import annotations

import datetime as dt
import uuid
from functools import partial

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select, text
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.db.models import (
    AgentConfig,
    AgentConversationLog,
    ConsentRecord,
    Igreja,
    LlmCredential,
    Message,
    Pessoa,
    WhatsappConnection,
)
from app.db.tenant_session import mark_tenant_scoped
from app.domain import consent as consent_rules
from app.routers import whatsapp as whatsapp_router
from app.services import crypto
from app.services.evolution import EvolutionClient
from app.workers import queue_worker as worker_module
from app.workers.queue_worker import (
    IngestionResult,
    QueueWorker,
    WebhookQueue,
    _Envelope,
    run_agent_for_message,
)
from devtools.simulador_whatsapp import create_app
from tests.test_whatsapp_integrated_pg import migrated_factory, rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

_REAL_PILOTO = Settings.whatsapp_piloto
_REAL_REPLY_ENABLED = worker_module._whatsapp_reply_enabled

_SIMULADOR = "http://simulador-whatsapp:8090"
_SEGREDO = "segredo-webhook-b7-sintetico"
_INSTANCE = "igreja-b7"
_IGREJA = uuid.UUID("b7b7b7b7-0000-0000-0000-0000000000b7")
_IGREJA_NOME = "Igreja Sintética B7"
_TELEFONE = "5500977776666"
_TERMO_ATUAL = "v-b7-sintetica-2"
_TERMO_ANTIGO = "v-b7-sintetica-1"
# Onboarding é a única rota refinada pelo LLM; com ALLOW_REAL_SENDS=false o
# cliente LLM devolve este texto fixo sem chamar provedor.
_ONBOARDING_LLM_SIMULADO = "[Resposta simulada — envios externos desativados neste ambiente.]"


class _RedisSemMemoria:
    """Marca de idempotência sempre nova: o banco é quem deduplica aqui."""

    def set(self, key, value, nx=False, ex=None) -> bool:
        return True

    def delete(self, key) -> None:
        pass

    def eval(self, script, numkeys, *args) -> int:
        return 1


class _FilaMemoria:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def enqueue(self, payload: dict) -> None:
        self.payloads.append(payload)


@pytest.fixture
def b7(migrated_factory, monkeypatch):  # noqa: F811
    monkeypatch.setattr(Settings, "whatsapp_piloto", _REAL_PILOTO)
    monkeypatch.setattr(worker_module, "_whatsapp_reply_enabled", _REAL_REPLY_ENABLED)
    for key, value in {
        "APP_ENV": "development",
        "ALLOW_REAL_SENDS": "false",
        "WHATSAPP_TRANSPORTE": "simulado",
        "EVOLUTION_SIMULADOR_URL": _SIMULADOR,
        "EVOLUTION_WEBHOOK_SECRET": _SEGREDO,
        "WHATSAPP_PILOTO_IGREJA_IDS": str(_IGREJA),
        "AGENT_TERM_VERSION": _TERMO_ATUAL,
        "SECRETS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }.items():
        monkeypatch.setenv(key, value)
    for name in (
        "JEV_ENABLED_IGREJA_IDS",
        "JEV_SHADOW_TRIAGE_IGREJA_IDS",
        "AGENT_PRIVILEGE_ENABLED_IGREJA_IDS",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    crypto._get_fernet.cache_clear()
    factory = migrated_factory
    with factory.begin() as session:
        session.add(Igreja(id=_IGREJA, nome=_IGREJA_NOME))
        session.flush()
        session.add_all(
            [
                WhatsappConnection(igreja_id=_IGREJA, instance=_INSTANCE),
                AgentConfig(igreja_id=_IGREJA, comportamento="perfil sintético", ativo=True),
                LlmCredential(
                    igreja_id=_IGREJA,
                    provedor="openai",
                    modelo="gpt-5.6-luna",
                    api_key_encrypted=crypto.encrypt_secret("synthetic-no-provider"),
                    validado=True,
                    ativo=True,
                ),
            ]
        )
    fila = _FilaMemoria()
    backend = FastAPI()
    backend.include_router(whatsapp_router.router)
    backend.dependency_overrides[whatsapp_router.get_webhook_queue] = lambda: fila
    simulador = create_app(
        webhook_url="http://backend:8000/whatsapp/webhook",
        webhook_secret=_SEGREDO,
        webhook_client=TestClient(backend, base_url="http://backend:8000"),
    )
    ui = TestClient(simulador)
    evolution = EvolutionClient(get_settings())
    evolution._client = TestClient(simulador, base_url=_SIMULADOR)
    # Nenhum tráfego de provedor pode escapar dos clientes ASGI locais.
    http_send = httpx.Client.send

    def local_http(client, *args, **kwargs):
        if not isinstance(client, TestClient):
            raise AssertionError("HTTP externo inesperado no teste B7")
        return http_send(client, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", local_http)
    worker = QueueWorker(
        queue=WebhookQueue(redis_client=_RedisSemMemoria()),
        session_factory=factory,
        agent_runner=partial(run_agent_for_message, evolution_client=evolution),
    )

    class Turnos:
        def envia(self, texto: str) -> None:
            resposta = ui.post(
                "/simulador/mensagens",
                json={"instance": _INSTANCE, "telefone": _TELEFONE, "texto": texto},
            )
            assert resposta.json()["webhook_status"] == 202
            result = worker.handle_envelope(_Envelope(payload=fila.payloads.pop(0)))
            assert result is IngestionResult.REGISTERED

        def respostas(self) -> list[str]:
            conversa = ui.get(
                "/simulador/mensagens",
                params={"instance": _INSTANCE, "telefone": _TELEFONE},
            ).json()
            return [m["texto"] for m in conversa if m["direcao"] == "saida"]

        def observa(self, model):
            """Conexão nova, sob RLS: só enxerga o que já foi commitado."""
            with factory() as session:
                mark_tenant_scoped(session, _IGREJA, source="b7-observer")
                role = session.execute(text("SELECT current_user")).scalar_one()
                assert role == "authenticated"
                return session.scalars(select(model)).all()

        def eventos(self) -> list[str]:
            rows = sorted(self.observa(AgentConversationLog), key=lambda r: (r.created_at, r.id))
            return [r.evento for r in rows if r.evento in _EVENTOS_DE_ROTA]

        def inbox(self) -> list[tuple[str, str]]:
            rows = sorted(self.observa(Message), key=lambda m: (m.criado_em, m.id))
            return [(m.direcao, m.texto) for m in rows if m.texto is not None]

    turnos = Turnos()
    turnos.factory = factory
    try:
        yield turnos
    finally:
        ui.close()
        get_settings.cache_clear()
        crypto._get_fernet.cache_clear()


_EVENTOS_DE_ROTA = {"consent_presented", "consent_accepted", "onboarding", "optout"}


def _termo() -> str:
    return consent_rules.term_text(_TERMO_ATUAL, _IGREJA_NOME)


def test_contato_novo_aceita_termo_e_proximo_turno_segue_onboarding(b7):
    b7.envia("oi")
    assert b7.respostas() == [_termo()]
    assert b7.observa(ConsentRecord) == []
    # O trigger de inbound concede só a permissão básica (nome/telefone).
    [pessoa] = b7.observa(Pessoa)
    assert pessoa.consentimento is True and pessoa.optout is False

    b7.envia("Aceito")
    [registro] = b7.observa(ConsentRecord)
    assert (registro.pessoa_id, registro.termo_versao) == (pessoa.id, _TERMO_ATUAL)
    assert registro.aceite_em is not None and registro.ator_id is None
    assert b7.respostas()[-1] == (
        "Obrigado! Seu consentimento foi registrado. Como posso te ajudar hoje?"
    )

    b7.envia("quero conhecer a igreja")
    respostas = b7.respostas()
    assert respostas[-1] == _ONBOARDING_LLM_SIMULADO
    assert respostas.count(_termo()) == 1
    assert b7.eventos() == ["consent_presented", "consent_accepted", "onboarding"]
    assert len(b7.observa(ConsentRecord)) == 1
    assert [d for d, _ in b7.inbox()] == ["in", "out"] * 3


def test_recusa_nao_grava_aceite_e_optout_bloqueia_aceite_posterior(b7):
    b7.envia("oi")
    b7.envia("não")
    assert b7.respostas() == [_termo(), _termo()]
    assert b7.observa(ConsentRecord) == []

    b7.envia("SAIR")
    b7.envia("Aceito")
    [pessoa] = b7.observa(Pessoa)
    assert pessoa.optout is True
    assert [r.termo_versao for r in b7.observa(ConsentRecord)] == [f"optout:{_TERMO_ATUAL}"]
    assert b7.respostas() == [_termo(), _termo()]
    assert "consent_accepted" not in b7.eventos()


def test_aceite_de_versao_antiga_exige_novo_aceite_da_versao_atual(b7):
    b7.envia("oi")
    [pessoa] = b7.observa(Pessoa)
    assert b7.observa(ConsentRecord) == []
    with b7.factory.begin() as session:
        session.add(
            ConsentRecord(
                igreja_id=_IGREJA,
                pessoa_id=pessoa.id,
                termo_versao=_TERMO_ANTIGO,
                aceite_em=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
            )
        )

    b7.envia("quero conhecer a igreja")
    assert b7.respostas() == [_termo(), _termo()]

    b7.envia("Aceito")
    versoes = sorted(r.termo_versao for r in b7.observa(ConsentRecord))
    assert versoes == [_TERMO_ANTIGO, _TERMO_ATUAL]

    b7.envia("quero conhecer a igreja")
    assert b7.respostas()[-1] == _ONBOARDING_LLM_SIMULADO
    assert b7.respostas().count(_termo()) == 2
    assert b7.eventos() == [
        "consent_presented", "consent_presented", "consent_accepted", "onboarding",
    ]

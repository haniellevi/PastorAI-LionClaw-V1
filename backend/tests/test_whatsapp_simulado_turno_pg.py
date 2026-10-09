"""Turno pelo simulador de WhatsApp em PostgreSQL descartável (handler + persistência).

O que prova: webhook com o segredo real do backend → ``QueueWorker.handle_envelope``
(ingestão, pessoa, conversa, mensagem) → ``run_agent_for_message`` (lista piloto,
runtime, grafo, termo LGPD, opt-out) → ``EvolutionClient`` no modo simulado →
resposta registrada no simulador e gravada em ``messages``.

O que NÃO prova, por construção:

- Redis: a fila é ``_FilaMemoria`` e o dedupe usa ``_RedisSemMemoria``; o envelope
  entra direto no handler, sem ``enqueue``/``claim``/``ack``/lease reais.
- RLS: o schema vem de ``Base.metadata.create_all`` (modelos ORM), sem as
  policies das migrations; o isolamento entre igrejas não é exercitado.
- Ação privilegiada (visitante, célula etc.): só termo LGPD, SAIR e recusas.
- API autenticada e painel: ``_inbox`` consulta ``messages`` direto no banco.
- LLM: segue bloqueado porque ``ALLOW_REAL_SENDS=false``.

A prova integrada com Redis, policies reais e uma ação vertical é a F2b.
O marcador ``rls_integration`` só seleciona o job com PostgreSQL; não significa
que RLS foi verificada aqui.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import partial

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

import app.db.session  # noqa: F401 - registra o listener after_begin (paridade prod)
from app.config import Settings, get_settings
from app.db.models import (
    AgentConfig,
    Base,
    Conversation,
    Igreja,
    LlmCredential,
    Message,
    Pessoa,
    WhatsappConnection,
)
from app.domain import consent as consent_rules
from app.domain.phone import normalize_phone
from app.routers import whatsapp as whatsapp_router
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
from tests.conftest_rls import rls_database_url  # noqa: F401 - fixture

pytestmark = pytest.mark.rls_integration

# O conftest libera a lista piloto para toda a suíte; este arquivo prova o gate
# real, então guarda as funções originais antes do autouse e as restaura.
_REAL_PILOTO = Settings.whatsapp_piloto
_REAL_REPLY_ENABLED = worker_module._whatsapp_reply_enabled

_SCHEMA = "sim_turno"
_SIMULADOR = "http://simulador-whatsapp:8090"
_SEGREDO = "segredo-webhook-turno"
_INSTANCE = "igreja-dev"
_IGREJA = uuid.UUID("5a5a5a5a-0000-0000-0000-0000000000a1")
_IGREJA_NOME = "Igreja Simulada"
_TELEFONE = "5500988887777"


@pytest.fixture
def engine(rls_database_url: str) -> Iterator[Engine]:  # noqa: F811
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA}"},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
        )
        conn.exec_driver_sql(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
            "create role authenticated nologin noinherit nobypassrls; "
            "end if; end $$;"
        )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"grant usage on schema {_SCHEMA} to authenticated;")
        conn.exec_driver_sql(
            f"grant select, insert, update, delete on all tables in schema "
            f"{_SCHEMA} to authenticated;"
        )
        conn.exec_driver_sql(
            f"create or replace function {_SCHEMA}.current_igreja_id() "
            "returns uuid language sql stable as $$ "
            "select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid "
            "$$;"
        )
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


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


def _seed(factory: sessionmaker, *, agente_ativo: bool = True) -> None:
    with factory() as session:
        session.add(Igreja(id=_IGREJA, nome=_IGREJA_NOME))
        session.flush()
        session.add_all(
            [
                WhatsappConnection(igreja_id=_IGREJA, instance=_INSTANCE),
                AgentConfig(
                    igreja_id=_IGREJA,
                    comportamento="perfil sintético",
                    ativo=agente_ativo,
                ),
                LlmCredential(
                    igreja_id=_IGREJA,
                    provedor="synthetic",
                    modelo="synthetic",
                    api_key_encrypted="synthetic",
                    validado=True,
                    ativo=True,
                ),
            ]
        )
        session.commit()


class _Ambiente:
    """Simulador + webhook real + worker real, ligados pelo modo simulado."""

    def __init__(self, factory: sessionmaker) -> None:
        self.factory = factory
        self.fila = _FilaMemoria()
        backend = FastAPI()
        backend.include_router(whatsapp_router.router)
        backend.dependency_overrides[whatsapp_router.get_webhook_queue] = lambda: self.fila
        self.simulador = create_app(
            webhook_url="http://backend:8000/whatsapp/webhook",
            webhook_secret=_SEGREDO,
            webhook_client=TestClient(backend, base_url="http://backend:8000"),
        )
        self.ui = TestClient(self.simulador)
        evolution = EvolutionClient(get_settings())
        evolution._client = TestClient(self.simulador, base_url=_SIMULADOR)
        self.worker = QueueWorker(
            queue=WebhookQueue(redis_client=_RedisSemMemoria()),
            session_factory=factory,
            agent_runner=partial(run_agent_for_message, evolution_client=evolution),
        )

    def contato_envia(self, texto: str) -> IngestionResult:
        resposta = self.ui.post(
            "/simulador/mensagens",
            json={"instance": _INSTANCE, "telefone": _TELEFONE, "texto": texto},
        )
        assert resposta.json()["webhook_status"] == 202
        payload = self.fila.payloads.pop(0)
        return self.worker.handle_envelope(_Envelope(payload=payload))

    def respostas_do_bot(self) -> list[str]:
        conversa = self.ui.get(
            "/simulador/mensagens", params={"instance": _INSTANCE, "telefone": _TELEFONE}
        ).json()
        return [m["texto"] for m in conversa if m["direcao"] == "saida"]


@pytest.fixture
def ambiente_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(Settings, "whatsapp_piloto", _REAL_PILOTO)
    monkeypatch.setattr(worker_module, "_whatsapp_reply_enabled", _REAL_REPLY_ENABLED)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_REAL_SENDS", "false")
    monkeypatch.setenv("WHATSAPP_TRANSPORTE", "simulado")
    monkeypatch.setenv("EVOLUTION_SIMULADOR_URL", _SIMULADOR)
    monkeypatch.setenv("EVOLUTION_WEBHOOK_SECRET", _SEGREDO)
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(_IGREJA))
    for nome in (
        "JEV_ENABLED_IGREJA_IDS",
        "JEV_SHADOW_TRIAGE_IGREJA_IDS",
        "AGENT_PRIVILEGE_ENABLED_IGREJA_IDS",
    ):
        monkeypatch.delenv(nome, raising=False)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _inbox(factory: sessionmaker) -> list[tuple[str, str]]:
    """Mensagens com texto, como o inbox mostra."""
    with factory() as session:
        rows = session.execute(
            select(Message.direcao, Message.texto)
            .where(Message.igreja_id == _IGREJA, Message.texto.is_not(None))
            .order_by(Message.criado_em, Message.id)
        ).all()
    return [(r.direcao, r.texto) for r in rows]


def _intencoes_sem_envio(factory: sessionmaker) -> list[str]:
    """Estados das intenções de resposta que não viraram mensagem."""
    with factory() as session:
        return list(
            session.execute(
                select(Message.agent_reply_state)
                .where(
                    Message.igreja_id == _IGREJA,
                    Message.direcao == "out",
                    Message.texto.is_(None),
                )
                .order_by(Message.criado_em, Message.id)
            ).scalars()
        )


def test_oi_no_simulador_recebe_termo_lgpd_e_aparece_no_inbox(
    engine: Engine, ambiente_env: None
) -> None:
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    _seed(factory)
    amb = _Ambiente(factory)

    assert amb.contato_envia("oi") is IngestionResult.REGISTERED

    termo = consent_rules.term_text(get_settings().agent_term_version, _IGREJA_NOME)
    assert amb.respostas_do_bot() == [termo]
    with factory() as session:
        pessoa = session.execute(select(Pessoa).where(Pessoa.igreja_id == _IGREJA)).scalar_one()
        conversa = session.execute(
            select(Conversation).where(Conversation.igreja_id == _IGREJA)
        ).scalar_one()
    assert normalize_phone(pessoa.telefone) == normalize_phone(_TELEFONE)
    assert conversa.pessoa_id == pessoa.id
    assert _inbox(factory) == [("in", "oi"), ("out", termo)]


def test_sair_grava_optout_e_o_bot_nao_responde_mais(
    engine: Engine, ambiente_env: None
) -> None:
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    _seed(factory)
    amb = _Ambiente(factory)

    amb.contato_envia("SAIR")
    amb.contato_envia("oi")

    # Comportamento atual: o opt-out é gravado sem mensagem de confirmação.
    assert amb.respostas_do_bot() == []
    with factory() as session:
        pessoa = session.execute(select(Pessoa).where(Pessoa.igreja_id == _IGREJA)).scalar_one()
    assert pessoa.optout is True
    assert _inbox(factory) == [("in", "SAIR"), ("in", "oi")]
    assert _intencoes_sem_envio(factory) == ["ia_suprimida", "ia_suprimida"]


def test_igreja_fora_do_piloto_so_registra_no_inbox(
    engine: Engine, ambiente_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(uuid.uuid4()))
    get_settings.cache_clear()
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    _seed(factory)
    amb = _Ambiente(factory)

    assert amb.contato_envia("oi") is IngestionResult.REGISTERED

    assert amb.respostas_do_bot() == []
    assert _inbox(factory) == [("in", "oi")]
    # Fora do piloto o agente nem reserva resposta.
    assert _intencoes_sem_envio(factory) == []


def test_agente_inativo_nao_responde(engine: Engine, ambiente_env: None) -> None:
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    _seed(factory, agente_ativo=False)
    amb = _Ambiente(factory)

    assert amb.contato_envia("oi") is IngestionResult.REGISTERED

    assert amb.respostas_do_bot() == []
    assert _inbox(factory) == [("in", "oi")]
    assert _intencoes_sem_envio(factory) == ["ia_sem_resposta"]

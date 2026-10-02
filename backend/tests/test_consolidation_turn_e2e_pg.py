"""V3 1:1 WhatsApp turn through the real worker, catalog and reply fence."""

from __future__ import annotations

import datetime as dt
import json
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.session  # noqa: F401 - registers the tenant session listener
from app.agent import runtime as runtime_module
from app.db.models import (
    AgentActionProposal,
    AgentActionReceipt,
    AgentConfig,
    AppUser,
    Base,
    Consolidacao,
    ConsolidacaoEtapa,
    ConsentRecord,
    Conversation,
    Decision,
    Igreja,
    LlmCredential,
    Message,
    Pessoa,
    UserRole,
    WhatsappConnection,
    WhatsappReminderPreference,
    WorkQueueItem,
)
from app.services import crypto, semantic_triage, whatsapp_privilege
from app.services.agent_privilege_routing import ChoiceSelection
from app.services.llm import LLMClient
from app.workers import queue_worker as worker_module
from tests.conftest_rls import assert_disposable_database
from tests.test_whatsapp_consolidation_v3_migration_pg import (
    _MIGRATION as _V3_MIGRATION,
    _apply as _apply_v3_migration,
    v3_database as _v3_database,
)


pytestmark = pytest.mark.rls_integration

_TERM = "v3-turn-synthetic-term"
_INSTANCE = "v3-turn-synthetic"


def _turn_database_url() -> str:
    url = os.environ.get("V3_TURN_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("V3_TURN_DATABASE_URL não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path.rstrip("/") != "/v3_consolidation_test"
    ):
        raise RuntimeError("banco de turno V3 deve ser loopback e exclusivo")
    return url


@pytest.fixture
def rls_database_url() -> str:
    return _turn_database_url()


def _install_runtime_model_columns(connection) -> None:
    """Complete only mapped parent columns absent from the V3 migration fixture."""

    connection.exec_driver_sql(
        """
        alter table public.igrejas
          add column if not exists nome text not null default 'Igreja sintética',
          add column if not exists plano text,
          add column if not exists setup_fee_override numeric(10,2),
          add column if not exists dono_id uuid,
          add column if not exists logo_path text,
          add column if not exists endereco_institucional text,
          add column if not exists horarios_culto text,
          add column if not exists notification_outbox_cutover_at timestamptz not null default now(),
          add column if not exists created_at timestamptz not null default now();
        alter table public.pessoas
          add column if not exists nome text not null default 'Pessoa sintética',
          add column if not exists email text,
          add column if not exists genero varchar,
          add column if not exists faixa_etaria text,
          add column if not exists endereco text,
          add column if not exists tipo varchar,
          add column if not exists etapa varchar,
          add column if not exists subetapa varchar,
          add column if not exists presencas_celula integer not null default 0,
          add column if not exists aceitou_jesus boolean not null default false,
          add column if not exists acompanhamento varchar,
          add column if not exists origem text,
          add column if not exists primeiro_contato timestamptz,
          add column if not exists celula_id uuid,
          add column if not exists lider_id uuid,
          add column if not exists consentimento boolean not null default false,
          add column if not exists apto_proxima_cd boolean not null default false,
          add column if not exists apto_lider boolean not null default false,
          add column if not exists sem_interesse boolean not null default false,
          add column if not exists sem_interesse_motivo text,
          add column if not exists arquivada_por uuid,
          add column if not exists arquivada_motivo text,
          add column if not exists created_at timestamptz not null default now();
        alter table public.app_users
          add column if not exists celula_pendente_id uuid,
          add column if not exists nome text not null default 'Operador sintético',
          add column if not exists email text not null default 'operator@example.test',
          add column if not exists chat_nome text,
          add column if not exists created_at timestamptz not null default now(),
          add column if not exists password_changed_at timestamptz;
        alter table public.decisions
          alter column id set default gen_random_uuid();
        alter table public.agent_action_proposals
          alter column id set default gen_random_uuid(),
          add column if not exists conversation_id uuid,
          add column if not exists actor_pessoa_id uuid,
          add column if not exists actor_app_user_id uuid,
          add column if not exists source_message_id uuid,
          add column if not exists target_id uuid,
          add column if not exists arguments_json jsonb,
          add column if not exists arguments_sha256 text,
          add column if not exists scope_fingerprint text,
          add column if not exists summary_sha256 text,
          add column if not exists state text,
          add column if not exists summary_message_id uuid,
          add column if not exists confirmation_message_id uuid,
          add column if not exists delivered_at timestamptz,
          add column if not exists expires_at timestamptz,
          add column if not exists executed_at timestamptz,
          add column if not exists terminal_reason text,
          add column if not exists created_at timestamptz not null default now();
        alter table public.agent_action_receipts
          alter column id set default gen_random_uuid(),
          add column if not exists igreja_id uuid,
          add column if not exists proposal_id uuid,
          add column if not exists conversation_id uuid,
          add column if not exists confirmation_message_id uuid,
          add column if not exists outcome text,
          add column if not exists effect_reference text,
          add column if not exists created_at timestamptz not null default now();
        alter table public.agenda_reminder_subscriptions
          add column if not exists pessoa_id uuid,
          add column if not exists event_id uuid,
          add column if not exists occurrence_at timestamptz,
          add column if not exists proposal_id uuid,
          add column if not exists state text,
          add column if not exists term_version text,
          add column if not exists confirmed_at timestamptz,
          add column if not exists updated_at timestamptz;
        """
    )


@pytest.fixture
def v3_turn_database(rls_database_url: str) -> Engine:
    generator = _v3_database.__wrapped__(rls_database_url)
    engine = next(generator)
    try:
        _apply_v3_migration(engine, _V3_MIGRATION.read_text())
        with engine.begin() as connection:
            _install_runtime_model_columns(connection)
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("grant usage on schema public to authenticated")
            connection.exec_driver_sql(
                "grant select, insert, update, delete on all tables in schema public to authenticated"
            )
            connection.exec_driver_sql(
                "grant usage, select on all sequences in schema public to authenticated"
            )
            connection.exec_driver_sql(
                "revoke delete on table public.consolidation_whatsapp_activation from authenticated"
            )
        yield engine
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _seed(
    factory: sessionmaker[Session],
    *,
    inbound_text: str = "Quais pendências de consolidação existem?",
) -> SimpleNamespace:
    values = SimpleNamespace(
        tenant=uuid.uuid4(),
        actor_person=uuid.uuid4(),
        actor=uuid.uuid4(),
        other_person=uuid.uuid4(),
        other=uuid.uuid4(),
        subject=uuid.uuid4(),
        consolidation=uuid.uuid4(),
        # Numeric-only opaque codes hit the existing routing privacy guard.
        # Keep this happy-path task code alphanumeric; retain UUID entropy,
        # version and variant. The source incompatibility needs its own fix.
        item=uuid.UUID("c0c0c0c0c0" + uuid.uuid4().hex[10:]),
        conversation=uuid.uuid4(),
        inbound=uuid.uuid4(),
    )
    with factory.begin() as session:
        session.add(Igreja(id=values.tenant, nome="Igreja Sintética"))
        session.flush()
        session.add_all(
            [
                Pessoa(
                    id=values.actor_person,
                    igreja_id=values.tenant,
                    nome="Ana Sintética",
                    telefone="5500000000102",
                    consentimento=True,
                ),
                Pessoa(
                    id=values.other_person,
                    igreja_id=values.tenant,
                    nome="Bia Sintética",
                    telefone="5500000000103",
                    consentimento=True,
                ),
                Pessoa(
                    id=values.subject,
                    igreja_id=values.tenant,
                    nome="Marina Privada",
                    telefone="5500000000101",
                    consentimento=True,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                AppUser(
                    id=values.actor,
                    igreja_id=values.tenant,
                    pessoa_id=values.actor_person,
                    clerk_user_id="clerk-v3-turn-actor",
                    nome="Ana Operadora",
                    email="ana@example.test",
                    status="ativo",
                ),
                AppUser(
                    id=values.other,
                    igreja_id=values.tenant,
                    pessoa_id=values.other_person,
                    clerk_user_id="clerk-v3-turn-other",
                    nome="Bia Operadora",
                    email="bia@example.test",
                    status="ativo",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserRole(igreja_id=values.tenant, user_id=values.actor, papel="lider_consol"),
                UserRole(igreja_id=values.tenant, user_id=values.other, papel="lider_consol"),
                ConsentRecord(
                    igreja_id=values.tenant,
                    pessoa_id=values.actor_person,
                    termo_versao=_TERM,
                    aceite_em=dt.datetime.now(dt.timezone.utc),
                ),
                AgentConfig(
                    igreja_id=values.tenant,
                    comportamento="Teste de turno V3",
                    ativo=True,
                ),
                LlmCredential(
                    igreja_id=values.tenant,
                    provedor="openai",
                    modelo="gpt-5.6-luna",
                    api_key_encrypted="synthetic-ciphertext",
                    validado=True,
                    ativo=True,
                ),
                WhatsappConnection(
                    igreja_id=values.tenant,
                    instance=_INSTANCE,
                    status="open",
                    numero="5500000000000",
                ),
                Conversation(
                    id=values.conversation,
                    igreja_id=values.tenant,
                    pessoa_id=values.actor_person,
                    telefone="5500000000102",
                    estado="ia",
                ),
                Consolidacao(
                    id=values.consolidation,
                    igreja_id=values.tenant,
                    pessoa_id=values.subject,
                    responsavel_id=values.actor,
                    tipo="individual",
                    concluida=False,
                    progresso=0,
                ),
                WorkQueueItem(
                    id=values.item,
                    igreja_id=values.tenant,
                    consolidacao_id=values.consolidation,
                    pessoa_id=values.subject,
                    responsavel_id=values.actor,
                    tipo="conectar_celula",
                    titulo="Conectar",
                    status="aberto",
                    prazo=dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc),
                    prioridade=1,
                ),
                Message(
                    id=values.inbound,
                    igreja_id=values.tenant,
                    conversation_id=values.conversation,
                    direcao="in",
                    autor="contato",
                    texto=inbound_text,
                    provider_message_id="V3-TURN-INBOUND",
                ),
            ]
        )
        session.flush()
        fono = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == values.tenant,
                WorkQueueItem.consolidacao_id == values.consolidation,
                WorkQueueItem.tipo == "fonovisita",
            )
        ).scalar_one()
        fono.id = uuid.UUID("f0f0f0f0f0" + fono.id.hex[10:])
    return values


def _outcome(values: SimpleNamespace) -> worker_module.IngestionOutcome:
    return worker_module.IngestionOutcome(
        result=worker_module.IngestionResult.REGISTERED,
        igreja_id=values.tenant,
        conversation_id=values.conversation,
        inbound_message_id=values.inbound,
        instance=_INSTANCE,
        telefone="5500000000102",
        texto="texto adulterado não é autoridade",
        inbound=True,
        provider_message_id="V3-TURN-INBOUND",
        claim_id="v3-turn-claim",
    )


def _append_inbound(
    factory: sessionmaker[Session],
    values: SimpleNamespace,
    *,
    text_value: str,
    provider_message_id: str,
) -> worker_module.IngestionOutcome:
    inbound_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            Message(
                id=inbound_id,
                igreja_id=values.tenant,
                conversation_id=values.conversation,
                direcao="in",
                autor="contato",
                texto=text_value,
                provider_message_id=provider_message_id,
            )
        )
    return worker_module.IngestionOutcome(
        result=worker_module.IngestionResult.REGISTERED,
        igreja_id=values.tenant,
        conversation_id=values.conversation,
        inbound_message_id=inbound_id,
        instance=_INSTANCE,
        telefone="5500000000102",
        texto="outcome não é autoridade",
        inbound=True,
        provider_message_id=provider_message_id,
        claim_id=f"claim-{provider_message_id}",
    )


def _set_inbound_text(
    factory: sessionmaker[Session], values: SimpleNamespace, text_value: str
) -> None:
    with factory.begin() as session:
        message = session.get(Message, values.inbound)
        assert message is not None
        message.texto = text_value


def _linked_fonovisita_id(
    factory: sessionmaker[Session], values: SimpleNamespace
) -> uuid.UUID:
    with factory() as session:
        rows = session.execute(
            select(WorkQueueItem.id).where(
                WorkQueueItem.igreja_id == values.tenant,
                WorkQueueItem.consolidacao_id == values.consolidation,
                WorkQueueItem.tipo == "fonovisita",
            )
        ).scalars().all()
    assert len(rows) == 1
    return rows[0]


class _ClassifiedEvolution:
    def __init__(self, *statuses: str) -> None:
        self._statuses = list(statuses or ("aceito",))
        self.calls: list[tuple[str | None, str | None, str]] = []

    def send_text_classificado(self, instance, telefone, texto):
        self.calls.append((instance, telefone, texto))
        return SimpleNamespace(status=self._statuses.pop(0) if self._statuses else "aceito")


def _install_v3_gates(monkeypatch: pytest.MonkeyPatch, tenant: uuid.UUID) -> None:
    from app.agent import privileged_turn
    from app.services import (
        agent_privilege_catalog,
        cell_report_whatsapp,
        consolidation_whatsapp,
    )

    settings = SimpleNamespace(
        agent_term_version=_TERM,
        agent_trusted_inbound_identity_enabled=False,
        effective_session_secret="v3-turn-synthetic-secret",
        frontend_url="https://app.igreja12.example",
    )
    monkeypatch.setattr(whatsapp_privilege, "PRIVILEGE_APPROVED_RELEASE_ID", "v3-turn-release")
    monkeypatch.setattr(
        consolidation_whatsapp,
        "CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID",
        "v3-turn-release",
    )
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", str(tenant))
    monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", str(tenant))
    monkeypatch.setattr(worker_module, "_whatsapp_reply_enabled", lambda igreja_id: igreja_id == tenant)
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_module, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_privilege, "get_settings", lambda: settings)
    monkeypatch.setattr(agent_privilege_catalog, "get_settings", lambda: settings)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(semantic_triage, "tier_a_enabled_from_environment", lambda _tenant: False)
    monkeypatch.setattr(cell_report_whatsapp, "cell_report_enabled_from_environment", lambda _tenant: False)
    monkeypatch.setattr(crypto, "decrypt_secret", lambda _cipher: "synthetic-key")
    assert privileged_turn._enabled(tenant)


def _route_to(monkeypatch: pytest.MonkeyPatch, action: str) -> list[str]:
    """Use the real B/C/D protocol while faking only its external provider."""

    stages: list[str] = []

    def choose(_client, _system, _prompt, *, schema_name, choices, timeout_seconds):
        assert timeout_seconds > 0
        stages.append(schema_name)
        answer = (
            "restrita"
            if schema_name == "s3_route"
            else action
            if schema_name == "s3_tool"
            else "h1"
        )
        assert answer in choices
        return ChoiceSelection(answer)

    monkeypatch.setattr(LLMClient, "generate_typed", choose)
    return stages


def test_pending_query_uses_server_projection_and_aba_reassignment_fences_retry_before_http(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry sees A→B→A revision change before its second provider call."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    _install_v3_gates(monkeypatch, values.tenant)
    prompts: list[str] = []

    def choose(_client, _system, user_prompt, *, schema_name, choices, timeout_seconds):
        assert timeout_seconds > 0
        prompts.append(user_prompt)
        payload = json.loads(user_prompt)
        assert "Marina" not in user_prompt
        assert "5500000000101" not in user_prompt
        if schema_name == "s3_route":
            answer = "restrita"
        elif schema_name == "s3_tool":
            assert payload["ferramentas"] == {
                "consultar_pendencias_consolidacao": (
                    "Consultar pendências de consolidação autorizadas sem dados pessoais"
                )
            }
            answer = "consultar_pendencias_consolidacao"
        else:
            raise AssertionError(f"stage inesperado: {schema_name}")
        assert answer in choices
        return ChoiceSelection(answer)

    monkeypatch.setattr(LLMClient, "generate_typed", choose)
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    outcome = _outcome(values)

    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert len(prompts) == 2
    assert len(evolution.calls) == 1
    assert evolution.calls[0][0:2] == (_INSTANCE, "5500000000102")
    assert "Marina" in evolution.calls[0][2]
    assert f"P-{values.item.hex[:10].upper()}" in evolution.calls[0][2]

    with factory.begin() as session:
        track = session.get(Consolidacao, values.consolidation)
        task = session.get(WorkQueueItem, values.item)
        assert track is not None and task is not None
        track.responsavel_id = values.other
        task.responsavel_id = values.other
    with factory.begin() as session:
        track = session.get(Consolidacao, values.consolidation)
        task = session.get(WorkQueueItem, values.item)
        assert track is not None and task is not None
        track.responsavel_id = values.actor
        task.responsavel_id = values.actor

    assert worker_module.run_agent_for_message(factory, outcome, evolution_client=evolution) is worker_module.AgentRunDisposition.COMPLETED
    assert len(evolution.calls) == 1
    with factory() as session:
        outbound = session.execute(
            select(Message).where(
                Message.igreja_id == values.tenant,
                Message.direcao == "out",
                Message.autor == "ia",
            )
        ).scalar_one()
        assert outbound.agent_reply_state == "ia_suprimida"
        assert outbound.agent_privilege_context["kind"] == "consolidation"
        assert session.get(Consolidacao, values.consolidation).assignment_revision == 2


def test_lider_celula_turn_sees_own_fonovisita_and_confirms_only_that_task(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cell leader gets no connection task and can confirm its own fono."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    fono_id = _linked_fonovisita_id(factory, values)
    with factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == values.tenant,
                UserRole.user_id == values.actor,
            )
        ).scalar_one()
        role.papel = "lider_celula"
    _install_v3_gates(monkeypatch, values.tenant)
    query_stages = _route_to(monkeypatch, "consultar_pendencias_consolidacao")
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert query_stages == ["s3_route", "s3_tool"]
    assert len(evolution.calls) == 1
    reply = evolution.calls[0][2]
    assert f"P-{fono_id.hex[:10].upper()}" in reply
    assert f"P-{values.item.hex[:10].upper()}" not in reply
    assert "conexão com célula" not in reply

    fono_request = _append_inbound(
        factory,
        values,
        text_value=f"Confirmar fonovisita feita P-{fono_id.hex[:10].upper()}",
        provider_message_id="V3-TURN-LIDER-CELULA-FONO",
    )
    fono_stages = _route_to(monkeypatch, "marcar_fonovisita_feita")
    assert worker_module.run_agent_for_message(
        factory, fono_request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert fono_stages == ["s3_route", "s3_tool", "s3_handle"]
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant,
                AgentActionProposal.action == "marcar_fonovisita_feita",
            )
        ).scalar_one()
        assert proposal.arguments_json["work_queue_item_id"] == str(fono_id)

    confirmation = _append_inbound(
        factory,
        values,
        text_value="SIM",
        provider_message_id="V3-TURN-LIDER-CELULA-SIM",
    )
    assert worker_module.run_agent_for_message(
        factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        fono = session.get(WorkQueueItem, fono_id)
        connection = session.get(WorkQueueItem, values.item)
        assert fono is not None and fono.status == "resolvido"
        assert connection is not None and connection.status == "aberto"


def test_lider_celula_turn_does_not_project_or_confirm_another_responsibles_work(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An assigned cell leader has no V3 visibility after another assignment."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    fono_id = _linked_fonovisita_id(factory, values)
    with factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == values.tenant,
                UserRole.user_id == values.actor,
            )
        ).scalar_one()
        role.papel = "lider_celula"
        track = session.get(Consolidacao, values.consolidation)
        assert track is not None
        track.responsavel_id = values.other
        for task in session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == values.tenant,
                WorkQueueItem.consolidacao_id == values.consolidation,
            )
        ).scalars():
            task.responsavel_id = values.other
    _install_v3_gates(monkeypatch, values.tenant)
    _route_to(monkeypatch, "consultar_pendencias_consolidacao")
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert len(evolution.calls) == 1
    reply = evolution.calls[0][2]
    assert reply == "Não há pendências de consolidação no seu escopo. Abra o painel: https://app.igreja12.example/#consolidar"
    assert "Marina" not in reply
    assert "P-" not in reply

    request = _append_inbound(
        factory,
        values,
        text_value=f"Confirmar fonovisita feita P-{fono_id.hex[:10].upper()}",
        provider_message_id="V3-TURN-LIDER-CELULA-OUTRO",
    )
    _route_to(monkeypatch, "consultar_pendencias_consolidacao")
    assert worker_module.run_agent_for_message(
        factory, request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        assert session.execute(
            select(AgentActionProposal.id).where(
                AgentActionProposal.igreja_id == values.tenant,
                AgentActionProposal.action == "marcar_fonovisita_feita",
            )
        ).all() == []


@pytest.mark.parametrize(
    ("role_state", "inbound_text"),
    (
        ("membro", "Confirmar fonovisita feita P-1234567890"),
        ("membro", "Quais pendências de consolidação existem?"),
        (
            "membro",
            "Quais pendências de consolidação? hoje planejo desaparecer para sempre.",
        ),
        ("revogado", "Confirmar fonovisita feita P-1234567890"),
        ("revogado", "Quais pendências de consolidação existem?"),
        (
            "revogado",
            "Quais pendências de consolidação? hoje planejo desaparecer para sempre.",
        ),
    ),
)
def test_recognized_v3_request_without_current_role_handoffs_before_router_or_transport(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    role_state: str,
    inbound_text: str,
) -> None:
    """A revoked or unrelated role cannot fall through to generic routing."""

    from app.services import agent_privilege_catalog

    factory = _factory(v3_turn_database)
    values = _seed(factory, inbound_text=inbound_text)
    with factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == values.tenant,
                UserRole.user_id == values.actor,
                UserRole.papel == "lider_consol",
            )
        ).scalar_one()
        if role_state == "membro":
            role.papel = "membro"
        else:
            session.delete(role)
    _install_v3_gates(monkeypatch, values.tenant)
    observed_roles: list[frozenset[str]] = []
    original_projection = agent_privilege_catalog.consolidation_routing_projection

    def observe_projection(session, context):
        observed_roles.append(context.roles)
        return original_projection(session, context)

    monkeypatch.setattr(
        agent_privilege_catalog,
        "consolidation_routing_projection",
        observe_projection,
    )
    monkeypatch.setattr(
        LLMClient,
        "generate_typed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("V3 incapaz não pode chegar ao roteador")
        ),
    )
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert observed_roles == [
        frozenset({"membro"}) if role_state == "membro" else frozenset()
    ]
    assert evolution.calls == []
    with factory() as session:
        conversation = session.get(Conversation, values.conversation)
        assert conversation is not None and conversation.estado == "humano"
        assert session.execute(
            select(AgentActionProposal.id).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).all() == []


def test_lider_g12_turn_sees_its_own_connection_task(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The G12 role retains the human resolver capability for connection."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    with factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == values.tenant,
                UserRole.user_id == values.actor,
            )
        ).scalar_one()
        role.papel = "lider_g12"
    _install_v3_gates(monkeypatch, values.tenant)
    _route_to(monkeypatch, "consultar_pendencias_consolidacao")
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert len(evolution.calls) == 1
    reply = evolution.calls[0][2]
    assert f"P-{values.item.hex[:10].upper()}" in reply
    assert "conexão com célula" in reply


def test_lider_g12_turn_confirms_its_own_fonovisita(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The G12 role uses the same canonical fono confirmation service."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    fono_id = _linked_fonovisita_id(factory, values)
    _set_inbound_text(
        factory,
        values,
        f"Confirmar fonovisita feita P-{fono_id.hex[:10].upper()}",
    )
    with factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == values.tenant,
                UserRole.user_id == values.actor,
            )
        ).scalar_one()
        role.papel = "lider_g12"
    _install_v3_gates(monkeypatch, values.tenant)
    _route_to(monkeypatch, "marcar_fonovisita_feita")
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant,
                AgentActionProposal.action == "marcar_fonovisita_feita",
            )
        ).scalar_one()
        assert proposal.state == "pendente"
        assert proposal.terminal_reason is None
        assert proposal.delivered_at is not None
        assert proposal.summary_message_id is not None
        summary = session.get(Message, proposal.summary_message_id)
        assert summary is not None
        assert summary.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
    confirmation = _append_inbound(
        factory,
        values,
        text_value="SIM",
        provider_message_id="V3-TURN-LIDER-G12-SIM",
    )
    assert worker_module.run_agent_for_message(
        factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant,
                AgentActionProposal.action == "marcar_fonovisita_feita",
            )
        ).scalar_one()
        receipt = session.execute(
            select(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == values.tenant,
                AgentActionReceipt.proposal_id == proposal.id,
            )
        ).scalar_one()
        assert proposal.state == "executada"
        assert proposal.terminal_reason == "confirmed"
        assert proposal.confirmation_message_id == confirmation.inbound_message_id
        assert receipt.confirmation_message_id == confirmation.inbound_message_id
        assert receipt.receipt_text == "Fonovisita confirmada."
        fono = session.get(WorkQueueItem, fono_id)
        connection = session.get(WorkQueueItem, values.item)
        assert fono is not None and fono.status == "resolvido"
        assert connection is not None and connection.status == "aberto"


@pytest.mark.parametrize("change", ("role_revoked", "phone_ambiguous"))
def test_pending_reply_retry_is_suppressed_before_second_http_when_identity_loses_scope(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """Role and canonical-phone changes invalidate a persisted V3 reply before retry."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    _install_v3_gates(monkeypatch, values.tenant)
    _route_to(monkeypatch, "consultar_pendencias_consolidacao")
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    outcome = _outcome(values)

    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(factory, outcome, evolution_client=evolution)
    assert len(evolution.calls) == 1

    with factory.begin() as session:
        if change == "role_revoked":
            role = session.execute(
                select(UserRole).where(
                    UserRole.igreja_id == values.tenant,
                    UserRole.user_id == values.actor,
                    UserRole.papel == "lider_consol",
                )
            ).scalar_one()
            session.delete(role)
        else:
            session.add(
                Pessoa(
                    id=uuid.uuid4(),
                    igreja_id=values.tenant,
                    nome="Identidade Ambígua",
                    telefone="5500000000102",
                    consentimento=True,
                )
            )

    assert worker_module.run_agent_for_message(
        factory, outcome, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert len(evolution.calls) == 1
    with factory() as session:
        outbound = session.execute(
            select(Message).where(
                Message.igreja_id == values.tenant,
                Message.direcao == "out",
                Message.autor == "ia",
            )
        ).scalar_one()
        assert outbound.agent_reply_state == "ia_suprimida"


@pytest.mark.parametrize(
    ("inbound_text", "expected_optout", "expected_disabled_preferences"),
    (
        ("SAIR", True, ("agenda", "cell_report", "consolidation")),
        ("PARAR LEMBRETES", False, ("agenda", "cell_report", "consolidation")),
        (
            "Quais pendências de consolidação? hoje planejo desaparecer para sempre.",
            False,
            (),
        ),
        ("Registrar decisão de Marina Privada hoje", False, ()),
    ),
)
def test_v3_stop_and_unsafe_inbound_are_suppressed_before_router_or_transport(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    inbound_text: str,
    expected_optout: bool,
    expected_disabled_preferences: tuple[str, ...],
) -> None:
    """Hard controls and unsafe recognized V3 residuals never reach a provider."""

    factory = _factory(v3_turn_database)
    values = _seed(factory, inbound_text=inbound_text)
    _install_v3_gates(monkeypatch, values.tenant)
    monkeypatch.setattr(
        LLMClient,
        "generate_typed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("V3 suprimido não pode chamar roteador")
        ),
    )
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory,
        _outcome(values),
        evolution_client=evolution,
    ) is worker_module.AgentRunDisposition.COMPLETED

    assert evolution.calls == []
    with factory() as session:
        actor = session.get(Pessoa, values.actor_person)
        assert actor is not None and actor.optout is expected_optout
        preferences = tuple(
            session.execute(
                select(WhatsappReminderPreference.reminder_kind)
                .where(
                    WhatsappReminderPreference.igreja_id == values.tenant,
                    WhatsappReminderPreference.pessoa_id == values.actor_person,
                    WhatsappReminderPreference.state == "disabled",
                )
                .order_by(WhatsappReminderPreference.reminder_kind)
            ).scalars()
        )
        assert preferences == expected_disabled_preferences
        assert session.execute(
            select(AgentActionProposal.id).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).all() == []


def test_ambiguous_decision_target_handoffs_before_router_or_transport(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A V3 decision request never lets the router choose between same-name people."""

    factory = _factory(v3_turn_database)
    values = _seed(factory, inbound_text="Registrar decisão de Marina Privada")
    with factory.begin() as session:
        session.add(
            Pessoa(
                id=uuid.uuid4(),
                igreja_id=values.tenant,
                nome="Marina Privada",
                telefone="5500000000104",
                consentimento=True,
            )
        )
    _install_v3_gates(monkeypatch, values.tenant)
    monkeypatch.setattr(
        LLMClient,
        "generate_typed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("alvo ambíguo não pode chamar roteador")
        ),
    )
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert evolution.calls == []
    with factory() as session:
        assert session.execute(
            select(AgentActionProposal.id).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).all() == []


def test_consolidation_optin_uses_s3_confirmation_and_writes_versioned_preference(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit opt-in is self-only and becomes active only after delivered SIM."""

    factory = _factory(v3_turn_database)
    values = _seed(
        factory,
        inbound_text="Quero ativar lembretes de consolidação",
    )
    _install_v3_gates(monkeypatch, values.tenant)
    stages = _route_to(monkeypatch, "configurar_lembrete_consolidacao")
    evolution = _ClassifiedEvolution()
    request = _outcome(values)

    assert worker_module.run_agent_for_message(
        factory, request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).scalar_one()
        assert proposal.action == "configurar_lembrete_consolidacao"
        assert proposal.state == "pendente"
        assert proposal.arguments_json == {
            "pessoa_id": str(values.actor_person),
            "term_version": _TERM,
        }
    assert stages == ["s3_route", "s3_tool", "s3_handle"]
    assert len(evolution.calls) == 1

    confirmation = _append_inbound(
        factory,
        values,
        text_value="SIM",
        provider_message_id="V3-TURN-OPTIN-SIM",
    )
    assert worker_module.run_agent_for_message(
        factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED

    assert len(evolution.calls) == 2
    with factory() as session:
        preference = session.execute(
            select(WhatsappReminderPreference).where(
                WhatsappReminderPreference.igreja_id == values.tenant,
                WhatsappReminderPreference.pessoa_id == values.actor_person,
                WhatsappReminderPreference.reminder_kind == "consolidation",
            )
        ).scalar_one()
        assert preference.state == "active"
        assert preference.term_version == _TERM
        assert preference.accepted_at is not None
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).scalar_one()
        receipt = session.execute(
            select(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == values.tenant
            )
        ).scalar_one()
        assert proposal.state == "executada"
        assert receipt.proposal_id == proposal.id
        assert receipt.receipt_text == "Lembretes de consolidação ativados."


def test_consolidation_fonovisita_confirmation_executes_canonical_work_item_once(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed opaque fono command resolves only the linked canonical item."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    fono_id = _linked_fonovisita_id(factory, values)
    _set_inbound_text(
        factory,
        values,
        f"Confirmar fonovisita feita P-{fono_id.hex[:10].upper()}",
    )
    _install_v3_gates(monkeypatch, values.tenant)
    stages = _route_to(monkeypatch, "marcar_fonovisita_feita")
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).scalar_one()
        assert proposal.action == "marcar_fonovisita_feita"
        assert proposal.state == "pendente"
        assert proposal.arguments_json == {
            "consolidacao_id": str(values.consolidation),
            "work_queue_item_id": str(fono_id),
            "assignment_revision": 0,
        }
    assert stages == ["s3_route", "s3_tool", "s3_handle"]

    confirmation = _append_inbound(
        factory,
        values,
        text_value="SIM",
        provider_message_id="V3-TURN-FONO-SIM",
    )
    assert worker_module.run_agent_for_message(
        factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED

    with factory() as session:
        fono = session.get(WorkQueueItem, fono_id)
        assert fono is not None and fono.status == "resolvido"
        stage = session.execute(
            select(ConsolidacaoEtapa).where(
                ConsolidacaoEtapa.igreja_id == values.tenant,
                ConsolidacaoEtapa.consolidacao_id == values.consolidation,
                ConsolidacaoEtapa.etapa == "fonovisita",
            )
        ).scalar_one()
        assert stage.concluida is True
        assert stage.confirmada_por == values.actor
        receipt = session.execute(
            select(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == values.tenant
            )
        ).scalar_one()
        assert receipt.receipt_text == "Fonovisita confirmada."
    assert len(evolution.calls) == 2


def test_consolidation_assignment_confirmation_synchronizes_open_linked_work(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One explicit S3 assignment updates the track and all active linked tasks."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    _set_inbound_text(
        factory,
        values,
        f"Atribuir P-{values.item.hex[:10].upper()} para Bia Sintética",
    )
    _install_v3_gates(monkeypatch, values.tenant)
    stages = _route_to(monkeypatch, "atribuir_consolidacao")
    evolution = _ClassifiedEvolution()

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).scalar_one()
        assert proposal.action == "atribuir_consolidacao"
        assert proposal.arguments_json == {
            "consolidacao_id": str(values.consolidation),
            "responsavel_id": str(values.other),
            "assignment_revision": 0,
        }
    assert stages == ["s3_route", "s3_tool", "s3_handle"]

    confirmation = _append_inbound(
        factory,
        values,
        text_value="SIM",
        provider_message_id="V3-TURN-ASSIGN-SIM",
    )
    assert worker_module.run_agent_for_message(
        factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED

    with factory() as session:
        track = session.get(Consolidacao, values.consolidation)
        assert track is not None
        assert track.responsavel_id == values.other
        assert track.assignment_revision == 1
        linked = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == values.tenant,
                WorkQueueItem.consolidacao_id == values.consolidation,
                WorkQueueItem.status.in_(("aberto", "assumido")),
            )
        ).scalars().all()
        assert linked
        assert {item.responsavel_id for item in linked} == {values.other}
        assert {item.status for item in linked} == {"assumido"}
        receipt = session.execute(
            select(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == values.tenant
            )
        ).scalar_one()
        assert receipt.receipt_text == "Consolidação atribuída."
    assert len(evolution.calls) == 2


def test_register_decision_confirmation_opens_canonical_24h_track_and_fonovisita(
    v3_turn_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing S3 decision action creates one V3-linked canonical track."""

    factory = _factory(v3_turn_database)
    values = _seed(factory)
    with factory.begin() as session:
        prior = session.get(Consolidacao, values.consolidation)
        assert prior is not None
        prior.concluida = True
    _set_inbound_text(factory, values, "Registrar decisão de Marina Privada")
    _install_v3_gates(monkeypatch, values.tenant)
    stages: list[str] = []
    prompts: list[str] = []

    def choose(_client, _system, user_prompt, *, schema_name, choices, timeout_seconds):
        assert timeout_seconds > 0
        stages.append(schema_name)
        prompts.append(user_prompt)
        answer = (
            "restrita"
            if schema_name == "s3_route"
            else "registrar_decisao"
            if schema_name == "s3_tool"
            else "h1"
        )
        assert answer in choices
        return ChoiceSelection(answer)

    monkeypatch.setattr(LLMClient, "generate_typed", choose)
    evolution = _ClassifiedEvolution()
    before = dt.datetime.now(dt.timezone.utc)

    assert worker_module.run_agent_for_message(
        factory, _outcome(values), evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    with factory() as session:
        proposal = session.execute(
            select(AgentActionProposal).where(
                AgentActionProposal.igreja_id == values.tenant
            )
        ).scalar_one()
        assert proposal.action == "registrar_decisao"
        assert proposal.arguments_json == {
            "celula_id": None,
            "pessoa_id": str(values.subject),
            "vinculo": "visitante",
        }
    assert stages == ["s3_route", "s3_tool", "s3_handle"]
    assert all("Marina" not in prompt for prompt in prompts)
    assert all("5500000000101" not in prompt for prompt in prompts)

    confirmation = _append_inbound(
        factory,
        values,
        text_value="SIM",
        provider_message_id="V3-TURN-DECISION-SIM",
    )
    assert worker_module.run_agent_for_message(
        factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    after = dt.datetime.now(dt.timezone.utc)

    with factory() as session:
        decision = session.execute(
            select(Decision).where(
                Decision.igreja_id == values.tenant,
                Decision.pessoa_id == values.subject,
            )
        ).scalar_one()
        assert decision.vinculo == "visitante"
        assert decision.prazo_conexao is not None
        assert before + dt.timedelta(hours=23, minutes=59) < decision.prazo_conexao < after + dt.timedelta(hours=24, minutes=1)
        track = session.execute(
            select(Consolidacao).where(
                Consolidacao.igreja_id == values.tenant,
                Consolidacao.origin_decision_id == decision.id,
            )
        ).scalar_one()
        assert track.pessoa_id == values.subject
        assert track.prazo_conexao == decision.prazo_conexao
        linked = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == values.tenant,
                WorkQueueItem.consolidacao_id == track.id,
            )
        ).scalars().all()
        connection = [item for item in linked if item.tipo == "conectar_celula"]
        fonovisitas = [item for item in linked if item.tipo == "fonovisita"]
        assert len(connection) == 1
        assert connection[0].prazo is not None
        assert before + dt.timedelta(hours=23, minutes=59) < connection[0].prazo < after + dt.timedelta(hours=24, minutes=1)
        assert len(fonovisitas) == 1
        assert fonovisitas[0].prazo is None
        receipt = session.execute(
            select(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == values.tenant
            )
        ).scalar_one()
        assert receipt.receipt_text == "Registro confirmado."
    assert len(evolution.calls) == 2

"""SQLAlchemy ORM models for the core multi-tenant tables (SPEC 2.1).

Only the tables used by the auth/RBAC layer and the routers wired in this
sprint are mapped here: igrejas, pessoas, app_users, user_roles,
role_permissions, celulas and subscriptions (billing gate at login). Other
tables exist in the migrations and can be added as their routers land.

Enum columns are mapped as plain strings: the database enforces the enum types,
so we keep the Python side simple and forward-compatible.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class Igreja(Base):
    """Tenant root (F1). The only core table without igreja_id."""

    __tablename__ = "igrejas"

    id: Mapped[uuid.UUID] = _uuid_pk()
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'ativa'")
    )
    plano: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Pessoa(Base):
    """Unified person model (F2/F6/F7)."""

    __tablename__ = "pessoas"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    telefone: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    genero: Mapped[str | None] = mapped_column(String, nullable=True)
    faixa_etaria: Mapped[str | None] = mapped_column(Text, nullable=True)
    endereco: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo: Mapped[str | None] = mapped_column(String, nullable=True)
    etapa: Mapped[str | None] = mapped_column(String, nullable=True)
    subetapa: Mapped[str | None] = mapped_column(String, nullable=True)
    presencas_celula: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    aceitou_jesus: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    acompanhamento: Mapped[str | None] = mapped_column(String, nullable=True)
    origem: Mapped[str | None] = mapped_column(Text, nullable=True)
    primeiro_contato: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    celula_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("celulas.id", ondelete="SET NULL"), nullable=True
    )
    lider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    consentimento: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    optout: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    apto_proxima_cd: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AppUser(Base):
    """Panel user authenticated via Clerk."""

    __tablename__ = "app_users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    clerk_user_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    # Convite Parte B (delta-049): célula destino guardada até a ativação criar
    # a Pessoa-membro. NULL na Parte A e após a ativação.
    celula_pendente_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("celulas.id", ondelete="SET NULL"), nullable=True
    )
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    igreja: Mapped["Igreja"] = relationship(lazy="joined")


class UserRole(Base):
    """Accumulated roles per user (F3). A user may hold many roles."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "papel", name="user_roles_user_id_papel_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    papel: Mapped[str] = mapped_column(String, nullable=False)

    user: Mapped["AppUser"] = relationship(back_populates="roles")


class RolePermission(Base):
    """Role x screen permission matrix (delta-010)."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "igreja_id", "papel", "tela", name="role_permissions_igreja_id_papel_tela_key"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    papel: Mapped[str] = mapped_column(String, nullable=False)
    tela: Mapped[str] = mapped_column(Text, nullable=False)


class Celula(Base):
    """Cell group."""

    __tablename__ = "celulas"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    lider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    dia_reuniao: Mapped[str | None] = mapped_column(Text, nullable=True)
    cobertura_espiritual: Mapped[str] = mapped_column(Text, nullable=False)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CellAlert(Base):
    """Pastoral alert raised for a person within a cell."""

    __tablename__ = "cell_alerts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    celula_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celulas.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pessoas.id", ondelete="CASCADE"),
        nullable=False,
    )
    gatilho: Mapped[str | None] = mapped_column(Text, nullable=True)
    acao_esperada: Mapped[str | None] = mapped_column(Text, nullable=True)
    tratado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Conversation(Base):
    """WhatsApp conversation thread bound to a person (F6)."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    telefone: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str | None] = mapped_column(String, nullable=True)
    assumido_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    assumido_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultima_mensagem: Mapped[str | None] = mapped_column(Text, nullable=True)
    nao_lidas: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    espera_desde: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    numero_oficial: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Message(Base):
    """Chronological message inside a conversation (F6)."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    direcao: Mapped[str] = mapped_column(String, nullable=False)
    autor: Mapped[str] = mapped_column(String, nullable=False)
    texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WorkQueueItem(Base):
    """Actionable item in the shared work queue (F5)."""

    __tablename__ = "work_queue_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    contexto: Mapped[str | None] = mapped_column(Text, nullable=True)
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    responsavel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    prazo: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    prioridade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Decision(Base):
    """Decision for Jesus (US-37). Inserting fires trg_decision_opens_consolidation."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pessoas.id", ondelete="CASCADE"),
        nullable=False,
    )
    origem: Mapped[str | None] = mapped_column(Text, nullable=True)
    vinculo: Mapped[str] = mapped_column(String, nullable=False)
    celula_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("celulas.id", ondelete="SET NULL"), nullable=True
    )
    responsavel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    prazo_conexao: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Consolidacao(Base):
    """Individual consolidation track for a person (US-38/39, delta-018)."""

    __tablename__ = "consolidacoes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pessoas.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo: Mapped[str | None] = mapped_column(String, nullable=True)
    responsavel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    progresso: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    concluida: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    prazo_conexao: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ConsolidacaoEtapa(Base):
    """Stage of the individual track (delta-018; US-39).

    Stage confirmation is gated by identity: only the consolidacao's
    responsavel_id (the consolidador) may confirm a stage.
    """

    __tablename__ = "consolidacao_etapas"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    consolidacao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consolidacoes.id", ondelete="CASCADE"),
        nullable=False,
    )
    etapa: Mapped[str | None] = mapped_column(Text, nullable=True)
    concluida: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    confirmada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    confirmada_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Multiplicacao(Base):
    """Cell multiplication (enviar — delta-027). Approval gated by supervisao_ok."""

    __tablename__ = "multiplicacoes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    celula_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celulas.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    data_prevista: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    descendencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    novo_lider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    supervisao_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    aprovada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )


class Cron(Base):
    """Scheduled job / state-driven trigger executed by the cron_worker.

    Rows describe recurring jobs (`frequencia`) or state-triggered automations
    (`gatilho_estado`). The cron_worker reads only active rows scoped to the
    igreja and dispatches the configured `acao` (e.g. SLA charge/escalation).
    """

    __tablename__ = "crons"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    frequencia: Mapped[str] = mapped_column(Text, nullable=False)
    gatilho_estado: Mapped[str | None] = mapped_column(Text, nullable=True)
    acao: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class Subscription(Base):
    """Billing subscription (1:1 with igreja). Used for the login billing gate."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    plano: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    pessoas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proxima_cobranca: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    asaas_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    asaas_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup_pago: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class Report(Base):
    """Weekly cell report (RF-37). One row per (celula, semana) when received."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    celula_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celulas.id", ondelete="CASCADE"),
        nullable=False,
    )
    semana: Mapped[str] = mapped_column(Text, nullable=False)
    data_reuniao: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    presentes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visitantes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decisoes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oferta: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    origem: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Broadcast(Base):
    """Segmented broadcast/communication (RF-38). Honors opt-out at send time."""

    __tablename__ = "broadcasts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    segmentos: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    modo: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    hora: Mapped[str | None] = mapped_column(Text, nullable=True)
    repeticao: Mapped[str | None] = mapped_column(String, nullable=True)
    alcance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ignorados_optout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Event(Base):
    """Church event (RF-39). Optionally mirrored to Google Calendar."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hora: Mapped[str | None] = mapped_column(Text, nullable=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WhatsappConnection(Base):
    """Official WhatsApp connection per igreja (1:1, RF-07 / US-05..US-07).

    The UNIQUE constraint on igreja_id enforces a single official number per
    tenant; an attempt to create a second one raises an integrity error mapped
    to a 409 in the router.
    """

    __tablename__ = "whatsapp_connections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    numero: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    instance: Mapped[str | None] = mapped_column(Text, nullable=True)
    ultima_sync: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ConsentRecord(Base):
    """LGPD consent record granted on first inbound message (US-31/RF-36)."""

    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pessoas.id", ondelete="CASCADE"),
        nullable=False,
    )
    termo_versao: Mapped[str | None] = mapped_column(Text, nullable=True)
    aceite_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentConfig(Base):
    """Agent behaviour config per igreja (1:1, US-28). Drives onboarding flow."""

    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    nome: Mapped[str | None] = mapped_column(Text, nullable=True)
    tom: Mapped[str | None] = mapped_column(Text, nullable=True)
    comportamento: Mapped[str] = mapped_column(Text, nullable=False)
    publico_alvo: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    acessos: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class LlmCredential(Base):
    """BYO LLM credential per igreja (1:1, US-27 / RNF-03).

    The API key is stored encrypted (`api_key_encrypted`) and never returned in
    clear text after being saved. The agent only operates while `validado` and
    `ativo` are both true.
    """

    __tablename__ = "llm_credentials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    provedor: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    validado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class AiUsageLog(Base):
    """Per-igreja AI consumption log: model / tokens / cost (F8/RNF-24)."""

    __tablename__ = "ai_usage_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    modelo: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custo: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    ferramenta: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AgentConversationLog(Base):
    """Audit trail of agent/webhook events on a conversation (F8/RNF-24)."""

    __tablename__ = "agent_conversation_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    evento: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Plano(Base):
    """Catálogo de planos do SaaS (preço mensal por porte) — definido pelo master.

    Tabela de REFERÊNCIA GLOBAL (sem igreja_id): o console de plataforma faz o
    CRUD e todos os tenants leem (tela de Assinatura). ``igrejas.plano`` guarda
    o ``codigo`` deste catálogo. Fonte única do preço para MRR/detalhe. Ver
    migration 0012.
    """

    __tablename__ = "planos"

    id: Mapped[uuid.UUID] = _uuid_pk()
    codigo: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    limite_pessoas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preco_mensal: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ordem: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PlatformAdmin(Base):
    """Super-Admin allowlist (console multi-tenant — Onda 1 / US-42/43).

    Platform plane: it has NO igreja_id and is NOT subject to per-tenant RLS.
    A row elevates an app_user to a platform administrator able to manage every
    igreja. See migration 0010 and ``get_platform_admin`` (app/deps.py).
    """

    __tablename__ = "platform_admins"

    id: Mapped[uuid.UUID] = _uuid_pk()
    app_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "Base",
    "Igreja",
    "Pessoa",
    "AppUser",
    "UserRole",
    "RolePermission",
    "Celula",
    "CellAlert",
    "Conversation",
    "Message",
    "WorkQueueItem",
    "Decision",
    "Consolidacao",
    "ConsolidacaoEtapa",
    "Multiplicacao",
    "Cron",
    "Subscription",
    "Report",
    "Broadcast",
    "Event",
    "WhatsappConnection",
    "ConsentRecord",
    "AgentConfig",
    "LlmCredential",
    "AiUsageLog",
    "AgentConversationLog",
    "Plano",
    "PlatformAdmin",
]

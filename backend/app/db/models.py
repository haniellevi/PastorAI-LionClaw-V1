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
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
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
    # Valor excepcional de setup definido pelo master para esta igreja. NULL
    # significa usar a taxa padrão global de cobrança.
    setup_fee_override: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    # #4: dono (admin principal) — único admin que enxerga/gerencia a Assinatura.
    # FK -> app_users (definido adiante); SET NULL no delete. NULL = sem dono.
    dono_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Missão 4 (branding): path da logo no bucket público church-logos.
    # NULL = sem logo (a UI mostra o nome da igreja como fallback).
    logo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Pessoa(Base):
    """Unified person model (F2/F6/F7)."""

    __tablename__ = "pessoas"
    __table_args__ = (
        # UNIQ-PESSOA-1: no máximo UMA pessoa ATIVA por (igreja_id, telefone).
        # Fecha o TOCTOU do "procura-antes-de-criar" nos três pontos que criam
        # Pessoa por telefone (queue_worker inbound, POST /contacts, ativação de
        # convite): duas criações concorrentes do MESMO telefone/tenant não se
        # veem e ambas inserem → duplicata. Índice único PARCIAL serializa: uma
        # vence, a outra recebe unique_violation, e app/services/pessoa_dedup.py
        # (savepoint) re-busca a vencedora e segue com ela. Parcial sobre
        # `arquivada_em IS NULL` — arquivada não bloqueia recriar ativa (não há
        # hard delete de Pessoa). Telefone BRUTO (não o sufixo da dedupe): o
        # sufixo é ambíguo entre números distintos de DDDs diferentes; a
        # unicidade canônica fica na dedupe da aplicação. Índice em
        # __table_args__ + migration idênticos (padrão CONSOL-1 / SEC-4B).
        Index(
            "uq_pessoas_telefone_ativa",
            "igreja_id",
            "telefone",
            unique=True,
            postgresql_where=text("arquivada_em IS NULL"),
        ),
    )

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
    # Apto a liderar célula (realizou o Reencontro). Liderança efetiva é
    # DERIVADA de celulas.lider_id em célula ativa — nunca de pessoas.tipo.
    apto_lider: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # CSIM (#1): contato sem interesse ministerial — fica fora do funil pastoral.
    sem_interesse: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    sem_interesse_motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Arquivamento (W3): NULL = pessoa ativa. Não há hard delete de Pessoa.
    arquivada_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    arquivada_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    arquivada_motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Nome de exibição no chat do WhatsApp (assinatura). NULL = usa `nome`.
    chat_nome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # SEC-3A / MEDIO-002: carimbo da última troca/reset de senha. NULL = nunca
    # marcado (sessões antigas seguem válidas — sem logout em massa no deploy).
    # Preenchido, invalida todo JWT de sessão com `iat` anterior a este valor.
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    # foreign_keys explícito: igrejas.dono_id (#4) cria um 2º caminho de FK entre
    # app_users e igrejas; sem isto o relationship fica ambíguo.
    igreja: Mapped["Igreja"] = relationship(
        lazy="joined", foreign_keys="AppUser.igreja_id"
    )


class PasswordResetToken(Base):
    """Um registro por link de "esqueci a senha" emitido (SEC-3B / MEDIO-003).

    Guarda o `jti` (não o token/JWT em si) + prazo + carimbo de uso, pra
    impedir que o mesmo link seja resgatado duas vezes — ver
    app/routers/auth.py::reset_password. Sem igreja_id: artefato de auth
    pré-login, não dado de tenant.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    clerk_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


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
    # Sensíveis (Células PR1, decisão 3.2): só a Central (pastor/admin) altera;
    # o líder solicita alteração (fluxo de Solicitação chega no PR5). dia_reuniao
    # e horario também são sensíveis.
    anfitriao_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    auxiliar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    endereco: Mapped[str | None] = mapped_column(Text, nullable=True)
    horario: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Leves: o líder edita direto.
    link_grupo: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_localizacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    mensagem_convite: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CelulaMembro(Base):
    """Vínculo canônico pessoa<->célula (Células PR1).

    Fonte de verdade da participação (Q1); `pessoas.celula_id` fica como espelho
    legado. `papel` é o rótulo do vínculo — anfitrião/auxiliar "de verdade" da
    célula são as FKs sensíveis em `Celula` (Q2).
    """

    __tablename__ = "celula_membro"

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
    papel: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'membro'")
    )
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaReuniao(Base):
    """Ocorrência materializada de uma célula (Células PR2).

    Uma reunião = um encontro da célula numa data/hora. `igreja_id` é próprio
    (a RLS não herda por FK) e a tabela tem policy tenant_isolation dedicada.
    `updated_at` é gerenciado pela aplicação (sem trigger).

    ⚠️ DB-DEC-04: `celula_id` é ON DELETE CASCADE — se um dia existir um
    DELETE /cells (hoje INEXISTENTE), apagar a célula apagaria em cadeia as
    reuniões e, por consequência, suas presenças (`celula_presenca`) e
    expectativas de visitante (`celula_expectativa_visitante`), que também são
    CASCADE a partir de `reuniao_id`.
    """

    __tablename__ = "celula_reuniao"

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
    data: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hora: Mapped[str | None] = mapped_column(Text, nullable=True)
    tema: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'planejada'")
    )
    # Ciclo do relatório da reunião (Células PR3-PR9). relatorio_status nasce
    # 'pendente' e vira 'enviado' no submit; relatorio_enviado_por é FK de autor
    # (SET NULL). oferta/observações compõem o relatório consolidado.
    relatorio_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pendente'")
    )
    relatorio_enviado_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    relatorio_enviado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    oferta_valor: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Congelamento E10/E11: no submit, o relatório é materializado num snapshot
    # imutável (presenças/visitantes/registros/oferta/observações). Depois de
    # enviado, get_report lê o snapshot — não `celula_presenca` ao vivo — de modo
    # que o endpoint PR2 de presença (upsert sempre-200) não altere o consolidado.
    relatorio_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaPresenca(Base):
    """Presença de uma pessoa numa reunião de célula (Células PR2).

    `estado` ∈ {confirmada, compareceu, ausente}. UNIQUE por (igreja_id,
    reuniao_id, pessoa_id) — uma linha por pessoa/reunião. `igreja_id` próprio +
    RLS própria. `reuniao_id`/`pessoa_id` ON DELETE CASCADE (DB-DEC-04).
    `updated_at` gerenciado pela aplicação.
    """

    __tablename__ = "celula_presenca"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    reuniao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_reuniao.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pessoas.id", ondelete="CASCADE"),
        nullable=False,
    )
    estado: Mapped[str] = mapped_column(String, nullable=False)
    origem: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaExpectativaVisitante(Base):
    """Visitante esperado por um membro para uma reunião de célula (Células PR2).

    SEM UNIQUE: a mesma pessoa pode esperar vários visitantes na mesma reunião
    (uma linha por visitante). `igreja_id` próprio + RLS própria.
    `reuniao_id`/`pessoa_id` ON DELETE CASCADE (DB-DEC-04). `updated_at`
    gerenciado pela aplicação.
    """

    __tablename__ = "celula_expectativa_visitante"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    reuniao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_reuniao.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pessoas.id", ondelete="CASCADE"),
        nullable=False,
    )
    nome_visitante: Mapped[str] = mapped_column(Text, nullable=False)
    observacao_oracao: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaReuniaoRegistro(Base):
    """Registro pastoral de uma reunião de célula (Células PR3-PR9).

    `tipo` ∈ {decisao, oracao, observacao}; `conteudo` é o texto livre. Oculto do
    discípulo (só líder/Central leem — regra na aplicação). `igreja_id` próprio +
    RLS própria. `reuniao_id` ON DELETE CASCADE; `autor_id` ON DELETE SET NULL
    (FK de autor). `updated_at` gerenciado pela aplicação.
    """

    __tablename__ = "celula_reuniao_registro"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    reuniao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_reuniao.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    conteudo: Mapped[str] = mapped_column(Text, nullable=False)
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    autor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaVisitante(Base):
    """Visitante presente numa reunião de célula (Células PR3-PR9).

    Pode referenciar a expectativa que o antecedeu (`expectativa_id`, opcional).
    SEM UNIQUE. `igreja_id` próprio + RLS própria. `reuniao_id` ON DELETE CASCADE;
    `expectativa_id` ON DELETE SET NULL (link opcional — apagar a expectativa não
    apaga o comparecimento real). `updated_at` gerenciado pela aplicação.
    """

    __tablename__ = "celula_visitante"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    reuniao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_reuniao.id", ondelete="CASCADE"),
        nullable=False,
    )
    expectativa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_expectativa_visitante.id", ondelete="SET NULL"),
        nullable=True,
    )
    nome_visitante: Mapped[str] = mapped_column(Text, nullable=False)
    telefone: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaSolicitacao(Base):
    """Solicitação de alteração sensível / multiplicação (Células PR3-PR9).

    Extensível por `tipo` (alterar_dia/horario/endereco/anfitriao/auxiliar,
    transferir_membro, remover_membro, multiplicacao), com `payload_proposto`
    JSONB tipado validado na aplicação. `status` ∈ {aguardando, aprovada,
    rejeitada, ajuste_solicitado, cancelada}. A Central NÃO edita o payload (3.6).

    `igreja_id` próprio + RLS própria. `celula_id` ON DELETE CASCADE;
    `solicitante_id`/`pessoa_id`/`decidido_por` ON DELETE SET NULL (FKs de
    autor/pessoa). `updated_at` gerenciado pela aplicação.
    """

    __tablename__ = "celula_solicitacao"

    # SEC-4B / E13 (SPEC §6.8): no máximo UMA solicitação ABERTA conflitante por
    # célula. Fecha o TOCTOU check→insert da criação — o pré-check em
    # cell_requests.py é só o caminho rápido; estes índices únicos PARCIAIS são a
    # garantia real (duas criações concorrentes serializam no índice: uma vence, a
    # outra recebe unique_violation, que o router traduz para 409). Statuses
    # terminais (aprovada/rejeitada/cancelada) SAEM do índice → histórico
    # preservado e uma nova solicitação pode abrir depois da decisão.
    #
    # Partição por pessoa_id (invariante: pessoa_id IS NOT NULL ⟺ tipo de membro):
    #   - NULL  → tipos sensíveis / multiplicação; a chave é (igreja, célula, tipo);
    #   - !NULL → transferir/remover; a chave é (igreja, célula, pessoa), SEM o
    #     tipo, pois transferir e remover a MESMA pessoa colidem entre si (E13).
    # Escopo sempre por igreja_id ⇒ igrejas diferentes nunca colidem (multi-tenant).
    __table_args__ = (
        Index(
            "uq_celula_solicitacao_aberta_tipo",
            "igreja_id",
            "celula_id",
            "tipo",
            unique=True,
            postgresql_where=text(
                "status IN ('aguardando', 'ajuste_solicitado') "
                "AND pessoa_id IS NULL"
            ),
        ),
        Index(
            "uq_celula_solicitacao_aberta_membro",
            "igreja_id",
            "celula_id",
            "pessoa_id",
            unique=True,
            postgresql_where=text(
                "status IN ('aguardando', 'ajuste_solicitado') "
                "AND pessoa_id IS NOT NULL"
            ),
        ),
    )

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
    solicitante_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'aguardando'")
    )
    payload_proposto: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    payload_atual: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacao_central: Mapped[str | None] = mapped_column(Text, nullable=True)
    decidido_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    decidido_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaSolicitacaoEvento(Base):
    """Trilha de auditoria APPEND-ONLY das transições de uma solicitação.

    Blindada no banco pelo trigger `trg_celula_solicitacao_evento_append_only`
    (UPDATE/DELETE levantam exceção). `acao` ∈ {criada, reenviada, aprovada,
    rejeitada, ajuste_solicitado, cancelada}. `payload_snapshot` guarda a foto do
    payload no momento da transição. SEM `updated_at` (append-only:
    cada transição é uma linha imutável). `igreja_id` próprio + RLS própria.
    `solicitacao_id` ON DELETE CASCADE; `autor_id` ON DELETE SET NULL.
    """

    __tablename__ = "celula_solicitacao_evento"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    solicitacao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_solicitacao.id", ondelete="CASCADE"),
        nullable=False,
    )
    acao: Mapped[str] = mapped_column(String, nullable=False)
    autor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    payload_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    de_status: Mapped[str | None] = mapped_column(String, nullable=True)
    para_status: Mapped[str | None] = mapped_column(String, nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CelulaAviso(Base):
    """Aviso da célula (origem=celula) ou da Central (origem=central).

    `escopo` ∈ {celula, igreja}; `celula_id` é NULL quando escopo='igreja'.
    `ativo=false` = inativado (sem edição no MVP). `notificado_em` é o ponto de
    extensão do disparo (cell_notify.py no-op). `igreja_id` próprio + RLS própria.
    `celula_id` ON DELETE CASCADE; `autor_id` ON DELETE SET NULL. `updated_at`
    gerenciado pela aplicação.
    """

    __tablename__ = "celula_aviso"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    celula_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("celulas.id", ondelete="CASCADE"), nullable=True
    )
    autor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    origem: Mapped[str] = mapped_column(String, nullable=False)
    escopo: Mapped[str] = mapped_column(String, nullable=False)
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    conteudo: Mapped[str] = mapped_column(Text, nullable=False)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    publicado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    notificado_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CelulaMaterial(Base):
    """Material de apoio publicado pela Central (Células PR3-PR9).

    Link/metadados (sem upload real de arquivo); líder e discípulo veem em
    leitura (E14). `ativo=false` = inativado. `igreja_id` próprio + RLS própria.
    `autor_id` ON DELETE SET NULL. `updated_at` gerenciado pela aplicação.
    """

    __tablename__ = "celula_material"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    autor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    publicado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    # MSG-IDEMP-1: defesa em profundidade contra duplicação de mensagem INBOUND.
    # Redis (WebhookQueue.mark_processed_if_new) é a primeira barreira, chaveada
    # pelo id estável da Evolution, mas expira em 7 dias e não sobrevive a um
    # Redis indisponível/flush. Este índice único PARCIAL garante que o MESMO
    # provider_message_id nunca persiste duas vezes como inbound na mesma
    # igreja, mesmo que o Redis diga "novo" de novo. Outbound (direcao='out')
    # fica fora do escopo — não carrega a mesma garantia de dedupe hoje.
    __table_args__ = (
        Index(
            "messages_inbound_provider_id_uidx",
            "igreja_id",
            "provider_message_id",
            unique=True,
            postgresql_where=text(
                "direcao = 'in' AND provider_message_id IS NOT NULL"
            ),
        ),
    )

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
    # Id estável do provider (Evolution `data.key.id` / ParsedMessage.
    # provider_message_id). Só populado para mensagens vindas do webhook
    # (in/out); histórico anterior a esta migration fica NULL. Ver
    # messages_inbound_provider_id_uidx acima.
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mídia (Etapa 2 do chat): o binário vive no Supabase Storage (bucket
    # whatsapp-media); aqui guardamos só o ponteiro + metadados. tipo='texto'
    # para mensagens de texto puro (default).
    tipo: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'texto'")
    )
    media_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_nome: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_tamanho: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Autoria (Parte A do chat): quem enviou a resposta humana. autor_nome é o
    # snapshot do nome exibido no envio; enviado_por é o app_user (auditoria).
    autor_nome: Mapped[str | None] = mapped_column(Text, nullable=True)
    enviado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
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
    __table_args__ = (
        # W3.2A: uma consolidação não pode estar concluída E abandonada ao
        # mesmo tempo — mutuamente exclusivos (revisão externa PR#163).
        CheckConstraint(
            "not (concluida = true and abandonada_em is not null)",
            name="consolidacoes_concluida_abandonada_excl_chk",
        ),
        # CONSOL-1: no máximo UMA consolidação ABERTA por pessoa. Fecha o TOCTOU
        # do INSERT feito por fn_decision_opens_consolidation (trigger, AFTER
        # INSERT em decisions) — duas decisões concorrentes para a mesma pessoa
        # disparam o trigger nas duas transações, sem linha a travar antes do
        # INSERT. Índice único PARCIAL serializa: uma vence, a outra recebe
        # unique_violation, que o router/tool traduzem para 409/ToolError.
        # "Aberta" = concluida=false AND abandonada_em IS NULL (mesma definição
        # do check acima); concluída/abandonada saem do índice e liberam nova
        # consolidação. Índice em __table_args__ + migration idênticos (padrão
        # SEC-4B/E13).
        Index(
            "uq_consolidacoes_pessoa_aberta",
            "pessoa_id",
            unique=True,
            postgresql_where=text("concluida = false AND abandonada_em IS NULL"),
        ),
    )

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
    # W3.2A: encerramento "abandonada" — única exceção automática do
    # arquivamento de Pessoa (ver pessoa_offboarding_service). NULL = não
    # abandonada; independente de `concluida`. Sem status/enum no domínio
    # anterior — este par nullable espelha pessoas.arquivada_em/motivo.
    abandonada_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    abandonada_motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    """Cell multiplication (enviar — delta-027). Approval gated by supervisao_ok.

    Células PR3-PR9: evoluído (não recriado) para a multiplicação transacional e
    idempotente. `celula_id` PERMANECE como a célula de ORIGEM (não renomear).
    Colunas aditivas: `solicitacao_id` (1:1 com a solicitação aprovada, NOT NULL
    UNIQUE, ON DELETE CASCADE), `idempotency_key` (barra reprocesso — índice único
    parcial where not null), `celula_nova_id` (célula gerada, ON DELETE SET NULL)
    e timestamps. `updated_at` gerenciado pela aplicação.
    """

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
    # Células PR3-PR9 — evolução aditiva (celula_id continua sendo a origem).
    solicitacao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("celula_solicitacao.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    celula_nova_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("celulas.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    # Pagamento avulso da taxa de setup. O webhook usa este id para não
    # confundir a confirmação mensal com a confirmação do setup.
    asaas_setup_charge_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Links públicos de pagamento devolvidos pelo Asaas no checkout. Persistidos
    # para a tela de Assinatura sobreviver a reload sem recriar cobranças.
    asaas_invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    asaas_setup_invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ID Asaas da cobrança mensal do CICLO CORRENTE — atualizado a cada webhook
    # de fatura, para o link nunca apontar para uma mensalidade já quitada.
    asaas_invoice_payment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Motivo da reversão da cobrança mensal corrente ('deleted'|'refunded',
    # NULL = sem reversão): o link dela é inutilizável e o recovery não deve
    # reapresentá-lo. 'deleted' permite restaurar a MESMA cobrança no Asaas;
    # 'refunded' exige cobrança avulsa de recuperação. Ciclo novo válido limpa.
    asaas_invoice_reversal: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup_pago: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class BillingPaymentOperation(Base):
    """Operação durável de cobrança avulsa (setup / recuperação de mensalidade).

    A ``operation_key`` é persistida ANTES do POST /payments e vira a
    externalReference exclusiva da cobrança no Asaas: um retry reconcilia pela
    chave (GET /payments?externalReference=...) em vez de repetir o POST às
    cegas — resposta perdida nunca duplica cobrança. O índice único parcial
    (subscription_id, purpose) sobre estados abertos faz o claim atômico entre
    requests concorrentes.
    """

    __tablename__ = "billing_payment_operations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)  # setup | monthly_recovery
    operation_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Cobrança original revertida que motivou esta operação (quando houver).
    source_payment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    asaas_payment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # prepared | creating | reconciling | created | paid | reversed | failed
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'prepared'")
    )
    valor: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Registro da rejeição DEFINITIVA que fechou a operação como `failed`.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BillingPlanChangeOperation(Base):
    """Troca de plano durável: PUT na assinatura Asaas EXISTENTE.

    Decisão de produto (PLAN-CHANGE-SAFETY-1): nunca criar segunda recorrência;
    vigência no próximo ciclo; cobranças já emitidas intocadas
    (updatePendingPayments=false). O alvo (plano/preço/limite) é CONGELADO na
    solicitação e persistido antes do PUT — retry reconcilia pelo GET da
    assinatura, nunca repete o PUT às cegas. ``origin='autoupgrade'`` reserva o
    mesmo trilho para o gatilho de porte quando existir worker de billing.
    """

    __tablename__ = "billing_plan_change_operations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    asaas_subscription_id: Mapped[str] = mapped_column(Text, nullable=False)
    from_plano: Mapped[str] = mapped_column(Text, nullable=False)
    to_plano: Mapped[str] = mapped_column(Text, nullable=False)
    to_preco: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    to_limite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual'")
    )
    # prepared | processing | reconciling | completed | failed
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'prepared'")
    )
    # pending | sent | skipped — separa a conclusão FINANCEIRA da entrega da
    # notificação de upgrade: 'pending' fica descobrível pelo cron-worker até
    # o envio; operações manuais nascem 'skipped'.
    notify_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'skipped'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BillingSubscriptionOperation(Base):
    """Intenção durável de criação da assinatura recorrente (CORRECTIVE-6).

    Persistida ANTES do POST /subscriptions; a ``operation_key`` vira a
    ``externalReference`` da assinatura. A externalReference NÃO é garantia de
    idempotência do POST — serve para LOCALIZAR e reconciliar: resposta
    perdida marca ``reconciling`` e o retry adota somente uma assinatura cujo
    customer/valor/ciclo/descrição batam com o alvo congelado. Nunca há
    segundo POST automático.
    """

    __tablename__ = "billing_subscription_operations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Persistido assim que o customer é resolvido — ANTES do POST da assinatura.
    customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    plano: Mapped[str] = mapped_column(Text, nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    ciclo: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'MONTHLY'")
    )
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    asaas_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # prepared | creating | reconciling | created | failed
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'prepared'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
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
    """Church event (RF-39 / Agenda de Eventos).

    Optionally mirrored to Google Calendar. The EVT-1 columns (status, tipo,
    origem, recorrencia + confirmation/communication fields) back the Agenda
    MVP; enums are kept as plain strings (the DB enforces the types). `data` is
    nullable so weekly-recurring events (recorrencia='semanal') can live without
    a specific date. See docs/design/AGENDA-EVENTOS-EVT0-decisao.md.
    """

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    hora: Mapped[str | None] = mapped_column(Text, nullable=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # EVT-1 — Agenda de Eventos (enums mapeados como string, DB enforça o tipo).
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'confirmado'")
    )
    tipo: Mapped[str | None] = mapped_column(String, nullable=True)
    origem: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'manual'")
    )
    recorrencia: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pontual'")
    )
    dia_semana: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publico_alvo: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    antecedencia_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mensagem_confirmacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    # EVT-8 PR1 — configuração de notificação do PRÓPRIO evento (captura da
    # intenção; o envio real é EVT-9, atrás de flag). `notificar_em`: instante
    # normalizado do disparo (D4) — derivado de `antecedencia_horas` + hora do
    # evento OU de uma data/hora específica; fonte única do futuro cron.
    # `notificacao_enviada_em`: idempotência do envio agendado — NULL com
    # `notificar_em` preenchido = pendente/futuro; NADA é enviado neste PR.
    # `canal`: WhatsApp no MVP (D6). Ver AGENDA-EVENTOS-EVT8-notificacao-evento.md.
    notificar_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notificacao_enviada_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canal: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmado_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # EVT-7 PR1 — carimbo de idempotência do aviso interno de confirmação (atrás
    # da flag AGENDA_NOTIFY_ENABLED). NULL = ainda não avisado; preenchido = aviso
    # já despachado, não reenvia. Ver app/services/event_notify.py.
    notificado_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EventNotifyTarget(Base):
    """Contato individual a notificar de um evento (EVT-8 PR1, D3).

    A seleção individual da notificação do próprio evento vem de contatos que já
    conversaram no WhatsApp da igreja (``conversations``) — nunca digitação livre
    de telefone. Preferimos ``pessoa_id`` quando a conversa tem pessoa vinculada;
    sem pessoa, guardamos o ``telefone`` (chave canônica só-dígitos, normalize_phone).
    ``igreja_id`` replica o tenant para a RLS. O envio real é EVT-9; aqui só se
    persiste a intenção. Ver docs/design/AGENDA-EVENTOS-EVT8-notificacao-evento.md.
    """

    __tablename__ = "event_notify_targets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True
    )
    telefone: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CalendarSync(Base):
    """Per-igreja Google Calendar connection + sync state (events module F1).

    Holds the OAuth refresh/access tokens (encrypted at rest) and the chosen
    calendar id. Sync-token/watch-channel columns are added in later phases.
    """

    __tablename__ = "calendar_sync"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    google_calendar_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expira_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    criado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    atualizado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AgendaAlertRecipient(Base):
    """Destinatário de avisos internos da Agenda por igreja (EVT-7 PR2).

    Config explícita, opt-in, de quem recebe os avisos da Agenda por WhatsApp —
    independente de papel e de ``AppUser.pessoa_id`` (mata a "dupla exclusão" que
    zerava os destinatários; ver docs/design/AGENDA-EVENTOS-EVT7-destinatarios-alerta.md).
    ``telefone`` é a chave canônica só-dígitos (normalize_phone), como em
    ``conversations.telefone``. Só destinatários ``ativo`` recebem.
    """

    __tablename__ = "agenda_alert_recipients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    telefone: Mapped[str] = mapped_column(Text, nullable=False)
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class PessoaArquivamentoEvento(Base):
    """Trilha de auditoria APPEND-ONLY do arquivamento/reativação de Pessoa (W3.2A).

    Blindada no banco pelo trigger `trg_pessoa_arquivamento_evento_append_only`
    (UPDATE/DELETE diretos levantam exceção). `acao` ∈ {arquivada, reativada} —
    "reativada" é headroom de schema para PR futuro (reativação administrativa
    não implementada aqui). NÃO é `platform_audit_log`: aquela é do plano de
    plataforma (sem igreja_id, sem RLS de tenant); esta é tenant-aware, mesmo
    padrão de `celula_solicitacao_evento`. `igreja_id`/`pessoa_id` ON DELETE
    CASCADE (estrutural — Pessoa nunca é hard-deletada na prática); `ator_id`
    (app_user que executou a ação) ON DELETE SET NULL. Sem `updated_at`
    (append-only: cada evento é uma linha imutável).
    """

    __tablename__ = "pessoa_arquivamento_evento"

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
    ator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acao: Mapped[str] = mapped_column(String, nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
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
    # App_user que registrou o consentimento quando a origem é ação
    # administrativa (ex.: reoptin do FECH-05). NULL = fluxo automático
    # (consent inbound, optout do agente) e legado. ON DELETE SET NULL: apagar
    # o app_user não apaga nem trava a trilha de consentimento (migration
    # 20260720_191143, espelho de pessoa_arquivamento_evento.ator_id).
    ator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
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


class AgentConfigRequest(Base):
    """Requisição admin → master para mudar o agente (#10b Fase 1 / delta-043).

    O admin da igreja não edita o comportamento (só o master); aqui ele SOLICITA
    mudanças por mensagem livre. O master lê no console, ajusta a config pelo
    editor existente e RESOLVE (``atendida``/``recusada`` + ``resposta``). Tenant
    (RLS por igreja_id); o master acessa cross-tenant via BYPASSRLS.
    """

    __tablename__ = "agent_config_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("igrejas.id", ondelete="CASCADE"),
        nullable=False,
    )
    solicitante_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pendente'")
    )
    resposta: Mapped[str | None] = mapped_column(Text, nullable=True)
    # platform_admin (app_user) que resolveu — sem FK (rastro imutável).
    resolvido_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    criado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolvido_em: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class BillingSettings(Base):
    """Configuração global de cobrança definida pelo console master.

    Há uma única linha (``id=1``). ``setup_fee_default`` nulo mantém o valor
    legado de ambiente até o master salvar a taxa no painel.
    """

    __tablename__ = "billing_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_fee_default: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PlatformAuditLog(Base):
    """Log de auditoria das ações cross-tenant do console master (M3).

    Plano de plataforma (sem igreja_id). Histórico imutável: ``actor_id`` e
    ``alvo_id`` NÃO têm FK de propósito, para o rastro sobreviver à exclusão da
    igreja/usuário. Ver migration 0013 e ``_audit`` (routers/platform_admin.py).
    """

    __tablename__ = "platform_audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    actor_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    acao: Mapped[str] = mapped_column(Text, nullable=False)
    alvo_tipo: Mapped[str] = mapped_column(Text, nullable=False)
    alvo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    alvo_nome: Mapped[str | None] = mapped_column(Text, nullable=True)
    detalhe: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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


class PlatformOrchestrator(Base):
    """Modelo padrão do orquestrador (1 linha), definido pelo master.

    Padrão TEMPLATE: o master define um comportamento base e, ao aprovar uma
    igreja, ele é COPIADO para o ``AgentConfig`` dela (por igreja). O runtime do
    agente NÃO muda — segue lendo o AgentConfig por igreja. Plano de plataforma
    (sem igreja_id), só service role. Ver migration 0014.
    """

    __tablename__ = "platform_orchestrator"

    id: Mapped[uuid.UUID] = _uuid_pk()
    nome: Mapped[str | None] = mapped_column(Text, nullable=True)
    tom: Mapped[str | None] = mapped_column(Text, nullable=True)
    comportamento: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
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
    "CelulaMembro",
    "CelulaReuniao",
    "CelulaPresenca",
    "CelulaExpectativaVisitante",
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
    "PlatformAuditLog",
    "PlatformOrchestrator",
]

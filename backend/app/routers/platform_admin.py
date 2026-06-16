"""Platform admin router — console Super-Admin (Onda 1 / US-42/43, RF-48/49).

Cross-tenant administration of churches by the SaaS provider. Every endpoint is
gated by ``get_platform_admin`` (the ``platform_admins`` allowlist) and runs
OUTSIDE the per-tenant RLS context: the session keeps the connection role
(BYPASSRLS), so a platform admin can see and manage every igreja — the whole
point of the platform plane. Mounted under ``/admin``.

Scope of this slice (manual provisioning — US-43 minus self-service):
  - GET   /admin/igrejas           list every church (+ size counters)
  - POST  /admin/igrejas           create a church and invite its first admin
  - PATCH /admin/igrejas/{id}      change a church's status and/or plano

This surface is intentionally separate from the per-tenant panel (PRD L36/L203/
L286): the tenant sidebar is built from the per-igreja role_permissions matrix
and must never expose cross-tenant data.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AiUsageLog,
    AppUser,
    Celula,
    Igreja,
    Pessoa,
    Plano,
    PlatformAdmin,
    PlatformAuditLog,
    RolePermission,
    Subscription,
    UserRole,
)
from app.db.session import get_db
from app.deps import PlatformAdminUser, get_platform_admin
from app.domain.permissions import DEFAULT_PERMISSIONS
from app.services.brevo import BrevoClient, BrevoError, get_brevo_client
from app.services.clerk import ClerkAuthError, ClerkClient, get_clerk_client

logger = logging.getLogger("pastorai.platform_admin")

router = APIRouter(prefix="/admin", tags=["platform-admin"])

# Status válidos de igreja (enum igreja_status — migration 0001).
IGREJA_STATUSES = {"ativa", "suspensa", "aguardando_aprovacao", "inadimplente"}


# Catálogo de planos (preço por plano) agora vive na tabela `planos` (migration
# 0012), editável pelo master. Estes helpers são a fonte única do preço para
# MRR, detalhe da igreja e validação de plano nas igrejas.
def _plano_precos(db: Session) -> dict[str, float]:
    """Mapa ``codigo -> preço mensal`` de TODOS os planos.

    Inclui planos inativos de propósito: uma igreja ATIVA grandfathered num
    plano que o master desativou continua pagando o preço dele, então ainda
    conta no MRR. O setup único (R$1.000) é one-time e não entra aqui.
    """
    rows = db.execute(select(Plano.codigo, Plano.preco_mensal)).all()
    return {codigo: float(preco) for codigo, preco in rows}


def _validate_plano_or_422(db: Session, codigo: str) -> None:
    """Garante que o código de plano existe no catálogo (senão 422).

    A UI só oferece planos ativos no seletor; aqui basta existir (a igreja pode
    permanecer num plano depois desativado — grandfathering).
    """
    if codigo not in _plano_precos(db):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"plano inválido: {codigo}",
        )


def _as_uuid(value: object) -> uuid.UUID | None:
    """Coage para UUID (str/UUID); None se inválido — o audit nunca quebra a ação."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _audit(
    db: Session,
    admin: PlatformAdminUser,
    acao: str,
    alvo_tipo: str,
    alvo_id: object,
    alvo_nome: str | None,
    detalhe: dict | None = None,
) -> None:
    """Registra uma ação do console no log de auditoria (M3).

    Adiciona a linha à sessão — o caller faz o commit JUNTO com a mutação, então
    o rastro é atômico com a ação. Nunca lança (o audit não pode derrubar a ação).
    """
    db.add(
        PlatformAuditLog(
            actor_id=_as_uuid(admin.app_user_id),
            actor_email=getattr(admin, "email", None),
            acao=acao,
            alvo_tipo=alvo_tipo,
            alvo_id=_as_uuid(alvo_id),
            alvo_nome=alvo_nome,
            detalhe=detalhe,
        )
    )


# ---------------------------------------------------------------------------
# Login dedicado do console (isento do gate de billing do tenant)
# ---------------------------------------------------------------------------
# Mensagem única para QUALQUER falha (credencial inválida OU conta sem acesso de
# plataforma): não revela se o e-mail existe nem se a conta é master.
_LOGIN_DENIED = "E-mail ou senha inválidos, ou acesso de plataforma não autorizado"


class AdminLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class AdminLoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(
    payload: AdminLoginRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> AdminLoginResponse:
    """Login do console master — NÃO aplica o gate de billing do tenant.

    Diferente de POST /auth/login, este caminho ignora o status da igreja: o
    provedor precisa entrar no console mesmo que a própria igreja-casa esteja
    suspensa/inadimplente (senão não conseguiria reativar ninguém). Autentica a
    credencial no Clerk, resolve o app_user SEM tenant context (cross-tenant) e
    exige uma linha em ``platform_admins``. Qualquer falha — credencial inválida
    OU conta sem acesso de plataforma — retorna o MESMO 401 genérico.
    """
    denied = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_LOGIN_DENIED,
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token, clerk_user_id = clerk.authenticate_password(
            payload.email, payload.password
        )
    except ClerkAuthError:
        raise denied from None

    # Sem set_tenant_context: resolve cross-tenant, igual ao gate de plataforma.
    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)
    ).scalar_one_or_none()
    if app_user is None:
        raise denied

    is_admin = db.execute(
        select(PlatformAdmin.id).where(PlatformAdmin.app_user_id == app_user.id)
    ).scalar_one_or_none()
    if is_admin is None:
        raise denied

    return AdminLoginResponse(token=token)


class IgrejaOut(BaseModel):
    """A church as seen by the platform console (with size counters)."""

    id: str
    nome: str
    status: str
    plano: str | None = None
    membros: int = 0
    pessoas: int = 0
    createdAt: str | None = None  # noqa: N815 - external contract is camelCase


class AdminSeed(BaseModel):
    """First administrator to provision alongside a new church."""

    nome: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome obrigatório")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("e-mail inválido")
        return v


class CreateIgrejaRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    plano: str | None = Field(default=None)
    admin: AdminSeed

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome obrigatório")
        return v

    @field_validator("plano")
    @classmethod
    def _plano(cls, v: str | None) -> str | None:
        # Só normaliza; a existência no catálogo é checada no handler (precisa
        # do banco — ver _validate_plano_or_422).
        if v is None:
            return None
        return v.strip() or None


class CreateIgrejaResponse(BaseModel):
    igrejaId: str  # noqa: N815
    adminUsuarioId: str  # noqa: N815
    emailEnviado: bool  # noqa: N815


class UpdateIgrejaRequest(BaseModel):
    status: str | None = Field(default=None)
    plano: str | None = Field(default=None)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in IGREJA_STATUSES:
            raise ValueError(f"status inválido: {v}")
        return v

    @field_validator("plano")
    @classmethod
    def _plano(cls, v: str | None) -> str | None:
        # Só normaliza; a existência no catálogo é checada no handler.
        if v is None:
            return None
        return v.strip() or None


class PlatformAdminMe(BaseModel):
    """Identity of the current platform admin (drives the console gate)."""

    appUserId: str  # noqa: N815
    email: str
    nome: str


def _activation_link(app_user_id: uuid.UUID, clerk: ClerkClient) -> str:
    """Activation link for the new church's first admin (tenant panel).

    Token de convite assinado (expira em 7 dias) — não o id cru.
    """
    token = clerk.mint_invite_token(str(app_user_id))
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/#ativar/{token}"


@router.get("/me", response_model=PlatformAdminMe)
def admin_me(
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> PlatformAdminMe:
    """Confirm the caller is a platform admin and return its identity.

    The console calls this right after login to decide whether to render the
    cross-tenant surface (200) or refuse (the gate returns 403 otherwise).
    """
    return PlatformAdminMe(
        appUserId=admin.app_user_id, email=admin.email, nome=admin.nome
    )


@router.get("/igrejas", response_model=list[IgrejaOut])
def list_igrejas(
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> list[IgrejaOut]:
    """List every church with size counters (cross-tenant).

    Runs without tenant context (BYPASSRLS via the connection role), so it sees
    all igrejas. Counters are aggregated in two grouped queries to avoid an N+1.
    """
    igrejas = db.execute(
        select(Igreja).order_by(Igreja.created_at.desc())
    ).scalars().all()

    membros_por = dict(
        db.execute(
            select(AppUser.igreja_id, func.count()).group_by(AppUser.igreja_id)
        ).all()
    )
    pessoas_por = dict(
        db.execute(
            select(Pessoa.igreja_id, func.count()).group_by(Pessoa.igreja_id)
        ).all()
    )

    return [
        IgrejaOut(
            id=str(ig.id),
            nome=ig.nome,
            status=ig.status,
            plano=ig.plano,
            membros=int(membros_por.get(ig.id, 0)),
            pessoas=int(pessoas_por.get(ig.id, 0)),
            createdAt=ig.created_at.isoformat() if ig.created_at else None,
        )
        for ig in igrejas
    ]


@router.post(
    "/igrejas",
    response_model=CreateIgrejaResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_igreja(
    payload: CreateIgrejaRequest,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
    mailer: BrevoClient = Depends(get_brevo_client),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> CreateIgrejaResponse:
    """Provision a new church and invite its first admin (US-43, manual).

    Cria a igreja em **'aguardando_aprovacao'** (M2): o acesso ao painel fica
    bloqueado (BLOCKING_IGREJA_STATUSES) até o master aprovar
    (POST /admin/igrejas/{id}/aprovar). O convidado já pode ATIVAR o acesso
    (definir senha), mas só loga após a aprovação. Cria também um app_user
    (convidado, role admin) e envia o link de ativação (best-effort:
    emailEnviado=false se o Brevo falhar, a igreja é criada mesmo assim). Roda
    como o role de conexão (BYPASSRLS), então os inserts cross-tenant passam por
    cima da RLS por igreja.
    """
    email = payload.admin.email

    if payload.plano is not None:
        _validate_plano_or_422(db, payload.plano)

    igreja = Igreja(
        nome=payload.nome, status="aguardando_aprovacao", plano=payload.plano
    )
    db.add(igreja)
    db.flush()  # assign igreja.id

    app_user = AppUser(
        igreja_id=igreja.id,
        nome=payload.admin.nome,
        email=email,
        status="convidado",
    )
    db.add(app_user)
    db.flush()  # assign app_user.id

    db.add(UserRole(igreja_id=igreja.id, user_id=app_user.id, papel="admin"))
    _audit(
        db, admin, "provisionar", "igreja", igreja.id, igreja.nome,
        {"plano": payload.plano, "adminEmail": email},
    )
    db.commit()

    email_sent = False
    try:
        mailer.send_invite(
            to_email=email,
            nome=payload.admin.nome,
            activation_link=_activation_link(app_user.id, clerk),
        )
        email_sent = True
    except BrevoError:
        logger.warning("Igreja criada, mas o convite ao admin inicial falhou")

    return CreateIgrejaResponse(
        igrejaId=str(igreja.id),
        adminUsuarioId=str(app_user.id),
        emailEnviado=email_sent,
    )


@router.patch("/igrejas/{igreja_id}", response_model=IgrejaOut)
def update_igreja(
    igreja_id: str,
    payload: UpdateIgrejaRequest,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> IgrejaOut:
    """Change a church's status and/or plano (US-42).

    Suspend/reactivate/approve a church or move it between plans. At least one
    field must be provided (422 otherwise).
    """
    if payload.status is None and payload.plano is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe ao menos um campo para atualizar (status ou plano)",
        )

    try:
        ig_uuid = uuid.UUID(igreja_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        ) from exc

    igreja = db.execute(
        select(Igreja).where(Igreja.id == ig_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        )

    if payload.plano is not None:
        _validate_plano_or_422(db, payload.plano)

    antes = {"status": igreja.status, "plano": igreja.plano}
    if payload.status is not None:
        igreja.status = payload.status
    if payload.plano is not None:
        igreja.plano = payload.plano
    _audit(
        db, admin, "editar", "igreja", igreja.id, igreja.nome,
        {"de": antes, "para": {"status": igreja.status, "plano": igreja.plano}},
    )
    db.commit()

    membros = int(
        db.execute(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.igreja_id == ig_uuid)
        ).scalar_one()
    )
    pessoas = int(
        db.execute(
            select(func.count())
            .select_from(Pessoa)
            .where(Pessoa.igreja_id == ig_uuid)
        ).scalar_one()
    )

    return IgrejaOut(
        id=str(igreja.id),
        nome=igreja.nome,
        status=igreja.status,
        plano=igreja.plano,
        membros=membros,
        pessoas=pessoas,
        createdAt=igreja.created_at.isoformat() if igreja.created_at else None,
    )


@router.delete("/igrejas/{igreja_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_igreja(
    igreja_id: str,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> None:
    """Excluir uma igreja e TODOS os seus dados (cross-tenant, irreversível).

    O schema tem ON DELETE CASCADE em todas as tabelas filhas (app_users,
    pessoas, células, conversas…), então remover a igreja limpa tudo sem deixar
    órfãos. Operação destrutiva — a UI exige confirmação. Suspender (PATCH
    status) é o caminho normal; excluir é para igrejas de teste/erro.
    """
    try:
        ig_uuid = uuid.UUID(igreja_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        ) from exc

    igreja = db.execute(
        select(Igreja).where(Igreja.id == ig_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        )

    _audit(
        db, admin, "excluir", "igreja", igreja.id, igreja.nome,
        {"status": igreja.status, "plano": igreja.plano},
    )
    db.delete(igreja)
    db.commit()


def _seed_role_permissions(db: Session, igreja_id: uuid.UUID) -> None:
    """Semeia a matriz role_permissions com os defaults (idempotente).

    Roda na aprovação (M2) para a igreja já nascer com a matriz de #permissoes
    explícita e editável. Idempotente: se a igreja já tem qualquer linha (ex.:
    re-aprovação ou o admin já customizou), não faz nada — não sobrescreve.
    Obs.: ``require_screen`` cai nos mesmos defaults quando não há linhas, então
    isto é uma conveniência (matriz visível desde o dia 1), não um pré-requisito.
    """
    existe = db.execute(
        select(RolePermission.id)
        .where(RolePermission.igreja_id == igreja_id)
        .limit(1)
    ).scalar_one_or_none()
    if existe is not None:
        return
    for papel, telas in DEFAULT_PERMISSIONS.items():
        for tela in telas:
            db.add(RolePermission(igreja_id=igreja_id, papel=papel, tela=tela))


@router.post("/igrejas/{igreja_id}/aprovar", response_model=IgrejaOut)
def aprovar_igreja(
    igreja_id: str,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> IgrejaOut:
    """Aprova uma igreja pendente (M2): 'aguardando_aprovacao' -> 'ativa'.

    Libera o acesso ao painel (sai do BLOCKING_IGREJA_STATUSES) e dispara a
    cascata: semeia a matriz role_permissions padrão (idempotente). Idempotente
    se já estiver 'ativa' (no-op); 409 se estiver suspensa/inadimplente (esses
    voltam por PATCH status, não por aprovação).
    """
    try:
        ig_uuid = uuid.UUID(igreja_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        ) from exc

    igreja = db.execute(
        select(Igreja).where(Igreja.id == ig_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        )

    if igreja.status != "ativa":
        if igreja.status != "aguardando_aprovacao":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Só é possível aprovar uma igreja em 'aguardando aprovação'."
                ),
            )
        igreja.status = "ativa"
        _seed_role_permissions(db, ig_uuid)
        _audit(db, admin, "aprovar", "igreja", igreja.id, igreja.nome, None)
        db.commit()

    membros = int(
        db.execute(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.igreja_id == ig_uuid)
        ).scalar_one()
    )
    pessoas = int(
        db.execute(
            select(func.count())
            .select_from(Pessoa)
            .where(Pessoa.igreja_id == ig_uuid)
        ).scalar_one()
    )

    return IgrejaOut(
        id=str(igreja.id),
        nome=igreja.nome,
        status=igreja.status,
        plano=igreja.plano,
        membros=membros,
        pessoas=pessoas,
        createdAt=igreja.created_at.isoformat() if igreja.created_at else None,
    )


# ---------------------------------------------------------------------------
# M1 — Visão global e drill-down por igreja
# ---------------------------------------------------------------------------
class AdminMetricsOut(BaseModel):
    """Métricas globais da plataforma para o console master."""

    totalIgrejas: int  # noqa: N815
    porStatus: dict[str, int]  # noqa: N815 - {ativa: N, suspensa: N, ...}
    porPlano: dict[str, int]  # noqa: N815 - {ate_100: N, ...}
    mrr: float  # R$/mês recorrente (igrejas ATIVAS com plano)
    totalMembros: int  # noqa: N815 - app_users (todas as igrejas)
    totalPessoas: int  # noqa: N815 - pessoas cadastradas
    custoIaTotal: float  # noqa: N815 - soma de ai_usage_logs.custo


class SubscriptionOut(BaseModel):
    plano: str | None = None
    status: str | None = None
    pessoas: int | None = None
    limite: int | None = None
    proximaCobranca: str | None = None  # noqa: N815
    setupPago: bool = False  # noqa: N815


class IgrejaDetailOut(BaseModel):
    """Drill-down de uma igreja (cross-tenant)."""

    id: str
    nome: str
    status: str
    plano: str | None = None
    createdAt: str | None = None  # noqa: N815
    mensalidade: float | None = None  # R$/mês do plano (None se sem plano)
    membros: int = 0  # app_users (acessos ao painel)
    pessoas: int = 0  # Pessoa (cadastro)
    celulas: int = 0
    custoIa: float = 0  # noqa: N815 - soma ai_usage_logs.custo
    tokensIa: int = 0  # noqa: N815 - soma tokens_in + tokens_out
    assinatura: SubscriptionOut | None = None


@router.get("/metrics", response_model=AdminMetricsOut)
def admin_metrics(
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> AdminMetricsOut:
    """Visão global da plataforma (cross-tenant, BYPASSRLS).

    MRR = soma da mensalidade (catálogo `planos`) das igrejas ATIVAS com plano.
    O custo de IA é a soma de ai_usage_logs (BYO-LLM, fora do preço do PastorAI —
    mas o provedor acompanha o consumo por aqui).
    """
    igrejas = db.execute(select(Igreja)).scalars().all()
    precos = _plano_precos(db)

    por_status: dict[str, int] = {}
    por_plano: dict[str, int] = {}
    mrr = 0.0
    for ig in igrejas:
        por_status[ig.status] = por_status.get(ig.status, 0) + 1
        if ig.plano:
            por_plano[ig.plano] = por_plano.get(ig.plano, 0) + 1
        if ig.status == "ativa" and ig.plano in precos:
            mrr += precos[ig.plano]

    total_membros = int(
        db.execute(select(func.count()).select_from(AppUser)).scalar_one()
    )
    total_pessoas = int(
        db.execute(select(func.count()).select_from(Pessoa)).scalar_one()
    )
    custo_ia = float(
        db.execute(select(func.coalesce(func.sum(AiUsageLog.custo), 0))).scalar_one()
        or 0
    )

    return AdminMetricsOut(
        totalIgrejas=len(igrejas),
        porStatus=por_status,
        porPlano=por_plano,
        mrr=mrr,
        totalMembros=total_membros,
        totalPessoas=total_pessoas,
        custoIaTotal=custo_ia,
    )


@router.get("/igrejas/{igreja_id}", response_model=IgrejaDetailOut)
def get_igreja_detail(
    igreja_id: str,
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> IgrejaDetailOut:
    """Drill-down de uma igreja: assinatura, custo de IA e contadores."""
    try:
        ig_uuid = uuid.UUID(igreja_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        ) from exc

    igreja = db.execute(
        select(Igreja).where(Igreja.id == ig_uuid)
    ).scalar_one_or_none()
    if igreja is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Igreja não encontrada"
        )

    membros = int(
        db.execute(
            select(func.count()).select_from(AppUser).where(AppUser.igreja_id == ig_uuid)
        ).scalar_one()
    )
    pessoas = int(
        db.execute(
            select(func.count()).select_from(Pessoa).where(Pessoa.igreja_id == ig_uuid)
        ).scalar_one()
    )
    celulas = int(
        db.execute(
            select(func.count()).select_from(Celula).where(Celula.igreja_id == ig_uuid)
        ).scalar_one()
    )

    custo_ia = float(
        db.execute(
            select(func.coalesce(func.sum(AiUsageLog.custo), 0)).where(
                AiUsageLog.igreja_id == ig_uuid
            )
        ).scalar_one()
        or 0
    )
    tokens_ia = int(
        db.execute(
            select(
                func.coalesce(func.sum(AiUsageLog.tokens_in), 0)
                + func.coalesce(func.sum(AiUsageLog.tokens_out), 0)
            ).where(AiUsageLog.igreja_id == ig_uuid)
        ).scalar_one()
        or 0
    )

    sub = db.execute(
        select(Subscription).where(Subscription.igreja_id == ig_uuid)
    ).scalar_one_or_none()
    assinatura = (
        SubscriptionOut(
            plano=sub.plano,
            status=sub.status,
            pessoas=sub.pessoas,
            limite=sub.limite,
            proximaCobranca=(
                sub.proxima_cobranca.isoformat() if sub.proxima_cobranca else None
            ),
            setupPago=sub.setup_pago,
        )
        if sub is not None
        else None
    )

    mensalidade = _plano_precos(db).get(igreja.plano) if igreja.plano else None

    return IgrejaDetailOut(
        id=str(igreja.id),
        nome=igreja.nome,
        status=igreja.status,
        plano=igreja.plano,
        createdAt=igreja.created_at.isoformat() if igreja.created_at else None,
        mensalidade=mensalidade,
        membros=membros,
        pessoas=pessoas,
        celulas=celulas,
        custoIa=custo_ia,
        tokensIa=tokens_ia,
        assinatura=assinatura,
    )


# ---------------------------------------------------------------------------
# Gestão de planos — "o master pode definir os planos" (catálogo, migration 0012)
# ---------------------------------------------------------------------------
class PlanoOut(BaseModel):
    """Um plano do catálogo, como visto pelo console master."""

    id: str
    codigo: str
    nome: str
    limitePessoas: int | None = None  # noqa: N815 - None = ilimitado
    precoMensal: float  # noqa: N815
    ativo: bool
    ordem: int
    emUso: int = 0  # noqa: N815 - nº de igrejas neste plano (trava o DELETE)


class CreatePlanoRequest(BaseModel):
    codigo: str = Field(min_length=1, max_length=50)
    nome: str = Field(min_length=1, max_length=120)
    limitePessoas: int | None = Field(default=None, ge=1)  # noqa: N815
    precoMensal: float = Field(ge=0)  # noqa: N815
    ordem: int = Field(default=0, ge=0)

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]+", v):
            raise ValueError(
                "codigo deve conter apenas letras minúsculas, números e _"
            )
        return v

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome obrigatório")
        return v


class UpdatePlanoRequest(BaseModel):
    # PATCH parcial: só os campos presentes no corpo são alterados (model_fields_set).
    # limitePessoas aceita null EXPLÍCITO para marcar "ilimitado".
    nome: str | None = Field(default=None, max_length=120)
    limitePessoas: int | None = Field(default=None, ge=1)  # noqa: N815
    precoMensal: float | None = Field(default=None, ge=0)  # noqa: N815
    ativo: bool | None = Field(default=None)
    ordem: int | None = Field(default=None, ge=0)

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("nome não pode ficar vazio")
        return v


def _plano_out(p: Plano, em_uso: int = 0) -> PlanoOut:
    return PlanoOut(
        id=str(p.id),
        codigo=p.codigo,
        nome=p.nome,
        limitePessoas=p.limite_pessoas,
        precoMensal=float(p.preco_mensal),
        ativo=p.ativo,
        ordem=p.ordem,
        emUso=em_uso,
    )


def _get_plano_or_404(db: Session, plano_id: str) -> Plano:
    try:
        pid = uuid.UUID(plano_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plano não encontrado"
        ) from exc
    plano = db.execute(select(Plano).where(Plano.id == pid)).scalar_one_or_none()
    if plano is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plano não encontrado"
        )
    return plano


def _igrejas_no_plano(db: Session, codigo: str) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(Igreja).where(Igreja.plano == codigo)
        ).scalar_one()
    )


@router.get("/planos", response_model=list[PlanoOut])
def list_planos(
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> list[PlanoOut]:
    """Lista o catálogo de planos (inclui inativos), com nº de igrejas em uso."""
    planos = db.execute(
        select(Plano).order_by(Plano.ordem, Plano.codigo)
    ).scalars().all()
    em_uso = dict(
        db.execute(
            select(Igreja.plano, func.count())
            .where(Igreja.plano.is_not(None))
            .group_by(Igreja.plano)
        ).all()
    )
    return [_plano_out(p, int(em_uso.get(p.codigo, 0))) for p in planos]


@router.post("/planos", response_model=PlanoOut, status_code=status.HTTP_201_CREATED)
def create_plano(
    payload: CreatePlanoRequest,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> PlanoOut:
    """Cria um plano no catálogo (US-42 — definir planos).

    O ``codigo`` é a chave estável referenciada por ``igrejas.plano`` e é
    imutável depois de criado (409 se já existir).
    """
    existe = db.execute(
        select(Plano.id).where(Plano.codigo == payload.codigo)
    ).scalar_one_or_none()
    if existe is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Já existe um plano com código '{payload.codigo}'",
        )
    plano = Plano(
        codigo=payload.codigo,
        nome=payload.nome,
        limite_pessoas=payload.limitePessoas,
        preco_mensal=payload.precoMensal,
        ativo=True,  # explícito: server_default só vale no banco (não no objeto)
        ordem=payload.ordem,
    )
    db.add(plano)
    db.flush()  # popula plano.id para o audit referenciar
    _audit(
        db, admin, "plano_criar", "plano", plano.id, plano.nome,
        {"codigo": plano.codigo, "preco": float(plano.preco_mensal)},
    )
    db.commit()
    return _plano_out(plano, 0)


@router.patch("/planos/{plano_id}", response_model=PlanoOut)
def update_plano(
    plano_id: str,
    payload: UpdatePlanoRequest,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> PlanoOut:
    """Edita um plano: nome, preço, limite, ordem ou ativa/desativa.

    O ``codigo`` não muda (as igrejas o referenciam). Atualização parcial: só
    os campos enviados são alterados — ``limitePessoas: null`` marca ilimitado.
    """
    plano = _get_plano_or_404(db, plano_id)
    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe ao menos um campo para atualizar",
        )
    if "nome" in fields and payload.nome is not None:
        plano.nome = payload.nome
    if "limitePessoas" in fields:  # null explícito = ilimitado
        plano.limite_pessoas = payload.limitePessoas
    if "precoMensal" in fields and payload.precoMensal is not None:
        plano.preco_mensal = payload.precoMensal
    if "ativo" in fields and payload.ativo is not None:
        plano.ativo = payload.ativo
    if "ordem" in fields and payload.ordem is not None:
        plano.ordem = payload.ordem
    _audit(
        db, admin, "plano_editar", "plano", plano.id, plano.nome,
        {"campos": sorted(fields)},
    )
    db.commit()
    return _plano_out(plano, _igrejas_no_plano(db, plano.codigo))


@router.delete("/planos/{plano_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plano(
    plano_id: str,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> None:
    """Exclui um plano do catálogo — só se NENHUMA igreja o estiver usando.

    Se houver igrejas no plano (409), o master deve desativá-lo (PATCH
    ativo=false) em vez de excluir, para não quebrar a referência delas.
    """
    plano = _get_plano_or_404(db, plano_id)
    em_uso = _igrejas_no_plano(db, plano.codigo)
    if em_uso > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{em_uso} igreja(s) usam este plano. "
                "Desative-o em vez de excluir."
            ),
        )
    _audit(
        db, admin, "plano_excluir", "plano", plano.id, plano.nome,
        {"codigo": plano.codigo},
    )
    db.delete(plano)
    db.commit()


# ---------------------------------------------------------------------------
# M3 — Auditoria das ações cross-tenant do console (migration 0013)
# ---------------------------------------------------------------------------
class AuditEntryOut(BaseModel):
    """Uma entrada do log de auditoria do console."""

    id: str
    actorEmail: str | None = None  # noqa: N815 - quem fez a ação
    acao: str
    alvoTipo: str  # noqa: N815 - 'igreja' | 'plano'
    alvoId: str | None = None  # noqa: N815
    alvoNome: str | None = None  # noqa: N815
    detalhe: dict | None = None
    createdAt: str | None = None  # noqa: N815


@router.get("/audit", response_model=list[AuditEntryOut])
def list_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> list[AuditEntryOut]:
    """Lista as ações recentes do console (mais novas primeiro). Limite 1..200."""
    limit = max(1, min(limit, 200))
    rows = db.execute(
        select(PlatformAuditLog)
        .order_by(PlatformAuditLog.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        AuditEntryOut(
            id=str(r.id),
            actorEmail=r.actor_email,
            acao=r.acao,
            alvoTipo=r.alvo_tipo,
            alvoId=str(r.alvo_id) if r.alvo_id else None,
            alvoNome=r.alvo_nome,
            detalhe=r.detalhe,
            createdAt=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]

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
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AppUser, Igreja, Pessoa, UserRole
from app.db.session import get_db
from app.deps import PlatformAdminUser, get_platform_admin
from app.services.brevo import BrevoClient, BrevoError, get_brevo_client
from app.services.clerk import ClerkClient, get_clerk_client

logger = logging.getLogger("pastorai.platform_admin")

router = APIRouter(prefix="/admin", tags=["platform-admin"])

# Status válidos de igreja (enum igreja_status — migration 0001).
IGREJA_STATUSES = {"ativa", "suspensa", "aguardando_aprovacao", "inadimplente"}

# Planos conhecidos (igrejas.plano é texto livre; validamos o conjunto atual
# para evitar typo, mantendo a coluna extensível no banco).
IGREJA_PLANOS = {"ate_100", "101_200", "acima_201"}


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
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if v not in IGREJA_PLANOS:
            raise ValueError(f"plano inválido: {v}")
        return v


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
        if v is None:
            return None
        v = v.strip()
        if not v or v not in IGREJA_PLANOS:
            raise ValueError(f"plano inválido: {v}")
        return v


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
    _admin: PlatformAdminUser = Depends(get_platform_admin),
    mailer: BrevoClient = Depends(get_brevo_client),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> CreateIgrejaResponse:
    """Provision a new church and invite its first admin (US-43, manual).

    Creates the igreja (status 'ativa'), an app_user (convidado, role admin) and
    emails the activation link (best-effort: emailEnviado=false if Brevo fails,
    the church is still created). The new church is an isolated tenant; its admin
    activates via the standard invite flow. Runs as the connection role
    (BYPASSRLS), so the cross-tenant inserts bypass the per-igreja RLS policies.
    """
    email = payload.admin.email

    igreja = Igreja(nome=payload.nome, status="ativa", plano=payload.plano)
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
    _admin: PlatformAdminUser = Depends(get_platform_admin),
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

    if payload.status is not None:
        igreja.status = payload.status
    if payload.plano is not None:
        igreja.plano = payload.plano
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

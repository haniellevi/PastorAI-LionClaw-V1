"""Setup checklist router — Missão 7B-7 (guia interativo de configuração).

GET /setup/checklist agrega o estado de configuração inicial da igreja em um só
lugar (identidade visual, equipe/papéis, células, WhatsApp, agente e, para o
dono, plano/assinatura), cada item apontando para a tela correspondente
(`screen`, alvo de hash route no admin). Só informa pendências — não bloqueia
nenhuma tela nem ação do sistema (RF 7B-7 §3).

'assinatura' só aparece para o DONO da igreja (mesmo gate de OWNER_ONLY que já
existe no menu/Sidebar para a tela Assinatura — um admin não-dono não vê a
tela, então não faria sentido reportar seu estado aqui).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Celula,
    Igreja,
    LlmCredential,
    Subscription,
    WhatsappConnection,
)
from app.db.session import get_db
from app.deps import REVOKED_USER_STATUS, CurrentUser, require_role
from app.services.billing import assigned_complimentary_plan

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupItemOut(BaseModel):
    id: str
    screen: str
    done: bool


class SetupChecklistOut(BaseModel):
    items: list[SetupItemOut]
    pendingCount: int  # noqa: N815 - external contract uses camelCase


@router.get("/checklist", response_model=SetupChecklistOut)
def get_setup_checklist(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> SetupChecklistOut:
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    items: list[SetupItemOut] = []

    igreja = db.execute(
        select(Igreja).where(Igreja.id == igreja_uuid)
    ).scalar_one_or_none()
    items.append(
        SetupItemOut(id="identidade", screen="identidade", done=bool(igreja and igreja.logo_path))
    )

    team_count = db.execute(
        select(func.count())
        .select_from(AppUser)
        .where(
            AppUser.igreja_id == igreja_uuid,
            AppUser.status.is_distinct_from(REVOKED_USER_STATUS),
        )
    ).scalar_one()
    items.append(SetupItemOut(id="equipe", screen="equipe", done=team_count > 1))

    cell_count = db.execute(
        select(func.count())
        .select_from(Celula)
        .where(Celula.igreja_id == igreja_uuid)
    ).scalar_one()
    items.append(SetupItemOut(id="celulas", screen="celulas", done=cell_count > 0))

    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    items.append(
        SetupItemOut(id="whatsapp", screen="whatsapp", done=bool(conn and conn.status == "online"))
    )

    cred = db.execute(
        select(LlmCredential).where(LlmCredential.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    items.append(
        SetupItemOut(
            id="agente", screen="agente", done=bool(cred and cred.validado and cred.ativo)
        )
    )

    if current_user.is_owner:
        sub = db.execute(
            select(Subscription).where(Subscription.igreja_id == igreja_uuid)
        ).scalar_one_or_none()
        complimentary = assigned_complimentary_plan(db, igreja) if sub is None else None
        items.append(
            SetupItemOut(
                id="assinatura",
                screen="assinatura",
                done=bool((sub and sub.status == "ativa") or complimentary),
            )
        )

    pending = sum(1 for item in items if not item.done)
    return SetupChecklistOut(items=items, pendingCount=pending)

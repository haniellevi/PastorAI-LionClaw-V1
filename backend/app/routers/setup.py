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
    Plano,
    Subscription,
    WhatsappConnection,
)
from app.db.session import get_db
from app.deps import REVOKED_USER_STATUS, CurrentUser, require_role

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

    # Scalar projections avoid fetching credentials, full users and history.
    # Every tenant relation remains explicitly filtered, alongside request RLS.
    def exists_for(model, *conditions):
        return select(model.id).where(model.igreja_id == igreja_uuid, *conditions).exists()

    identity = select(Igreja.logo_path).where(Igreja.id == igreja_uuid).scalar_subquery()
    team = select(func.count()).select_from(AppUser).where(
        AppUser.igreja_id == igreja_uuid,
        AppUser.status.is_distinct_from(REVOKED_USER_STATUS),
    ).scalar_subquery()
    complimentary = select(Plano.id).join(Igreja, Igreja.plano == Plano.codigo).where(
        Igreja.id == igreja_uuid, Plano.preco_mensal == 0,
    ).exists()
    state = db.execute(select(
        identity.label("setup_identity"),
        (team > 1).label("setup_team"),
        exists_for(Celula).label("setup_cells"),
        exists_for(WhatsappConnection, WhatsappConnection.status == "online").label("setup_whatsapp"),
        exists_for(LlmCredential, LlmCredential.validado.is_(True), LlmCredential.ativo.is_(True)).label("setup_agent"),
        (exists_for(Subscription, Subscription.status == "ativa") | complimentary).label("setup_subscription"),
    )).one()
    items = [
        SetupItemOut(id="identidade", screen="identidade", done=bool(state.setup_identity)),
        SetupItemOut(id="equipe", screen="equipe", done=bool(state.setup_team)),
        SetupItemOut(id="celulas", screen="celulas", done=bool(state.setup_cells)),
        SetupItemOut(id="whatsapp", screen="whatsapp", done=bool(state.setup_whatsapp)),
        SetupItemOut(id="agente", screen="agente", done=bool(state.setup_agent)),
    ]
    if current_user.is_owner:
        items.append(SetupItemOut(
            id="assinatura", screen="assinatura", done=bool(state.setup_subscription),
        ))

    pending = sum(1 for item in items if not item.done)
    return SetupChecklistOut(items=items, pendingCount=pending)

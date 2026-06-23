"""Dashboard router — visão geral (totais por tipo/etapa + KPIs) do tenant (#2).

Escopo por papel: admin/pastor e líderes sênior (G12/consolidação) veem a
IGREJA INTEIRA; líder de célula vê só as pessoas das células que ele lidera (via
AppUser.pessoa_id → celulas.lider_id). Tenant-scoped por RLS
(ensure_tenant_context). Sem agregação cross-tenant.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Text, case, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.domain.dashboard_overview import (
    ETAPA_BUCKETS,
    TIPO_BUCKETS,
    has_full_overview,
    normalize_counts,
)
from app.routers._common import ensure_tenant_context

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class OverviewOut(BaseModel):
    """Totais do tenant para a faixa 'Visão geral' do dashboard (#2)."""

    scope: str  # "igreja" | "celula"
    total: int
    decisoesJesus: int  # noqa: N815
    celulasAtivas: int  # noqa: N815
    semInteresse: int  # noqa: N815 - CSIM
    porTipo: dict[str, int]  # noqa: N815
    porEtapa: dict[str, int]  # noqa: N815

    @classmethod
    def empty(cls, scope: str) -> "OverviewOut":
        return cls(
            scope=scope,
            total=0,
            decisoesJesus=0,
            celulasAtivas=0,
            semInteresse=0,
            porTipo=normalize_counts({}, TIPO_BUCKETS),
            porEtapa=normalize_counts({}, ETAPA_BUCKETS),
        )


@router.get("/overview", response_model=OverviewOut)
def overview(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("dashboard")),
) -> OverviewOut:
    """Totais por tipo/etapa + KPIs, escopados por papel (#2).

    admin/pastor/líderes sênior → igreja inteira; líder de célula → só as suas
    células. Quem não tem visão completa nem lidera células recebe zeros.
    """
    ensure_tenant_context(db, current_user)

    full = has_full_overview(current_user.roles)
    person_filter = None
    cell_filter = None
    scope = "igreja"
    if not full:
        scope = "celula"
        pessoa_id = db.execute(
            select(AppUser.pessoa_id).where(
                AppUser.id == uuid.UUID(current_user.app_user_id)
            )
        ).scalar_one_or_none()
        if pessoa_id is None:
            return OverviewOut.empty(scope)
        cell_ids = list(
            db.execute(
                select(Celula.id).where(Celula.lider_id == pessoa_id)
            ).scalars().all()
        )
        if not cell_ids:
            return OverviewOut.empty(scope)
        person_filter = Pessoa.celula_id.in_(cell_ids)
        cell_filter = Celula.id.in_(cell_ids)

    # porTipo: CSIM entra no bucket "sem_interesse"; senão, o tipo. tipo NULL cai
    # em "contato" (entrada) para a soma fechar com o total (espelha a UI).
    tipo_expr = case(
        (Pessoa.sem_interesse.is_(True), "sem_interesse"),
        else_=func.coalesce(cast(Pessoa.tipo, Text), "contato"),
    )
    tipo_q = select(tipo_expr, func.count()).group_by(tipo_expr)
    if person_filter is not None:
        tipo_q = tipo_q.where(person_filter)
    por_tipo = normalize_counts(dict(db.execute(tipo_q).all()), TIPO_BUCKETS)

    # porEtapa: exclui CSIM (fora do funil). etapa NULL = "ganhar" (entrada do
    # funil, como o trigger fn_promote_pipeline), p/ não subcontar a fila.
    etapa_expr = case(
        (Pessoa.etapa.is_(None), "ganhar"), else_=cast(Pessoa.etapa, Text)
    )
    etapa_q = (
        select(etapa_expr, func.count())
        .where(Pessoa.sem_interesse.is_(False))
        .group_by(etapa_expr)
    )
    if person_filter is not None:
        etapa_q = etapa_q.where(person_filter)
    por_etapa = normalize_counts(dict(db.execute(etapa_q).all()), ETAPA_BUCKETS)

    # KPIs
    total_q = select(func.count()).select_from(Pessoa)
    dec_q = (
        select(func.count()).select_from(Pessoa).where(Pessoa.aceitou_jesus.is_(True))
    )
    csim_q = (
        select(func.count()).select_from(Pessoa).where(Pessoa.sem_interesse.is_(True))
    )
    if person_filter is not None:
        total_q = total_q.where(person_filter)
        dec_q = dec_q.where(person_filter)
        csim_q = csim_q.where(person_filter)
    total = int(db.execute(total_q).scalar_one())
    decisoes = int(db.execute(dec_q).scalar_one())
    sem_interesse = int(db.execute(csim_q).scalar_one())

    cells_q = select(func.count()).select_from(Celula).where(Celula.ativo.is_(True))
    if cell_filter is not None:
        cells_q = cells_q.where(cell_filter)
    celulas_ativas = int(db.execute(cells_q).scalar_one())

    return OverviewOut(
        scope=scope,
        total=total,
        decisoesJesus=decisoes,
        celulasAtivas=celulas_ativas,
        semInteresse=sem_interesse,
        porTipo=por_tipo,
        porEtapa=por_etapa,
    )

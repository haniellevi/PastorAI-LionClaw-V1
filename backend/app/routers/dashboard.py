"""Dashboard router — visão geral (totais por tipo/etapa + KPIs) do tenant (#2).

Escopo por papel: admin/pastor e líderes sênior (G12/consolidação) veem a
IGREJA INTEIRA; líder de célula vê só os vínculos ativos das células ativas que
ele lidera (via AppUser.pessoa_id → celulas.lider_id → celula_membro).
Tenant-scoped por RLS: a sessão já vem marcada por ``get_current_user`` (seam
``mark_tenant_scoped`` + listener ``after_begin``). Sem agregação cross-tenant.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Text, case, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, CelulaMembro, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, require_screen
from app.domain.dashboard_overview import (
    ETAPA_BUCKETS,
    TIPO_BUCKETS,
    has_full_overview,
    normalize_counts,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class OverviewOut(BaseModel):
    """Totais do tenant para a faixa 'Visão geral' do dashboard (#2)."""

    scope: str  # "igreja" | "celula"
    total: int
    decisoesJesus: int  # noqa: N815
    celulasAtivas: int  # noqa: N815
    # Líderes de célula DERIVADOS (pessoas distintas em celulas.lider_id de
    # célula ativa) — nunca de pessoas.tipo (regra 2026-07-06).
    lideresCelula: int  # noqa: N815
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
            lideresCelula=0,
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

    full = has_full_overview(current_user.roles)
    person_filter = None
    cell_filter = None
    scope = "igreja"
    if not full:
        scope = "celula"
        has_cells = (
            select(Celula.id)
            .where(
                Celula.lider_id == AppUser.pessoa_id,
                Celula.ativo.is_(True),
            )
            .exists()
        )
        scope_row = (
            db.execute(
                select(
                    AppUser.pessoa_id.label("pessoa_id"),
                    has_cells.label("has_cells"),
                ).where(AppUser.id == uuid.UUID(current_user.app_user_id))
            )
            .mappings()
            .one_or_none()
        )
        if (
            scope_row is None
            or scope_row["pessoa_id"] is None
            or not scope_row["has_cells"]
        ):
            return OverviewOut.empty(scope)
        pessoa_id = scope_row["pessoa_id"]
        person_filter = (
            select(CelulaMembro.id)
            .join(Celula, Celula.id == CelulaMembro.celula_id)
            .where(
                CelulaMembro.pessoa_id == Pessoa.id,
                CelulaMembro.ativo.is_(True),
                Celula.ativo.is_(True),
                Celula.lider_id == pessoa_id,
            )
            .exists()
        )
        cell_filter = Celula.lider_id == pessoa_id

    # porTipo: CSIM entra no bucket "sem_interesse"; senão, o tipo. tipo NULL cai
    # em "contato" (entrada) para a soma fechar com o total (espelha a UI).
    tipo_expr = case(
        (Pessoa.sem_interesse.is_(True), "sem_interesse"),
        else_=func.coalesce(cast(Pessoa.tipo, Text), "contato"),
    )
    pessoa_columns = [
        func.count().label("total"),
        func.count()
        .filter(Pessoa.aceitou_jesus.is_(True))
        .label("decisoes_jesus"),
        func.count()
        .filter(Pessoa.sem_interesse.is_(True))
        .label("sem_interesse"),
        *[
            func.count()
            .filter(tipo_expr == bucket)
            .label(f"tipo_{bucket}")
            for bucket in TIPO_BUCKETS
        ],
    ]

    # porEtapa: exclui CSIM (fora do funil). etapa NULL = "ganhar" (entrada do
    # funil, como o trigger fn_promote_pipeline), p/ não subcontar a fila.
    etapa_expr = case(
        (Pessoa.etapa.is_(None), "ganhar"), else_=cast(Pessoa.etapa, Text)
    )
    pessoa_columns.extend(
        func.count()
        .filter(Pessoa.sem_interesse.is_(False), etapa_expr == bucket)
        .label(f"etapa_{bucket}")
        for bucket in ETAPA_BUCKETS
    )

    # Uma única linha agregada substitui porTipo, porEtapa e os três KPIs de
    # Pessoa. COUNT ... FILTER preserva a semântica anterior sem materializar
    # pessoas no processo da API.
    pessoa_q = (
        select(*pessoa_columns)
        .select_from(Pessoa)
        .where(Pessoa.arquivada_em.is_(None))
    )
    if person_filter is not None:
        pessoa_q = pessoa_q.where(person_filter)
    pessoa = db.execute(pessoa_q).mappings().one()
    por_tipo = normalize_counts(
        {bucket: pessoa[f"tipo_{bucket}"] for bucket in TIPO_BUCKETS},
        TIPO_BUCKETS,
    )
    por_etapa = normalize_counts(
        {bucket: pessoa[f"etapa_{bucket}"] for bucket in ETAPA_BUCKETS},
        ETAPA_BUCKETS,
    )

    # Os dois KPIs de Celula também compartilham uma única linha agregada.
    cells_q = select(
        func.count().filter(Celula.ativo.is_(True)).label("ativas"),
        func.count(func.distinct(Celula.lider_id))
        .filter(Celula.ativo.is_(True), Celula.lider_id.is_not(None))
        .label("lideres"),
    ).select_from(Celula)
    if cell_filter is not None:
        cells_q = cells_q.where(cell_filter)
    cells = db.execute(cells_q).mappings().one()

    return OverviewOut(
        scope=scope,
        total=int(pessoa["total"]),
        decisoesJesus=int(pessoa["decisoes_jesus"]),
        celulasAtivas=int(cells["ativas"]),
        lideresCelula=int(cells["lideres"]),
        semInteresse=int(pessoa["sem_interesse"]),
        porTipo=por_tipo,
        porEtapa=por_etapa,
    )

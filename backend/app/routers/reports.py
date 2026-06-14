"""Reports router — weekly cell reports (RF-37).

Endpoint:
  - GET /reports   reports by cell/week with status recebido/pendente

A report exists once a cell submits it (status=recebido). For active, led cells
that have not reported for the requested week, a synthetic `pendente` entry is
returned so the panel can show who is missing — without persisting a row. The
target week defaults to the current ISO week and can be overridden via ?semana=.
All access is tenant-scoped by RLS (current_igreja_id).
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, Report
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.routers._common import Page, PaginationParams, ensure_tenant_context

logger = logging.getLogger("pastorai.reports")

router = APIRouter(prefix="/reports", tags=["reports"])


def current_iso_week(today: dt.date | None = None) -> str:
    """Return the current ISO week as `YYYY-Www` (e.g. 2026-W24)."""
    today = today or dt.date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


class ReportOut(BaseModel):
    """Report projection. Synthetic pending entries have id=None."""

    id: str | None = None
    celulaId: str  # noqa: N815
    celulaNome: str | None = None  # noqa: N815
    semana: str
    status: str  # recebido | pendente
    dataReuniao: dt.date | None = None  # noqa: N815
    presentes: int | None = None
    visitantes: int | None = None
    decisoes: int | None = None
    oferta: float | None = None
    observacoes: str | None = None
    origem: str | None = None

    @classmethod
    def from_model(cls, r: Report, celula_nome: str | None) -> "ReportOut":
        return cls(
            id=str(r.id),
            celulaId=str(r.celula_id),
            celulaNome=celula_nome,
            semana=r.semana,
            status=r.status or "recebido",
            dataReuniao=r.data_reuniao,
            presentes=r.presentes,
            visitantes=r.visitantes,
            decisoes=r.decisoes,
            oferta=float(r.oferta) if r.oferta is not None else None,
            observacoes=r.observacoes,
            origem=r.origem,
        )


@router.get("", response_model=Page[ReportOut])
def list_reports(
    semana: str | None = Query(default=None, description="ISO week, ex 2026-W24"),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[ReportOut]:
    """List reports for a week with recebido/pendente status (RNF-09).

    Received reports come from the `reports` table; pending entries are
    synthesized for active, led cells with no report that week.
    """
    ensure_tenant_context(db, current_user)
    target_week = (semana or "").strip() or current_iso_week()

    received = db.execute(
        select(Report).where(Report.semana == target_week)
    ).scalars().all()

    cells = db.execute(select(Celula)).scalars().all()
    cell_names = {c.id: c.nome for c in cells}
    reported_cell_ids = {r.celula_id for r in received}

    items: list[ReportOut] = [
        ReportOut.from_model(r, cell_names.get(r.celula_id)) for r in received
    ]

    # Synthetic pending entries for active, led cells that have not reported.
    for c in cells:
        if not c.ativo or c.lider_id is None:
            continue
        if c.id in reported_cell_ids:
            continue
        items.append(
            ReportOut(
                id=None,
                celulaId=str(c.id),
                celulaNome=c.nome,
                semana=target_week,
                status="pendente",
            )
        )

    total = len(items)
    start = pagination.offset
    page_items = items[start : start + pagination.limit]

    return Page[ReportOut](
        items=page_items,
        page=pagination.page,
        pageSize=pagination.page_size,
        total=total,
    )

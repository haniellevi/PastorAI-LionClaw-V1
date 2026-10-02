"""Central de Células — dashboard, fila de pendências e saúde (Células PR3-PR9).

Superfície de GOVERNANÇA da própria igreja, restrita à Central (pastor/admin via
``require_central`` — 403 para os demais). ``igreja_id`` deriva sempre do contexto
autenticado; nada vem do payload.

Endpoints (US-16/18/22):
  - GET /cell-central/dashboard        contadores operacionais (E16, não paginado);
  - GET /cell-central/pending-reports  relatórios pendentes de reuniões passadas;
  - GET /cell-central/health           saúde on-read (delegada a cell_health_service).

Leitura pura: nenhuma escrita. "Passada" segue o fuso America/Sao_Paulo (§6.5).
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import Time, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Celula,
    CelulaAviso,
    CelulaMaterial,
    CelulaReuniao,
    CelulaSolicitacao,
    Pessoa,
)
from app.db.session import get_db
from app.deps import CurrentUser, require_central
from app.domain.cell_meetings_schedule import now_in_sao_paulo
from app.domain.cell_requests import STATUS_AGUARDANDO, TIPO_MULTIPLICACAO
from app.services import cell_health_service
from app.services.cell_health_service import (
    RELATORIO_ENVIADO,
    STATUS_CANCELADA,
)

router = APIRouter(prefix="/cell-central", tags=["cell-central"])

# Relatório ainda não enviado (fila de pendentes).
RELATORIO_PENDENTE = "pendente"

# Janela de "recentes" para os contadores do dashboard (E16).
RECENT_DAYS = 7

# Paginação (contrato snake_case): padrão 20, máx 100.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Schemas de saída (snake_case)
# ---------------------------------------------------------------------------
class DashboardOut(BaseModel):
    relatorios_pendentes: int
    solicitacoes_aguardando: int
    celulas_com_alerta: int
    multiplicacoes_pendentes: int
    avisos_recentes: int
    materiais_recentes: int


class PendingReportItem(BaseModel):
    reuniao_id: str
    celula_id: str
    celula_nome: str
    lider_nome: str
    data: str


class PendingReportsPage(BaseModel):
    items: list[PendingReportItem]
    page: int
    page_size: int
    total: int = 0


class HealthSignalOut(BaseModel):
    reuniao_id: str
    cor: str


class CellHealthOut(BaseModel):
    celula_id: str
    celula_nome: str
    status: str
    sinais: list[HealthSignalOut]
    vermelhos: int
    alertas: int


class HealthOut(BaseModel):
    cells: list[CellHealthOut]


def _past_meeting_filter(now: dt.datetime):
    """SQL equivalent of meeting_has_passed, including null/malformed hours."""
    local = now_in_sao_paulo(now)
    hora = func.btrim(CelulaReuniao.hora)
    valid_time = case((hora.op("~")(r"^([01][0-9]|2[0-3]):[0-5][0-9]$"), cast(hora, Time)), else_=None)
    return or_(
        CelulaReuniao.data < local.date(),
        and_(CelulaReuniao.data == local.date(), valid_time < local.time().replace(tzinfo=None)),
    )


# ---------------------------------------------------------------------------
# GET /cell-central/dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> DashboardOut:
    """Contadores operacionais da própria igreja (E16). Não paginado (resumo)."""
    igreja_id = uuid.UUID(current_user.igreja_id)
    now = dt.datetime.now(dt.timezone.utc)
    recent_cutoff = now - dt.timedelta(days=RECENT_DAYS)

    def counter(model, *filters):
        return select(func.count()).select_from(model).where(model.igreja_id == igreja_id, *filters).scalar_subquery()

    counters = db.execute(select(
        counter(CelulaReuniao, CelulaReuniao.status.is_distinct_from(STATUS_CANCELADA),
            CelulaReuniao.relatorio_status.is_distinct_from(RELATORIO_ENVIADO), _past_meeting_filter(now)).label("central_pending"),
        counter(CelulaSolicitacao, CelulaSolicitacao.status == STATUS_AGUARDANDO).label("central_requests"),
        counter(CelulaSolicitacao, CelulaSolicitacao.status == STATUS_AGUARDANDO,
            CelulaSolicitacao.tipo == TIPO_MULTIPLICACAO).label("central_multiplications"),
        counter(CelulaAviso, CelulaAviso.ativo.is_(True), CelulaAviso.publicado_em >= recent_cutoff).label("central_notices"),
        counter(CelulaMaterial, CelulaMaterial.ativo.is_(True), CelulaMaterial.publicado_em >= recent_cutoff).label("central_materials"),
    )).one()
    relatorios_pendentes = counters.central_pending
    solicitacoes_aguardando = counters.central_requests
    multiplicacoes_pendentes = counters.central_multiplications
    avisos_recentes = counters.central_notices
    materiais_recentes = counters.central_materials

    # celulas_com_alerta — células distintas com ≥1 vermelho OU alerta.
    healths = cell_health_service.compute_cells_health(
        db, igreja_id, now=now
    )
    celulas_com_alerta = sum(
        1 for h in healths if h.vermelhos > 0 or h.alertas > 0
    )

    return DashboardOut(
        relatorios_pendentes=relatorios_pendentes,
        solicitacoes_aguardando=solicitacoes_aguardando,
        celulas_com_alerta=celulas_com_alerta,
        multiplicacoes_pendentes=multiplicacoes_pendentes,
        avisos_recentes=avisos_recentes,
        materiais_recentes=materiais_recentes,
    )


# ---------------------------------------------------------------------------
# GET /cell-central/pending-reports
# ---------------------------------------------------------------------------
@router.get("/pending-reports", response_model=PendingReportsPage)
def get_pending_reports(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Items per page (max 100)",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> PendingReportsPage:
    """Reuniões passadas não canceladas com ``relatorio_status='pendente'``.

    Identifica célula e líder (``lider_nome`` deriva de ``celulas.lider_id``,
    §6.6). Mais antigas primeiro (as mais atrasadas no topo). Paginado.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    filters = (
        CelulaReuniao.igreja_id == igreja_id,
        CelulaReuniao.status.is_distinct_from(STATUS_CANCELADA),
        CelulaReuniao.relatorio_status == RELATORIO_PENDENTE,
        _past_meeting_filter(dt.datetime.now(dt.timezone.utc)),
    )
    total = int(db.execute(select(func.count()).select_from(CelulaReuniao).where(*filters)).scalar_one())
    window = db.execute(
        select(CelulaReuniao).where(*filters)
        .order_by(CelulaReuniao.data.asc(), CelulaReuniao.hora.asc(), CelulaReuniao.id.asc())
        .offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    cell_ids = {r.celula_id for r in window}
    cells = db.execute(select(Celula).where(
        Celula.igreja_id == igreja_id, Celula.id.in_(cell_ids),
    )).scalars().all() if cell_ids else []
    cell_by_id = {str(c.id): c for c in cells}
    leader_ids = {c.lider_id for c in cells if c.lider_id is not None}
    leaders = db.execute(select(Pessoa.id, Pessoa.nome).where(
        Pessoa.igreja_id == igreja_id, Pessoa.id.in_(leader_ids),
    )).all() if leader_ids else []
    names = {str(pid): nome for pid, nome in leaders}
    items = []
    for r in window:
        cell = cell_by_id.get(str(r.celula_id))
        items.append(PendingReportItem(
            reuniao_id=str(r.id), celula_id=str(r.celula_id), data=r.data.isoformat(),
            celula_nome=cell.nome if cell else "",
            lider_nome=names.get(str(cell.lider_id), "") if cell else "",
        ))

    return PendingReportsPage(items=items, page=page, page_size=page_size, total=total)


# ---------------------------------------------------------------------------
# GET /cell-central/health
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthOut)
def get_health(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(
        default=MAX_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Items per page (max 100)",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> HealthOut:
    """Saúde on-read das células (E6), menos saudáveis primeiro.

    Delega o cálculo a ``cell_health_service`` (últimas 10 reuniões, 3 sinais).
    Paginação opcional; por padrão devolve o conjunto completo (até 100).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    healths = cell_health_service.compute_cells_health(db, igreja_id)
    start = (page - 1) * page_size
    window = healths[start : start + page_size]

    return HealthOut(
        cells=[
            CellHealthOut(
                celula_id=h.celula_id,
                celula_nome=h.celula_nome,
                status=h.status,
                sinais=[
                    HealthSignalOut(reuniao_id=s.reuniao_id, cor=s.cor)
                    for s in h.sinais
                ],
                vermelhos=h.vermelhos,
                alertas=h.alertas,
            )
            for h in window
        ]
    )

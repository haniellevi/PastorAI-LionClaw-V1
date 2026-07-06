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
from sqlalchemy import select
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
from app.domain.cell_meetings_schedule import meeting_has_passed
from app.domain.cell_requests import STATUS_AGUARDANDO, TIPO_MULTIPLICACAO
from app.routers._common import ensure_tenant_context
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


# ---------------------------------------------------------------------------
# GET /cell-central/dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> DashboardOut:
    """Contadores operacionais da própria igreja (E16). Não paginado (resumo)."""
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)
    now = dt.datetime.now(dt.timezone.utc)
    recent_cutoff = now - dt.timedelta(days=RECENT_DAYS)

    # relatorios_pendentes — reuniões passadas não canceladas com relatório
    # não enviado.
    reunioes = db.execute(
        select(CelulaReuniao).where(CelulaReuniao.igreja_id == igreja_id)
    ).scalars().all()
    relatorios_pendentes = sum(
        1
        for r in reunioes
        if r.status != STATUS_CANCELADA
        and r.relatorio_status != RELATORIO_ENVIADO
        and meeting_has_passed(data=r.data, hora=r.hora)
    )

    # solicitacoes_aguardando / multiplicacoes_pendentes.
    solicitacoes = db.execute(
        select(CelulaSolicitacao).where(
            CelulaSolicitacao.igreja_id == igreja_id,
            CelulaSolicitacao.status == STATUS_AGUARDANDO,
        )
    ).scalars().all()
    solicitacoes_aguardando = len(solicitacoes)
    multiplicacoes_pendentes = sum(
        1 for s in solicitacoes if s.tipo == TIPO_MULTIPLICACAO
    )

    # celulas_com_alerta — células distintas com ≥1 vermelho OU alerta.
    healths = cell_health_service.compute_cells_health(
        db, igreja_id, now=now
    )
    celulas_com_alerta = sum(
        1 for h in healths if h.vermelhos > 0 or h.alertas > 0
    )

    # avisos_recentes / materiais_recentes — ativos publicados nos últimos 7 dias.
    avisos = db.execute(
        select(CelulaAviso).where(
            CelulaAviso.igreja_id == igreja_id,
            CelulaAviso.ativo.is_(True),
        )
    ).scalars().all()
    avisos_recentes = sum(
        1 for a in avisos if _is_recent(a.publicado_em, recent_cutoff)
    )
    materiais = db.execute(
        select(CelulaMaterial).where(
            CelulaMaterial.igreja_id == igreja_id,
            CelulaMaterial.ativo.is_(True),
        )
    ).scalars().all()
    materiais_recentes = sum(
        1 for m in materiais if _is_recent(m.publicado_em, recent_cutoff)
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
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)

    reunioes = db.execute(
        select(CelulaReuniao)
        .where(CelulaReuniao.igreja_id == igreja_id)
        .order_by(CelulaReuniao.data.asc(), CelulaReuniao.hora.asc())
    ).scalars().all()

    pending = [
        r
        for r in reunioes
        if r.status != STATUS_CANCELADA
        and r.relatorio_status == RELATORIO_PENDENTE
        and meeting_has_passed(data=r.data, hora=r.hora)
    ]

    start = (page - 1) * page_size
    window = pending[start : start + page_size]

    # Caches por célula p/ evitar consultas repetidas na janela.
    cell_cache: dict[uuid.UUID, Celula | None] = {}
    lider_cache: dict[uuid.UUID, str] = {}

    items: list[PendingReportItem] = []
    for r in window:
        cell = _resolve_cell(db, igreja_id, r.celula_id, cell_cache)
        celula_nome = cell.nome if cell is not None else ""
        lider_nome = _resolve_lider_nome(
            db, igreja_id, cell, lider_cache
        )
        items.append(
            PendingReportItem(
                reuniao_id=str(r.id),
                celula_id=str(r.celula_id),
                celula_nome=celula_nome,
                lider_nome=lider_nome,
                data=r.data.isoformat(),
            )
        )

    return PendingReportsPage(items=items, page=page, page_size=page_size)


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
    ensure_tenant_context(db, current_user)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_recent(published: dt.datetime | None, cutoff: dt.datetime) -> bool:
    """True se ``published`` é >= cutoff (tolerante a datetime naive/aware)."""
    if published is None:
        return False
    ref = published
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=dt.timezone.utc)
    return ref >= cutoff


def _resolve_cell(
    db: Session,
    igreja_id: uuid.UUID,
    celula_id: uuid.UUID,
    cache: dict[uuid.UUID, Celula | None],
) -> Celula | None:
    if celula_id not in cache:
        cache[celula_id] = db.execute(
            select(Celula).where(
                Celula.id == celula_id,
                Celula.igreja_id == igreja_id,
            )
        ).scalar_one_or_none()
    return cache[celula_id]


def _resolve_lider_nome(
    db: Session,
    igreja_id: uuid.UUID,
    cell: Celula | None,
    cache: dict[uuid.UUID, str],
) -> str:
    """Nome do líder via ``celulas.lider_id`` → ``pessoas.nome`` (§6.6)."""
    if cell is None or cell.lider_id is None:
        return ""
    if cell.lider_id not in cache:
        pessoa = db.execute(
            select(Pessoa).where(
                Pessoa.id == cell.lider_id,
                Pessoa.igreja_id == igreja_id,
            )
        ).scalar_one_or_none()
        cache[cell.lider_id] = pessoa.nome if pessoa is not None else ""
    return cache[cell.lider_id]

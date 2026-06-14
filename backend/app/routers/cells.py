"""Cells router — cells, alerts and leadership descendants (F7 / delta-007).

Endpoints:
  - GET  /cells                       paginated tenant cells
  - GET  /cells/{id}                  cell detail incl. its open alerts
  - POST /cells                       create or edit a cell (cobertura required)
  - POST /cells/{id}/alerts/{aid}/baixar  mark an alert as handled (tratado=true)
  - GET  /descendencias               leadership tree from pessoas.lider_id

Editing a cell (delta-007) is restricted to the cell's own leader, anyone above
that leader in the pessoas.lider_id chain, or a pastor/admin.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, CellAlert, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.hierarchy import is_leader_or_superior
from app.routers._common import Page, PaginationParams, ensure_tenant_context

logger = logging.getLogger("pastorai.cells")

router = APIRouter(tags=["cells"])

# Roles that may create a cell (admin always passes via has_any_role).
CELL_CREATE_ROLES = ["pastor", "lider_g12"]
# Roles treated as superior to any cell leader for edit authorization.
CELL_EDIT_SUPERIOR_ROLES = ["pastor"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AlertOut(BaseModel):
    id: str
    pessoaId: str  # noqa: N815
    gatilho: str | None = None
    acaoEsperada: str | None = None  # noqa: N815
    tratado: bool

    @classmethod
    def from_model(cls, a: CellAlert) -> "AlertOut":
        return cls(
            id=str(a.id),
            pessoaId=str(a.pessoa_id),
            gatilho=a.gatilho,
            acaoEsperada=a.acao_esperada,
            tratado=a.tratado,
        )


class CellOut(BaseModel):
    id: str
    nome: str
    liderId: str | None = None  # noqa: N815
    diaReuniao: str | None = None  # noqa: N815
    coberturaEspiritual: str  # noqa: N815
    ativo: bool

    @classmethod
    def from_model(cls, c: Celula) -> "CellOut":
        return cls(
            id=str(c.id),
            nome=c.nome,
            liderId=str(c.lider_id) if c.lider_id else None,
            diaReuniao=c.dia_reuniao,
            coberturaEspiritual=c.cobertura_espiritual,
            ativo=c.ativo,
        )


class CellDetailOut(CellOut):
    alerts: list[AlertOut] = []


class UpsertCellRequest(BaseModel):
    """Create (no id) or edit (with id) a cell. cobertura is mandatory."""

    id: str | None = None
    nome: str = Field(min_length=1, max_length=200)
    liderId: str | None = None  # noqa: N815
    diaReuniao: str | None = Field(default=None, max_length=40)  # noqa: N815
    coberturaEspiritual: str = Field(min_length=1, max_length=200)  # noqa: N815
    ativo: bool = True

    @field_validator("nome", "coberturaEspiritual")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatório")
        return value

    @field_validator("id", "liderId")
    @classmethod
    def _uuid_opt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("UUID inválido") from exc
        return value


class TreeNode(BaseModel):
    id: str
    nome: str
    tipo: str | None = None
    children: list["TreeNode"] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _actor_pessoa_id(db: Session, current_user: CurrentUser) -> str | None:
    """Resolve the acting user's linked pessoa_id (for hierarchy checks)."""
    pessoa_id = db.execute(
        select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id)
        )
    ).scalar_one_or_none()
    return str(pessoa_id) if pessoa_id else None


def _lider_of_map(db: Session) -> dict[str, str | None]:
    """Tenant-scoped pessoa_id -> lider_id mapping for hierarchy walks."""
    rows = db.execute(select(Pessoa.id, Pessoa.lider_id)).all()
    return {str(pid): (str(lid) if lid else None) for pid, lid in rows}


def _can_edit_cell(
    db: Session, current_user: CurrentUser, cell: Celula
) -> bool:
    """delta-007: leader of the cell, a superior in the chain, or pastor/admin."""
    if current_user.has_any_role(CELL_EDIT_SUPERIOR_ROLES):
        return True  # admin is covered by has_any_role's implicit access
    actor = _actor_pessoa_id(db, current_user)
    return is_leader_or_superior(
        actor_pessoa_id=actor,
        cell_leader_id=str(cell.lider_id) if cell.lider_id else None,
        lider_of=_lider_of_map(db),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/cells", response_model=Page[CellOut])
def list_cells(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[CellOut]:
    """List the tenant's cells, paginated."""
    ensure_tenant_context(db, current_user)
    total = db.execute(select(func.count()).select_from(Celula)).scalar_one()
    rows = db.execute(
        select(Celula)
        .order_by(Celula.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()
    return Page[CellOut](
        items=[CellOut.from_model(c) for c in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.get("/cells/{cell_id}", response_model=CellDetailOut)
def get_cell(
    cell_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellDetailOut:
    """Return a cell with its open alerts."""
    ensure_tenant_context(db, current_user)
    cell = _get_cell_or_404(db, cell_id)

    alerts = db.execute(
        select(CellAlert)
        .where(CellAlert.celula_id == cell.id, CellAlert.tratado.is_(False))
        .order_by(CellAlert.created_at.desc())
    ).scalars().all()

    detail = CellDetailOut.from_model(cell)
    detail.alerts = [AlertOut.from_model(a) for a in alerts]
    return detail


@router.post("/cells", response_model=CellOut)
def upsert_cell(
    payload: UpsertCellRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellOut:
    """Create a new cell or edit an existing one.

    cobertura_espiritual is mandatory (validated at the edge). Editing requires
    leader-or-superior authorization (delta-007); creating requires a pastoral
    leadership role.
    """
    ensure_tenant_context(db, current_user)

    if payload.id is None:
        if not current_user.has_any_role(CELL_CREATE_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para criar células",
            )
        cell = Celula(
            igreja_id=uuid.UUID(current_user.igreja_id),
            nome=payload.nome,
            lider_id=uuid.UUID(payload.liderId) if payload.liderId else None,
            dia_reuniao=payload.diaReuniao,
            cobertura_espiritual=payload.coberturaEspiritual,
            ativo=payload.ativo,
        )
        db.add(cell)
        db.flush()
        db.refresh(cell)
        db.commit()
        return CellOut.from_model(cell)

    # Edit path.
    cell = _get_cell_or_404(db, payload.id)
    if not _can_edit_cell(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o líder da célula ou um superior pode editá-la",
        )
    cell.nome = payload.nome
    cell.lider_id = uuid.UUID(payload.liderId) if payload.liderId else None
    cell.dia_reuniao = payload.diaReuniao
    cell.cobertura_espiritual = payload.coberturaEspiritual
    cell.ativo = payload.ativo
    db.flush()
    db.refresh(cell)
    db.commit()
    return CellOut.from_model(cell)


@router.post("/cells/{cell_id}/alerts/{alert_id}/baixar", response_model=AlertOut)
def baixar_alert(
    cell_id: str,
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AlertOut:
    """Mark a cell alert as handled (tratado=true)."""
    ensure_tenant_context(db, current_user)
    cell = _get_cell_or_404(db, cell_id)
    if not _can_edit_cell(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissão para tratar alertas desta célula",
        )

    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado"
        ) from exc

    alert = db.execute(
        select(CellAlert).where(
            CellAlert.id == alert_uuid, CellAlert.celula_id == cell.id
        )
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado"
        )

    alert.tratado = True
    db.flush()
    db.refresh(alert)
    db.commit()
    return AlertOut.from_model(alert)


@router.get("/descendencias", response_model=list[TreeNode])
def descendencias(
    root_id: str | None = Query(default=None, alias="rootId"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[TreeNode]:
    """Return the leadership tree built from pessoas.lider_id.

    By default the tree is rooted at the acting user's linked person (their
    downline). An explicit ?rootId= overrides it. When no root can be resolved,
    the full forest (people with no leader) is returned.
    """
    ensure_tenant_context(db, current_user)

    rows = db.execute(
        select(Pessoa.id, Pessoa.nome, Pessoa.tipo, Pessoa.lider_id)
    ).all()

    # node lookup and parent -> children adjacency.
    info: dict[str, tuple[str, str | None]] = {}
    children: dict[str | None, list[str]] = {}
    for pid, nome, tipo, lider_id in rows:
        spid = str(pid)
        info[spid] = (nome, tipo)
        key = str(lider_id) if lider_id else None
        children.setdefault(key, []).append(spid)

    def build(node_id: str) -> TreeNode:
        nome, tipo = info[node_id]
        return TreeNode(
            id=node_id,
            nome=nome,
            tipo=tipo,
            children=[build(cid) for cid in children.get(node_id, [])],
        )

    resolved_root = root_id or _actor_pessoa_id(db, current_user)
    if resolved_root:
        return [build(resolved_root)] if resolved_root in info else []

    # No root: return the forest of top-level people (lider_id is null).
    return [build(pid) for pid in children.get(None, [])]


def _get_cell_or_404(db: Session, cell_id: str) -> Celula:
    try:
        cell_uuid = uuid.UUID(cell_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        ) from exc
    cell = db.execute(
        select(Celula).where(Celula.id == cell_uuid)
    ).scalar_one_or_none()
    if cell is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        )
    return cell

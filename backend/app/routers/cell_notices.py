"""Avisos de célula/Central — publicação, leitura e inativação (Células PR3-PR9).

Dois autores possíveis, decididos SEMPRE server-side pelo papel autenticado:

  - Líder de célula → ``origem='celula'`` / ``escopo='celula'`` APENAS da própria
    célula (403 se tentar broadcast de igreja; 404 se a célula não for sua).
  - Central (pastor/admin) → ``origem='central'`` com ``escopo`` 'celula' ou
    'igreja'. A autoria é validada no servidor — nunca vem do payload.

Alcance de leitura (E15):
  - ``escopo='igreja'`` → todos os autenticados da igreja (RLS já escopa o tenant);
  - ``escopo='celula'`` → apenas membros ATIVOS + líder daquela célula + Central.

Sem edição no MVP: DELETE apenas INATIVA (``ativo=false``) quando a autoria é
compatível. A publicação aciona o ponto de extensão de notificação
(``cell_notify``), que hoje é NO-OP (nenhum WhatsApp/Evolution é tocado).
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaAviso, CelulaMembro
from app.db.session import get_db
from app.deps import (
    CENTRAL_ROLES,
    CurrentUser,
    get_current_cell_for_leader,
    get_current_user,
    resolve_actor_pessoa_id,
)
from app.routers._common import ensure_tenant_context
from app.services import cell_notify

router = APIRouter(prefix="/cell-notices", tags=["cell-notices"])

# Origem/escopo canônicos (espelham celula_aviso.origem/escopo).
ORIGEM_CENTRAL = "central"
ORIGEM_CELULA = "celula"
ESCOPO_CELULA = "celula"
ESCOPO_IGREJA = "igreja"

# Paginação (contrato snake_case): padrão 20, máx 100.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreateNoticeRequest(BaseModel):
    """Corpo de publicação. ``origem`` NUNCA vem do cliente (derivada do papel)."""

    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1, max_length=200)
    conteudo: str = Field(min_length=1, max_length=5000)
    escopo: str | None = None
    celula_id: str | None = None


class NoticeOut(BaseModel):
    """Contrato de saída em snake_case (espelha as colunas relevantes)."""

    id: str
    origem: str
    escopo: str
    celula_id: str | None = None
    titulo: str
    conteudo: str
    ativo: bool
    publicado_em: dt.datetime | None = None
    notificado_em: dt.datetime | None = None

    @classmethod
    def from_model(cls, a: CelulaAviso) -> "NoticeOut":
        return cls(
            id=str(a.id),
            origem=a.origem,
            escopo=a.escopo,
            celula_id=str(a.celula_id) if a.celula_id else None,
            titulo=a.titulo,
            conteudo=a.conteudo,
            ativo=a.ativo,
            publicado_em=a.publicado_em,
            notificado_em=a.notificado_em,
        )


class NoticePage(BaseModel):
    items: list[NoticeOut]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_cell(db: Session, igreja_id: uuid.UUID, cell_id: str) -> Celula:
    """Carrega a célula do tenant ou 404 (id malformado também → 404)."""
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
    )
    try:
        cell_uuid = uuid.UUID(cell_id)
    except (ValueError, AttributeError) as exc:
        raise not_found from exc
    cell = db.execute(
        select(Celula).where(
            Celula.id == cell_uuid, Celula.igreja_id == igreja_id
        )
    ).scalar_one_or_none()
    if cell is None:
        raise not_found
    return cell


def _load_notice(
    db: Session, igreja_id: uuid.UUID, notice_id: str
) -> CelulaAviso:
    """Carrega o aviso do tenant ou 404 (id malformado também → 404)."""
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Aviso não encontrado"
    )
    try:
        notice_uuid = uuid.UUID(notice_id)
    except (ValueError, AttributeError) as exc:
        raise not_found from exc
    aviso = db.execute(
        select(CelulaAviso).where(
            CelulaAviso.id == notice_uuid,
            CelulaAviso.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()
    if aviso is None:
        raise not_found
    return aviso


def _visible_cell_ids(
    db: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> set[uuid.UUID]:
    """Células cujos avisos 'celula' o usuário pode ler: onde é membro ativo OU líder."""
    ids: set[uuid.UUID] = set()
    memberships = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.ativo.is_(True),
        )
    ).scalars().all()
    for m in memberships:
        ids.add(m.celula_id)
    led = db.execute(
        select(Celula).where(
            Celula.igreja_id == igreja_id,
            Celula.lider_id == pessoa_id,
        )
    ).scalars().all()
    for c in led:
        ids.add(c.id)
    return ids


# ---------------------------------------------------------------------------
# POST /cell-notices
# ---------------------------------------------------------------------------
@router.post("", response_model=NoticeOut, status_code=status.HTTP_201_CREATED)
def publish_notice(
    payload: CreateNoticeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> NoticeOut:
    """Publica um aviso. Autoria (origem/escopo/célula) é decidida no servidor.

    - Central (pastor/admin): ``origem='central'``; ``escopo`` ∈ {celula, igreja}.
      Escopo 'celula' exige ``celula_id`` válido no tenant.
    - Líder: ``origem='celula'``/``escopo='celula'`` apenas da PRÓPRIA célula
      (403 se tentar escopo 'igreja'; 404 se a célula não for sua).

    A publicação registra a intenção de notificar (``cell_notify``, NO-OP) na
    MESMA transação — sem envio real de WhatsApp/Evolution (RNF-09/20).
    """
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)
    is_central = current_user.has_any_role(CENTRAL_ROLES)

    titulo = payload.titulo.strip()
    conteudo = payload.conteudo.strip()
    if not titulo or not conteudo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="titulo e conteudo são obrigatórios",
        )

    actor = resolve_actor_pessoa_id(db, current_user)
    autor_id = uuid.UUID(actor) if actor else None

    if is_central:
        escopo = (payload.escopo or "").strip().lower()
        if escopo not in (ESCOPO_CELULA, ESCOPO_IGREJA):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="escopo deve ser 'celula' ou 'igreja'",
            )
        origem = ORIGEM_CENTRAL
        if escopo == ESCOPO_CELULA:
            if not payload.celula_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="celula_id é obrigatório para escopo 'celula'",
                )
            celula_id: uuid.UUID | None = _load_cell(
                db, igreja_id, payload.celula_id
            ).id
        else:
            celula_id = None
    else:
        # Líder: só publica na própria célula, escopo 'celula'. Broadcast de
        # igreja é exclusivo da Central.
        requested_escopo = (payload.escopo or ESCOPO_CELULA).strip().lower()
        if requested_escopo != ESCOPO_CELULA:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas a Central publica avisos para a igreja",
            )
        if not payload.celula_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="celula_id é obrigatório",
            )
        # 404 (não 403) quando a célula não é do líder — não vaza existência.
        cell = get_current_cell_for_leader(db, current_user, payload.celula_id)
        origem = ORIGEM_CELULA
        escopo = ESCOPO_CELULA
        celula_id = cell.id

    aviso = CelulaAviso(
        igreja_id=igreja_id,
        celula_id=celula_id,
        autor_id=autor_id,
        origem=origem,
        escopo=escopo,
        titulo=titulo,
        conteudo=conteudo,
        ativo=True,
        publicado_em=dt.datetime.now(dt.timezone.utc),
    )
    db.add(aviso)
    db.flush()
    # Ponto de extensão NO-OP: carimba notificado_em, sem envio real.
    cell_notify.notify_notice_published(db, aviso)
    db.refresh(aviso)
    db.commit()
    return NoticeOut.from_model(aviso)


# ---------------------------------------------------------------------------
# GET /cell-notices
# ---------------------------------------------------------------------------
@router.get("", response_model=NoticePage)
def list_notices(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Items per page (max 100)",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> NoticePage:
    """Lista avisos ativos aplicando o alcance E15 (mais recentes primeiro).

    Escopo 'igreja' é visível a todos na igreja; escopo 'celula' só a membros
    ativos/líder daquela célula e à Central. Apenas ``ativo=true``. Paginado.
    """
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)
    is_central = current_user.has_any_role(CENTRAL_ROLES)

    visible_cells: set[uuid.UUID] = set()
    if not is_central:
        actor = resolve_actor_pessoa_id(db, current_user)
        if actor is not None:
            visible_cells = _visible_cell_ids(
                db, igreja_id, uuid.UUID(actor)
            )

    rows = db.execute(
        select(CelulaAviso)
        .where(
            CelulaAviso.igreja_id == igreja_id,
            CelulaAviso.ativo.is_(True),
        )
        .order_by(CelulaAviso.publicado_em.desc())
    ).scalars().all()

    visible: list[CelulaAviso] = []
    for a in rows:
        if a.escopo == ESCOPO_IGREJA:
            pass
        elif a.escopo == ESCOPO_CELULA and (
            is_central or a.celula_id in visible_cells
        ):
            pass
        else:
            continue
        visible.append(a)

    total = len(visible)
    start = (page - 1) * page_size
    window = visible[start : start + page_size]
    return NoticePage(
        items=[NoticeOut.from_model(a) for a in window],
        page=page,
        page_size=page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# DELETE /cell-notices/{notice_id}
# ---------------------------------------------------------------------------
@router.delete("/{notice_id}", response_model=NoticeOut)
def remove_notice(
    notice_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> NoticeOut:
    """Inativa (``ativo=false``) um aviso quando a autoria é compatível.

    - Central (pastor/admin) gere qualquer aviso da igreja;
    - Líder só inativa avisos da PRÓPRIA célula (404 se não for sua);
    - demais papéis: 403.

    Sem edição no MVP. Idempotente em ``ativo=false``. Aciona o ponto de
    extensão de remoção (``cell_notify``, NO-OP — nada é entregue).
    """
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)
    is_central = current_user.has_any_role(CENTRAL_ROLES)

    aviso = _load_notice(db, igreja_id, notice_id)

    if is_central:
        pass
    elif aviso.origem == ORIGEM_CELULA and aviso.celula_id is not None:
        # 404 quando a célula do aviso não é do líder — não vaza existência.
        get_current_cell_for_leader(db, current_user, str(aviso.celula_id))
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para inativar este aviso",
        )

    if aviso.ativo:
        aviso.ativo = False
        aviso.updated_at = dt.datetime.now(dt.timezone.utc)
        cell_notify.notify_notice_removed(db, aviso)
        db.flush()
        db.refresh(aviso)
        db.commit()

    return NoticeOut.from_model(aviso)

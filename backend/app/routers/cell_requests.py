"""Solicitações de célula — criação, listagem e ciclo de decisão (Células PR3-PR9).

O líder de uma célula ABRE solicitações (campo sensível de célula / multiplicação);
a Central de Células DECIDE (aprova como está, rejeita ou pede ajuste). O líder
autor pode reenviar (quando em `ajuste_solicitado`) ou cancelar (enquanto aberta).
Toda transição grava a trilha append-only na MESMA transação (delegado ao
`cell_requests_service`).

M7B-W1.3: transferência/remoção de membro NÃO nascem na tela do líder (Minha
Célula) — a gestão de membros é atribuição da Central de Célula. A criação/reenvio
desses tipos é barrada aqui (403), sem afetar a DECISÃO da Central sobre eventuais
solicitações legadas nem os fluxos administrativos da Central.

Contrato de saída em snake_case (espelha as colunas): `celula_id`,
`payload_proposto`, `observacao_central`, `created_at`, `decidido_em`… A Central
NUNCA edita o payload (SPEC §3.6). Criação nasce `aguardando`, NÃO altera o dado
real e barra (409) uma segunda solicitação aberta conflitante (matriz E13/§6.8).
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Pessoa,
    Celula,
    CelulaSolicitacao,
    CelulaSolicitacaoEvento,
)
from app.db.session import get_db
from app.deps import (
    CurrentUser,
    get_current_cell_for_leader,
    get_current_user,
    require_central,
    resolve_actor_pessoa_id,
)
from app.domain.cell_requests import (
    TIPO_ABRIR_CELULA,
    InvalidPayload,
    validate_payload,
)
from app.routers._common import Page, PaginationParams
from app.services import cell_requests_service
from app.services.cell_request_contract import (
    CellRequestOut,
    _PG_UNIQUE_VIOLATION,
    _has_open_conflict,
    _reject_member_tipo,
    _require_requests_enabled,
)

router = APIRouter(prefix="/cell-requests", tags=["cell-requests"])

# ---------------------------------------------------------------------------
# Schemas de entrada
# ---------------------------------------------------------------------------
class CreateCellRequest(BaseModel):
    """Corpo de criação: origem + tipo + payload proposto (validado por tipo)."""

    model_config = ConfigDict(extra="forbid")

    celula_id: str | None = None
    tipo: str
    payload_proposto: dict | None = None
    motivo: str | None = None


class ResubmitRequest(BaseModel):
    """Reenvio do líder autor (edita o payload, mesmo `tipo`)."""

    model_config = ConfigDict(extra="forbid")

    payload_proposto: dict | None = None


class ApproveRequest(BaseModel):
    """Aprovação da Central. `idempotency_key` só é exigido em multiplicação."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str | None = None
    confirmar_execucao: bool = False
    versao_proposta: int | None = None


class DecisionRequest(BaseModel):
    """Rejeição / pedido de ajuste — `observacao_central` obrigatória."""

    model_config = ConfigDict(extra="forbid")

    observacao_central: str | None = None


class CellRequestEventOut(BaseModel):
    id: str
    acao: str
    autor_id: str | None = None
    de_status: str | None = None
    para_status: str | None = None
    observacao: str | None = None
    payload_snapshot: dict
    created_at: dt.datetime | None = None

    @classmethod
    def from_model(cls, e: CelulaSolicitacaoEvento) -> "CellRequestEventOut":
        return cls(
            id=str(e.id),
            acao=e.acao,
            autor_id=str(e.autor_id) if e.autor_id else None,
            de_status=e.de_status,
            para_status=e.para_status,
            observacao=e.observacao,
            payload_snapshot=e.payload_snapshot or {},
            created_at=e.created_at,
        )


class CellRequestDetailOut(CellRequestOut):
    eventos: list[CellRequestEventOut]

    @classmethod
    def from_models(
        cls,
        s: CelulaSolicitacao,
        eventos: list[CelulaSolicitacaoEvento],
        db: Session | None = None,
    ) -> "CellRequestDetailOut":
        base = CellRequestOut.from_model(s, db)
        return cls(
            **base.model_dump(),
            eventos=[CellRequestEventOut.from_model(e) for e in eventos],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_solicitacao(
    db: Session, igreja_id: uuid.UUID, request_id: str
) -> CelulaSolicitacao:
    """Carrega a solicitação do tenant ou 404 (id malformado também → 404)."""
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação não encontrada"
    )
    try:
        request_uuid = uuid.UUID(request_id)
    except (ValueError, AttributeError) as exc:
        raise not_found from exc
    solicitacao = db.execute(
        select(CelulaSolicitacao).where(
            CelulaSolicitacao.id == request_uuid,
            CelulaSolicitacao.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()
    if solicitacao is None:
        raise not_found
    return solicitacao


def _load_events(
    db: Session, solicitacao: CelulaSolicitacao
) -> list[CelulaSolicitacaoEvento]:
    return list(
        db.execute(
            select(CelulaSolicitacaoEvento)
            .where(CelulaSolicitacaoEvento.solicitacao_id == solicitacao.id)
            .order_by(CelulaSolicitacaoEvento.created_at.asc())
        ).scalars().all()
    )


def _assert_author(
    db: Session, solicitacao: CelulaSolicitacao, current_user: CurrentUser
) -> uuid.UUID | None:
    """Exige que o usuário autenticado seja o autor (solicitante) — senão 404.

    404 (não 403) para não revelar a existência de solicitações de outros líderes.
    """
    actor = resolve_actor_pessoa_id(db, current_user)
    if (
        actor is None
        or solicitacao.solicitante_id is None
        or str(solicitacao.solicitante_id) != actor
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitação não encontrada",
        )
    return uuid.UUID(actor)


# ---------------------------------------------------------------------------
# Criação e leitura
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=CellRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_requests_enabled)],
)
def create_cell_request(
    body: CreateCellRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellRequestOut:
    from app.services.cell_request_creation import create_request
    try:
        result = create_request(db, current_user, body)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise


@router.get("", response_model=Page[CellRequestOut])
def list_cell_requests(
    pagination: PaginationParams = Depends(),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[CellRequestOut]:
    """Lista solicitações: Central vê as da igreja; líder vê apenas as SUAS.

    A distinção é derivada do papel autenticado — a Central (pastor/admin) enxerga
    toda a igreja; os demais são escopados por `solicitante_id`. `?status` filtra.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    filters = [CelulaSolicitacao.igreja_id == igreja_id]
    if not current_user.has_any_role(["pastor"]):
        actor = resolve_actor_pessoa_id(db, current_user)
        if actor is None:
            return Page[CellRequestOut](
                items=[],
                page=pagination.page,
                pageSize=pagination.page_size,
                total=0,
            )
        filters.append(CelulaSolicitacao.solicitante_id == uuid.UUID(actor))

    if status_filter is not None:
        normalized = status_filter.strip().lower()
        filters.append(CelulaSolicitacao.status == normalized)

    total = db.execute(
        select(func.count()).select_from(CelulaSolicitacao).where(*filters)
    ).scalar_one()
    rows = db.execute(
        select(CelulaSolicitacao)
        .where(*filters)
        .order_by(CelulaSolicitacao.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    return Page[CellRequestOut](
        items=[CellRequestOut.from_model(s, db) for s in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.get("/{request_id}", response_model=CellRequestDetailOut)
def get_cell_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellRequestDetailOut:
    """Detalhe da solicitação + trilha de eventos (ordenada por created_at).

    A Central vê qualquer solicitação da igreja; o líder só as suas (404 senão).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    solicitacao = _load_solicitacao(db, igreja_id, request_id)
    if not current_user.has_any_role(["pastor"]):
        actor = resolve_actor_pessoa_id(db, current_user)
        if (
            actor is None
            or solicitacao.solicitante_id is None
            or str(solicitacao.solicitante_id) != actor
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitação não encontrada",
            )

    eventos = _load_events(db, solicitacao)
    return CellRequestDetailOut.from_models(solicitacao, eventos, db)


# ---------------------------------------------------------------------------
# Ações do líder autor (reenviar / cancelar)
# ---------------------------------------------------------------------------
@router.put(
    "/{request_id}/resubmit",
    response_model=CellRequestOut,
    dependencies=[Depends(_require_requests_enabled)],
)
def resubmit_cell_request(
    request_id: str,
    body: ResubmitRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellRequestOut:
    """Líder autor edita o payload e reenvia (só em `ajuste_solicitado` → 409)."""
    igreja_id = uuid.UUID(current_user.igreja_id)

    solicitacao = _load_solicitacao(db, igreja_id, request_id)
    actor_pessoa_id = _assert_author(db, solicitacao, current_user)

    # Reenvio de transferir/remover membro também é barrado (legado; W1.3).
    _reject_member_tipo(solicitacao.tipo)

    try:
        new_payload = validate_payload(solicitacao.tipo, body.payload_proposto)
    except InvalidPayload as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    updated = cell_requests_service.resubmit(
        db,
        solicitacao=solicitacao,
        actor_pessoa_id=actor_pessoa_id,
        new_payload=new_payload,
        author_app_user_id=uuid.UUID(current_user.app_user_id),
    )
    return CellRequestOut.from_model(updated, db)


@router.post(
    "/{request_id}/cancel",
    response_model=CellRequestOut,
    dependencies=[Depends(_require_requests_enabled)],
)
def cancel_cell_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellRequestOut:
    """Líder autor cancela a própria solicitação (só enquanto aberta — E12)."""
    igreja_id = uuid.UUID(current_user.igreja_id)

    solicitacao = _load_solicitacao(db, igreja_id, request_id)
    actor_pessoa_id = _assert_author(db, solicitacao, current_user)

    updated = cell_requests_service.cancel(
        db, solicitacao=solicitacao, actor_pessoa_id=actor_pessoa_id
    )
    return CellRequestOut.from_model(updated, db)


# ---------------------------------------------------------------------------
# Decisão da Central (aprovar / rejeitar / pedir ajuste)
# ---------------------------------------------------------------------------
@router.post(
    "/{request_id}/approve",
    response_model=CellRequestOut,
    dependencies=[Depends(_require_requests_enabled)],
)
def approve_cell_request(
    request_id: str,
    body: ApproveRequest | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> CellRequestOut:
    """Central aprova (sem editar o payload): aplica em transação única + auditoria.

    Multiplicação exige `idempotency_key` (do corpo ou do payload) e é idempotente
    (reprocesso não duplica). Falha parcial → rollback total. Segregação 3.1: quem
    originou a solicitação não pode aprová-la.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    solicitacao = _load_solicitacao(db, igreja_id, request_id)
    _assert_not_author(db, solicitacao, current_user)
    cell = None if solicitacao.tipo == TIPO_ABRIR_CELULA else _load_solicitacao_cell(db, igreja_id, solicitacao)

    actor_pessoa_id = _actor_uuid(db, current_user)
    body_key = (body.idempotency_key if body else None) or ""
    payload_key = str((solicitacao.payload_proposto or {}).get("idempotency_key") or "")
    idempotency_key = body_key.strip() or payload_key.strip() or None

    updated = cell_requests_service.approve(
        db,
        solicitacao=solicitacao,
        cell=cell,
        actor_pessoa_id=actor_pessoa_id,
        approver_app_user_id=uuid.UUID(current_user.app_user_id),
        idempotency_key=idempotency_key,
        confirmar_execucao=body.confirmar_execucao if body else False,
        versao_proposta=body.versao_proposta if body else None,
    )
    return CellRequestOut.from_model(updated, db)


@router.post(
    "/{request_id}/reject",
    response_model=CellRequestOut,
    dependencies=[Depends(_require_requests_enabled)],
)
def reject_cell_request(
    request_id: str,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> CellRequestOut:
    """Central rejeita — `observacao_central` obrigatória (422 se ausente).

    Segregação 3.1: quem originou a solicitação não pode decidi-la.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    observacao = _require_observacao(body)
    solicitacao = _load_solicitacao(db, igreja_id, request_id)
    _assert_not_author(db, solicitacao, current_user)
    actor_pessoa_id = _actor_uuid(db, current_user)

    updated = cell_requests_service.reject(
        db,
        solicitacao=solicitacao,
        actor_pessoa_id=actor_pessoa_id,
        observacao_central=observacao,
        approver_app_user_id=uuid.UUID(current_user.app_user_id),
    )
    return CellRequestOut.from_model(updated, db)


@router.post(
    "/{request_id}/request-adjustment",
    response_model=CellRequestOut,
    dependencies=[Depends(_require_requests_enabled)],
)
def request_adjustment_cell_request(
    request_id: str,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> CellRequestOut:
    """Central devolve para ajuste — `observacao_central` obrigatória (422).

    Segregação 3.1: quem originou a solicitação não pode decidi-la.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    observacao = _require_observacao(body)
    solicitacao = _load_solicitacao(db, igreja_id, request_id)
    _assert_not_author(db, solicitacao, current_user)
    actor_pessoa_id = _actor_uuid(db, current_user)

    updated = cell_requests_service.request_adjustment(
        db,
        solicitacao=solicitacao,
        actor_pessoa_id=actor_pessoa_id,
        observacao_central=observacao,
        approver_app_user_id=uuid.UUID(current_user.app_user_id),
    )
    return CellRequestOut.from_model(updated, db)


# ---------------------------------------------------------------------------
# Helpers de decisão
# ---------------------------------------------------------------------------
def _actor_uuid(db: Session, current_user: CurrentUser) -> uuid.UUID | None:
    actor = resolve_actor_pessoa_id(db, current_user)
    return uuid.UUID(actor) if actor else None


def _assert_not_author(
    db: Session, solicitacao: CelulaSolicitacao, current_user: CurrentUser
) -> None:
    """Segregação de funções (decisão 3.1): quem origina não decide.

    Um pastor/admin que também seja o líder AUTOR da solicitação não pode
    aprová-la/rejeitá-la/devolvê-la — outra pessoa da Central decide. Derivado do
    contexto autenticado (nunca do payload); 403.
    """
    actor = resolve_actor_pessoa_id(db, current_user)
    if (
        actor is not None
        and solicitacao.solicitante_id is not None
        and str(solicitacao.solicitante_id) == actor
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quem originou a solicitação não pode decidi-la (segregação 3.1)",
        )


def _require_observacao(body: DecisionRequest) -> str:
    observacao = (body.observacao_central or "").strip()
    if not observacao:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="observacao_central é obrigatória",
        )
    return observacao


def _load_solicitacao_cell(
    db: Session, igreja_id: uuid.UUID, solicitacao: CelulaSolicitacao
) -> Celula:
    cell = db.execute(
        select(Celula).where(
            Celula.id == solicitacao.celula_id,
            Celula.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()
    if cell is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Célula de origem não encontrada",
        )
    return cell

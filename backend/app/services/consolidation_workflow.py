"""Transactional V3 consolidation actions shared by panel and WhatsApp.

Callers own commit and rollback. Panel/S3 assignment locks the track, then the
target account/person and role rows, then linked queue rows by id. A queue
action locks the track and linked queue rows before its target/holder checks,
so it can fence the candidate read that preceded the canonical lock. Completion
locks the track and linked queue rows by id. The stable track-to-task order
prevents assignment and fonovisita completion from splitting canonical state.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal
import uuid

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Consolidacao,
    ConsolidacaoEtapa,
    Pessoa,
    UserRole,
    WorkQueueItem,
)
from app.deps import CurrentUser
from app.domain.consolidation import (
    CONSOLIDATION_ROLES,
    can_conclude,
    compute_progresso,
    is_valid_etapa,
    pending_mandatory,
)
from app.domain.pipeline import PIPELINE_WRITE_ROLES
from app.domain.work_queue import can_resolve, has_tenant_queue_scope
from app.services.consolidation_whatsapp import CONSOLIDATION_WHATSAPP_ROLES


_ACTIVE_QUEUE_STATUSES = ("aberto", "assumido")
_WHATSAPP_TARGET_ROLES = tuple(sorted(CONSOLIDATION_WHATSAPP_ROLES))
_QUEUE_ACTIONS = frozenset({"assume", "assign"})


@dataclass(frozen=True)
class AssignmentResult:
    consolidacao: Consolidacao
    work_items: tuple[WorkQueueItem, ...]


@dataclass(frozen=True)
class FonovisitaCompletion:
    consolidacao: Consolidacao
    work_queue_item: WorkQueueItem


@dataclass(frozen=True)
class StageAdvanceResult:
    consolidacao: Consolidacao
    etapas_pendentes: tuple[str, ...]


def assign_consolidacao(
    db: Session,
    current_user: CurrentUser,
    *,
    consolidacao_id: uuid.UUID,
    responsavel_id: uuid.UUID,
    expected_assignment_revision: int | None,
    whatsapp: bool,
    expected_work_queue_item_id: uuid.UUID | None = None,
    work_queue_action: Literal["assume", "assign"] | None = None,
) -> AssignmentResult:
    """Assign an eligible responsible and synchronize every open linked task.

    The optional revision is mandatory for confirmed WhatsApp actions and
    detects stale or ABA proposals. Panel callers pass ``None`` because their
    row lock is the current interactive intent.
    """

    _require_bool(whatsapp)
    _validate_revision(expected_assignment_revision, required=whatsapp)
    _validate_queue_action(
        expected_work_queue_item_id=expected_work_queue_item_id,
        work_queue_action=work_queue_action,
    )
    tenant = _tenant_id(current_user)
    consolidacao = _lock_consolidacao(db, tenant, consolidacao_id)
    _ensure_open(consolidacao)
    _require_expected_revision(consolidacao, expected_assignment_revision)
    if work_queue_action is None:
        _require_assignment_actor(current_user)
        target_id = _resolve_assignment_target(
            db,
            tenant,
            responsavel_id,
            whatsapp=whatsapp,
        )
        work_items = _lock_linked_work_items(db, tenant, consolidacao.id)
    else:
        if whatsapp:
            raise TypeError("ação de fila não é permitida pelo WhatsApp")
        work_items = _lock_linked_work_items(db, tenant, consolidacao.id)
        expected_item = _require_active_queue_candidate(
            work_items,
            expected_work_queue_item_id,
        )
        _require_queue_action_actor(
            current_user,
            item_tipo=expected_item.tipo,
            action=work_queue_action,
        )
        target_id = _resolve_queue_target(
            db,
            tenant,
            current_user,
            responsavel_id,
            expected_item.tipo,
            action=work_queue_action,
        )
        if _queue_action_is_idempotent_or_conflicts(
            db,
            tenant,
            expected_item,
            target_id,
            action=work_queue_action,
        ):
            return AssignmentResult(
                consolidacao=consolidacao,
                work_items=tuple(work_items),
            )

    consolidacao.responsavel_id = target_id
    for item in work_items:
        if _is_active_queue_item(item):
            item.responsavel_id = target_id
            item.status = "assumido"

    db.flush()
    db.refresh(consolidacao)
    return AssignmentResult(consolidacao=consolidacao, work_items=tuple(work_items))


def complete_fonovisita(
    db: Session,
    current_user: CurrentUser,
    *,
    consolidacao_id: uuid.UUID,
    work_queue_item_id: uuid.UUID,
    expected_assignment_revision: int | None,
    whatsapp: bool,
) -> FonovisitaCompletion:
    """Resolve one canonical fonovisita and its stage in the same transaction."""

    _require_bool(whatsapp)
    _validate_revision(expected_assignment_revision, required=whatsapp)
    tenant = _tenant_id(current_user)
    consolidacao = _lock_consolidacao(db, tenant, consolidacao_id)
    _ensure_open(consolidacao)
    _require_expected_revision(consolidacao, expected_assignment_revision)
    if whatsapp and not can_resolve(current_user.roles, "fonovisita"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para confirmar fonovisita",
        )
    if (
        consolidacao.responsavel_id is None
        or str(consolidacao.responsavel_id) != current_user.app_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o consolidador responsável pode confirmar etapas",
        )

    work_items = _lock_linked_work_items(db, tenant, consolidacao.id)
    work_item = next(
        (
            item
            for item in work_items
            if item.id == work_queue_item_id and item.tipo == "fonovisita"
        ),
        None,
    )
    if work_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pendência de fonovisita não encontrada",
        )
    if work_item.status == "resolvido" and whatsapp:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fonovisita já foi resolvida",
        )
    if not _is_active_queue_item(work_item) and work_item.status != "resolvido":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pendência de fonovisita não está ativa",
        )

    etapa = _lock_stage(db, tenant, consolidacao.id, "fonovisita")
    if etapa is None:
        etapa = ConsolidacaoEtapa(
            igreja_id=tenant,
            consolidacao_id=consolidacao.id,
            etapa="fonovisita",
        )
        db.add(etapa)
    etapa.concluida = True
    etapa.confirmada_por = uuid.UUID(current_user.app_user_id)
    etapa.confirmada_em = dt.datetime.now(dt.UTC)
    work_item.status = "resolvido"

    db.flush()
    _refresh_progress(db, consolidacao)
    db.flush()
    db.refresh(consolidacao)
    return FonovisitaCompletion(
        consolidacao=consolidacao,
        work_queue_item=work_item,
    )


def advance_consolidacao_stage(
    db: Session,
    current_user: CurrentUser,
    *,
    consolidacao_id: uuid.UUID,
    etapa: str | None,
    concluir: bool,
) -> StageAdvanceResult:
    """Panel-only stage progression, including the legacy conclude combination."""

    if etapa is None and not concluir:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe etapa para confirmar ou concluir=true",
        )
    if etapa is not None and not is_valid_etapa(etapa):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"etapa inválida: {etapa}",
        )

    tenant = _tenant_id(current_user)
    if etapa == "fonovisita":
        consolidacao = _lock_consolidacao(db, tenant, consolidacao_id)
        _ensure_open(consolidacao)
        if (
            consolidacao.responsavel_id is None
            or str(consolidacao.responsavel_id) != current_user.app_user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o consolidador responsável pode confirmar etapas",
            )
        work_items = _lock_linked_work_items(db, tenant, consolidacao.id)
        canonical = next(
            (item for item in work_items if item.tipo == "fonovisita"),
            None,
        )
        if canonical is None:
            # Legacy tracks predate the V3 canonical queue item. The human
            # panel preserves its existing stage advancement without creating
            # a queue row, alert or backfill. WhatsApp remains on
            # complete_fonovisita, which requires the exact canonical row.
            stage = _lock_stage(db, tenant, consolidacao.id, "fonovisita")
            if stage is None:
                stage = ConsolidacaoEtapa(
                    igreja_id=tenant,
                    consolidacao_id=consolidacao.id,
                    etapa="fonovisita",
                )
                db.add(stage)
            stage.concluida = True
            stage.confirmada_por = uuid.UUID(current_user.app_user_id)
            stage.confirmada_em = dt.datetime.now(dt.UTC)
            db.flush()
            _refresh_progress(db, consolidacao)
        else:
            completion = complete_fonovisita(
                db,
                current_user,
                consolidacao_id=consolidacao.id,
                work_queue_item_id=canonical.id,
                expected_assignment_revision=None,
                whatsapp=False,
            )
            consolidacao = completion.consolidacao
    else:
        consolidacao = _lock_consolidacao(db, tenant, consolidacao_id)
        _ensure_open(consolidacao)
        if (
            consolidacao.responsavel_id is None
            or str(consolidacao.responsavel_id) != current_user.app_user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o consolidador responsável pode confirmar etapas",
            )
        if etapa is not None:
            stage = _lock_stage(db, tenant, consolidacao.id, etapa)
            if stage is None:
                stage = ConsolidacaoEtapa(
                    igreja_id=tenant,
                    consolidacao_id=consolidacao.id,
                    etapa=etapa,
                )
                db.add(stage)
            stage.concluida = True
            stage.confirmada_por = uuid.UUID(current_user.app_user_id)
            stage.confirmada_em = dt.datetime.now(dt.UTC)
            db.flush()
        _refresh_progress(db, consolidacao)

    confirmed = _confirmed_stages(db, consolidacao.id)
    if concluir:
        if not can_conclude(confirmed):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "pending_stages",
                    "message": "Há etapas obrigatórias pendentes",
                    "etapasPendentes": sorted(pending_mandatory(confirmed)),
                },
            )
        consolidacao.concluida = True
        consolidacao.progresso = 100

    db.flush()
    db.refresh(consolidacao)
    return StageAdvanceResult(
        consolidacao=consolidacao,
        etapas_pendentes=tuple(sorted(pending_mandatory(confirmed))),
    )


def queue_manual_fonovisita(
    db: Session,
    current_user: CurrentUser,
    *,
    pessoa: Pessoa,
    contexto: str | None,
) -> tuple[WorkQueueItem, bool]:
    """Create or refresh only an unlinked legacy/manual fonovisita item."""

    if not current_user.has_any_role(PIPELINE_WRITE_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para registrar fonovisita",
        )
    tenant = _tenant_id(current_user)
    if pessoa.igreja_id != tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pessoa não encontrada",
        )
    normalized_context = contexto or f"Fonovisita para {pessoa.nome}"
    existing = db.execute(
        select(WorkQueueItem)
        .where(
            WorkQueueItem.igreja_id == tenant,
            WorkQueueItem.pessoa_id == pessoa.id,
            WorkQueueItem.tipo == "fonovisita",
            WorkQueueItem.consolidacao_id.is_(None),
            WorkQueueItem.status.in_(_ACTIVE_QUEUE_STATUSES),
        )
        .order_by(WorkQueueItem.id)
        .with_for_update()
        .execution_options(populate_existing=True)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        existing.contexto = normalized_context
        db.flush()
        return existing, True

    item = WorkQueueItem(
        igreja_id=tenant,
        tipo="fonovisita",
        titulo=f"Fonovisita: {pessoa.nome}",
        contexto=normalized_context,
        pessoa_id=pessoa.id,
        status="aberto",
        prioridade=2,
    )
    db.add(item)
    db.flush()
    return item, False


def _tenant_id(current_user: CurrentUser) -> uuid.UUID:
    return uuid.UUID(current_user.igreja_id)


def _require_bool(value: bool) -> None:
    if type(value) is not bool:
        raise TypeError("whatsapp deve ser bool")


def _validate_revision(value: int | None, *, required: bool) -> None:
    if (required and value is None) or (
        value is not None and (type(value) is not int or value < 0)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Revisão de atribuição inválida",
        )


def _validate_queue_action(
    *,
    expected_work_queue_item_id: uuid.UUID | None,
    work_queue_action: Literal["assume", "assign"] | None,
) -> None:
    if expected_work_queue_item_id is None and work_queue_action is None:
        return
    if (
        not isinstance(expected_work_queue_item_id, uuid.UUID)
        or work_queue_action not in _QUEUE_ACTIONS
    ):
        raise TypeError("contrato de ação da fila inválido")


def _require_assignment_actor(current_user: CurrentUser) -> None:
    if not current_user.has_any_role(CONSOLIDATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para atribuir consolidador",
        )


def _require_queue_action_actor(
    current_user: CurrentUser,
    *,
    item_tipo: str,
    action: Literal["assume", "assign"],
) -> None:
    """Preserve the panel queue's existing per-item authorization.

    Queue callers arrive after the router has checked the item's visibility.
    The workflow repeats the checks that remain meaningful after it acquires
    the canonical track/task locks, so a direct service caller cannot widen
    the legacy action surface.
    """

    if not can_resolve(current_user.roles, item_tipo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode resolver itens deste tipo",
        )
    if action == "assign" and not has_tenant_queue_scope(current_user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para atribuir itens da fila",
        )


def _lock_consolidacao(
    db: Session,
    tenant: uuid.UUID,
    consolidacao_id: uuid.UUID,
) -> Consolidacao:
    consolidacao = db.execute(
        select(Consolidacao)
        .where(
            Consolidacao.id == consolidacao_id,
            Consolidacao.igreja_id == tenant,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if consolidacao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consolidação não encontrada",
        )
    return consolidacao


def _lock_linked_work_items(
    db: Session,
    tenant: uuid.UUID,
    consolidacao_id: uuid.UUID,
) -> list[WorkQueueItem]:
    return list(
        db.execute(
            select(WorkQueueItem)
            .where(
                WorkQueueItem.igreja_id == tenant,
                WorkQueueItem.consolidacao_id == consolidacao_id,
            )
            .order_by(WorkQueueItem.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars().all()
    )


def _lock_stage(
    db: Session,
    tenant: uuid.UUID,
    consolidacao_id: uuid.UUID,
    etapa: str,
) -> ConsolidacaoEtapa | None:
    return db.execute(
        select(ConsolidacaoEtapa)
        .where(
            ConsolidacaoEtapa.igreja_id == tenant,
            ConsolidacaoEtapa.consolidacao_id == consolidacao_id,
            ConsolidacaoEtapa.etapa == etapa,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _resolve_assignment_target(
    db: Session,
    tenant: uuid.UUID,
    responsavel_id: uuid.UUID,
    *,
    whatsapp: bool,
) -> uuid.UUID:
    if whatsapp:
        target_id = db.execute(
            select(AppUser.id)
            .join(
                Pessoa,
                and_(
                    Pessoa.id == AppUser.pessoa_id,
                    Pessoa.igreja_id == AppUser.igreja_id,
                ),
            )
            .where(
                AppUser.id == responsavel_id,
                AppUser.igreja_id == tenant,
                AppUser.status == "ativo",
                Pessoa.igreja_id == tenant,
                Pessoa.arquivada_em.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if target_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Responsável não encontrado",
            )
        capable = db.execute(
            select(UserRole.id)
            .where(
                UserRole.igreja_id == tenant,
                UserRole.user_id == target_id,
                UserRole.papel.in_(_WHATSAPP_TARGET_ROLES),
            )
            .with_for_update()
            .limit(1)
        ).scalar_one_or_none()
        if capable is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Responsável não pode atuar na consolidação",
            )
        return target_id

    target_id = db.execute(
        select(AppUser.id)
        .where(
            AppUser.id == responsavel_id,
            AppUser.igreja_id == tenant,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Responsável não encontrado",
        )
    return target_id


def _require_active_queue_candidate(
    work_items: list[WorkQueueItem],
    expected_work_queue_item_id: uuid.UUID | None,
) -> WorkQueueItem:
    item = next(
        (row for row in work_items if row.id == expected_work_queue_item_id),
        None,
    )
    if item is None or not _is_active_queue_item(item):
        raise _queue_conflict(item)
    return item


def _resolve_queue_target(
    db: Session,
    tenant: uuid.UUID,
    current_user: CurrentUser,
    responsavel_id: uuid.UUID,
    item_tipo: str,
    *,
    action: Literal["assume", "assign"],
) -> uuid.UUID:
    if action == "assume":
        return uuid.UUID(current_user.app_user_id)

    target_id = db.execute(
        select(AppUser.id).where(
            AppUser.id == responsavel_id,
            AppUser.igreja_id == tenant,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
    ).scalar_one_or_none()
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Responsável não encontrado",
        )
    target_roles = db.execute(
        select(UserRole.papel).where(
            UserRole.igreja_id == tenant,
            UserRole.user_id == target_id,
        )
    ).scalars().all()
    if not can_resolve(target_roles, item_tipo):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Responsável não pode resolver itens deste tipo",
        )
    return target_id


def _queue_action_is_idempotent_or_conflicts(
    db: Session,
    tenant: uuid.UUID,
    item: WorkQueueItem,
    target_id: uuid.UUID,
    *,
    action: Literal["assume", "assign"],
) -> bool:
    if item.status != "assumido":
        return False
    if item.responsavel_id == target_id:
        return True
    if action == "assume" or _queue_holder_is_active_and_capable(
        db,
        tenant,
        item.responsavel_id,
        item.tipo,
    ):
        raise _queue_conflict(item)
    return False


def _queue_holder_is_active_and_capable(
    db: Session,
    tenant: uuid.UUID,
    responsavel_id: uuid.UUID | None,
    item_tipo: str,
) -> bool:
    if responsavel_id is None:
        return False
    holder_id = db.execute(
        select(AppUser.id).where(
            AppUser.id == responsavel_id,
            AppUser.igreja_id == tenant,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
    ).scalar_one_or_none()
    if holder_id is None:
        return False
    holder_roles = db.execute(
        select(UserRole.papel).where(
            UserRole.igreja_id == tenant,
            UserRole.user_id == holder_id,
        )
    ).scalars().all()
    return can_resolve(holder_roles, item_tipo)


def _queue_conflict(item: WorkQueueItem | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "stale_item",
            "message": "Item já foi assumido ou resolvido por outro usuário",
            "status": item.status if item is not None else None,
            "responsavelId": (
                str(item.responsavel_id)
                if item is not None and item.responsavel_id is not None
                else None
            ),
        },
    )


def _ensure_open(consolidacao: Consolidacao) -> None:
    if consolidacao.concluida:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Consolidação já concluída",
        )
    if consolidacao.abandonada_em is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Consolidação abandonada (pessoa arquivada) não pode ser avançada",
        )


def _require_expected_revision(
    consolidacao: Consolidacao,
    expected_assignment_revision: int | None,
) -> None:
    if (
        expected_assignment_revision is not None
        and consolidacao.assignment_revision != expected_assignment_revision
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A atribuição da consolidação foi alterada",
        )


def _is_active_queue_item(item: WorkQueueItem) -> bool:
    return item.status is None or item.status in _ACTIVE_QUEUE_STATUSES


def _confirmed_stages(db: Session, consolidacao_id: uuid.UUID) -> set[str]:
    return {
        etapa
        for etapa in db.execute(
            select(ConsolidacaoEtapa.etapa).where(
                ConsolidacaoEtapa.consolidacao_id == consolidacao_id,
                ConsolidacaoEtapa.concluida.is_(True),
            )
        ).scalars().all()
        if etapa
    }


def _refresh_progress(db: Session, consolidacao: Consolidacao) -> set[str]:
    confirmed = _confirmed_stages(db, consolidacao.id)
    consolidacao.progresso = compute_progresso(confirmed)
    return confirmed


__all__ = [
    "AssignmentResult",
    "FonovisitaCompletion",
    "StageAdvanceResult",
    "advance_consolidacao_stage",
    "assign_consolidacao",
    "complete_fonovisita",
    "queue_manual_fonovisita",
]

"""Human domain operations shared with confirmed WhatsApp proposals.

Callers own commit/rollback. No HTTP and no privilege inferred from model output.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.models import AppUser, Celula, CelulaMembro, CelulaPresenca, CelulaReuniao, Consolidacao, Decision, Pessoa
from app.deps import CurrentUser
from app.domain.consolidation import CONNECTION_DEADLINE_HOURS, CONSOLIDATION_ROLES, VALID_VINCULOS, VINCULO_VISITANTE
from app.domain.hierarchy import is_leader_or_superior

logger = logging.getLogger(__name__)


def register_decision(db: Session, current_user: CurrentUser, *, pessoa_id: uuid.UUID,
                      vinculo: str, origem: str | None = None,
                      celula_id: uuid.UUID | None = None) -> Consolidacao:
    if vinculo not in VALID_VINCULOS:
        raise HTTPException(422, "Vínculo inválido")
    if not current_user.has_any_role(CONSOLIDATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para lançar decisões",
        )

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_id, Pessoa.igreja_id == uuid.UUID(current_user.igreja_id))
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    celula_uuid: uuid.UUID | None = None
    if celula_id is not None:
        celula_uuid = celula_id
        celula = db.execute(
            select(Celula).where(Celula.id == celula_uuid, Celula.igreja_id == uuid.UUID(current_user.igreja_id))
        ).scalar_one_or_none()
        if celula is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
            )

    # fluxo B (visitante): 24h connection deadline; fluxo A (celula): none.
    prazo_conexao: dt.datetime | None = None
    if vinculo == VINCULO_VISITANTE:
        prazo_conexao = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            hours=CONNECTION_DEADLINE_HOURS
        )

    decision = Decision(
        igreja_id=uuid.UUID(current_user.igreja_id),
        pessoa_id=pessoa.id,
        origem=origem,
        vinculo=vinculo,
        celula_id=celula_uuid,
        prazo_conexao=prazo_conexao,
    )
    # Preserve the outer proposal and its claim when consolidation collides.
    db.flush()
    with db.begin_nested():
        db.add(decision)
        pessoa.aceitou_jesus = True
        db.flush()

    consolidacao = db.execute(
        select(Consolidacao)
        .where(
            Consolidacao.igreja_id == uuid.UUID(current_user.igreja_id),
            Consolidacao.origin_decision_id == decision.id,
        )
    ).scalar_one_or_none()
    if consolidacao is None:
        # The trigger should always create one; fail loudly if it did not.
        logger.error(
            "consolidation not created by trigger",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao abrir consolidação",
        )

    return consolidacao


def can_mark_for_other(db: Session, current_user: CurrentUser, cell: Celula) -> bool:
    tenant = uuid.UUID(current_user.igreja_id)
    if str(cell.igreja_id) != str(tenant):
        return False
    if current_user.has_any_role(["pastor"]):
        return True
    actor = db.execute(select(AppUser.pessoa_id).where(
        AppUser.id == uuid.UUID(current_user.app_user_id), AppUser.igreja_id == tenant,
    )).scalar_one_or_none()
    leaders = db.execute(select(Pessoa.id, Pessoa.lider_id).where(Pessoa.igreja_id == tenant)).all()
    return is_leader_or_superior(actor_pessoa_id=str(actor) if actor else None,
        cell_leader_id=str(cell.lider_id) if cell.lider_id else None,
        lider_of={str(pid): str(lid) if lid else None for pid, lid in leaders})


def confirm_meeting_attendance(db: Session, current_user: CurrentUser, *,
                               reuniao_id: uuid.UUID, pessoa_id: uuid.UUID | None = None) -> CelulaPresenca:
    tenant = uuid.UUID(current_user.igreja_id)
    meeting = db.execute(select(CelulaReuniao).where(
        CelulaReuniao.id == reuniao_id, CelulaReuniao.igreja_id == tenant,
    )).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(404, "Reunião não encontrada")
    actor = db.execute(select(AppUser.pessoa_id).where(
        AppUser.id == uuid.UUID(current_user.app_user_id), AppUser.igreja_id == tenant,
    )).scalar_one_or_none()
    automatic = pessoa_id is None or (actor is not None and str(pessoa_id) == str(actor))
    if automatic:
        if actor is None:
            raise HTTPException(403, "Seu usuário não está vinculado a uma pessoa")
        target = actor
        source = "auto"
    else:
        cell = db.execute(select(Celula).where(
            Celula.id == meeting.celula_id, Celula.igreja_id == tenant,
        )).scalar_one_or_none()
        if cell is None or not can_mark_for_other(db, current_user, cell):
            raise HTTPException(403, "Sem permissão para marcar a presença de outra pessoa")
        target = pessoa_id
        person = db.execute(select(Pessoa).where(Pessoa.id == target, Pessoa.igreja_id == tenant)).scalar_one_or_none()
        if person is None:
            raise HTTPException(422, "pessoaId: pessoa não encontrada nesta igreja")
        source = "lider"
    member = db.execute(select(CelulaMembro).where(
        CelulaMembro.igreja_id == tenant, CelulaMembro.celula_id == meeting.celula_id,
        CelulaMembro.pessoa_id == target, CelulaMembro.ativo.is_(True),
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(403, "Pessoa sem vínculo ativo na célula desta reunião")
    query = select(CelulaPresenca).where(CelulaPresenca.igreja_id == tenant,
        CelulaPresenca.reuniao_id == meeting.id, CelulaPresenca.pessoa_id == target)
    attendance = db.execute(query).scalar_one_or_none()
    if attendance is None:
        # A savepoint contains UNIQUE races without rolling back the proposal.
        db.flush()
        try:
            with db.begin_nested():
                attendance = CelulaPresenca(igreja_id=tenant, reuniao_id=meeting.id,
                    pessoa_id=target, estado="confirmada", origem=source)
                db.add(attendance)
                db.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "pgcode", None) != "23505":
                raise
            attendance = db.execute(query).scalar_one_or_none()
            if attendance is None:
                raise
    attendance.estado = "confirmada"
    attendance.origem = source
    attendance.updated_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.refresh(attendance)
    return attendance

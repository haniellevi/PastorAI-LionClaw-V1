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
from app.db.models import AppUser, Celula, CelulaMembro, CelulaPresenca, CelulaReuniao, CelulaExpectativaVisitante, Consolidacao, Decision, Pessoa
from app.deps import CurrentUser
from app.domain import cell_meetings_schedule
from app.domain.consolidation import CONNECTION_DEADLINE_HOURS, CONSOLIDATION_ROLES, VALID_VINCULOS, VINCULO_VISITANTE
from app.domain.hierarchy import is_leader_or_superior

logger = logging.getLogger(__name__)


def register_own_visitor_expectation(db: Session, current_user: CurrentUser, *,
                                    reuniao_id: uuid.UUID, nome_visitante: str,
                                    observacao_oracao: str | None = None,
                                    expected_actor_pessoa_id: uuid.UUID | None = None
                                    ) -> CelulaExpectativaVisitante:
    """Create one own expectation; caller owns commit and the proposal ledger.

    Human callers omit the internal expected actor and keep their historical
    meeting/membership contract, optional note and multiple rows.
    """
    tenant = uuid.UUID(current_user.igreja_id)
    if expected_actor_pessoa_id is None:
        meeting = db.execute(select(CelulaReuniao).where(
            CelulaReuniao.id == reuniao_id, CelulaReuniao.igreja_id == tenant,
        )).scalar_one_or_none()
        if meeting is None:
            raise HTTPException(404, "Reunião não encontrada")
        actor = db.execute(select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id), AppUser.igreja_id == tenant,
        )).scalar_one_or_none()
        if actor is None:
            raise HTTPException(403, "Seu usuário não está vinculado a uma pessoa")
        person_id = uuid.UUID(str(actor))
        member = db.execute(select(CelulaMembro).where(
            CelulaMembro.igreja_id == tenant, CelulaMembro.celula_id == meeting.celula_id,
            CelulaMembro.pessoa_id == person_id, CelulaMembro.ativo.is_(True),
        )).scalar_one_or_none()
        if member is None:
            raise HTTPException(403, "Você não tem vínculo ativo na célula desta reunião")
        # The existing HTTP schemas validate/trim human input, including notes.
        if type(nome_visitante) is not str or not 1 <= len(nome_visitante.strip()) <= 200:
            raise HTTPException(422, "Nome de visitante inválido")
        name = nome_visitante.strip()
    else:
        if (type(expected_actor_pessoa_id) is not uuid.UUID or expected_actor_pessoa_id.int == 0
            or type(reuniao_id) is not uuid.UUID or reuniao_id.int == 0
            or observacao_oracao is not None):
            raise HTTPException(403, "Ação não autorizada")
        from app.services.agent_action_proposals import canonical_visitor_name, ProposalContractError
        try:
            name = canonical_visitor_name(nome_visitante)
        except ProposalContractError:
            raise HTTPException(422, "Nome de visitante inválido") from None
        actor = db.execute(select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id), AppUser.igreja_id == tenant,
            AppUser.status == "ativo",
        ).with_for_update()).scalar_one_or_none()
        if actor is None or actor != expected_actor_pessoa_id:
            raise HTTPException(403, "Vínculo do usuário alterado")
        person = db.execute(select(Pessoa).where(
            Pessoa.id == expected_actor_pessoa_id, Pessoa.igreja_id == tenant,
            Pessoa.arquivada_em.is_(None),
        ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if person is None:
            raise HTTPException(403, "Pessoa sem vínculo elegível")
        person_id = person.id
        meeting = db.execute(select(CelulaReuniao).where(
            CelulaReuniao.id == reuniao_id, CelulaReuniao.igreja_id == tenant,
        ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if meeting is None:
            raise HTTPException(404, "Reunião não encontrada")
        cell = db.execute(select(Celula).where(
            Celula.id == meeting.celula_id, Celula.igreja_id == tenant, Celula.ativo.is_(True),
        ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if cell is None:
            raise HTTPException(403, "Célula sem vínculo elegível")
        member = db.execute(select(CelulaMembro).where(
            CelulaMembro.igreja_id == tenant, CelulaMembro.celula_id == cell.id,
            CelulaMembro.pessoa_id == person_id, CelulaMembro.ativo.is_(True),
        ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if member is None:
            raise HTTPException(403, "Você não tem vínculo ativo na célula desta reunião")
        # Flush preceding proposal work, then recheck after all lookup/lock
        # waits immediately before adding the expectation. E4 allows equality.
        db.flush()
        now = cell_meetings_schedule.now_in_sao_paulo()
        if cell_meetings_schedule.meeting_has_passed(data=meeting.data, hora=meeting.hora, now=now):
            raise HTTPException(409, "A reunião já ocorreu")
    expectation = CelulaExpectativaVisitante(
        igreja_id=tenant, reuniao_id=meeting.id, pessoa_id=person_id,
        nome_visitante=name, observacao_oracao=observacao_oracao,
    )
    db.add(expectation)
    db.flush()
    db.refresh(expectation)
    return expectation


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
                               reuniao_id: uuid.UUID, pessoa_id: uuid.UUID | None = None,
                               expected_actor_pessoa_id: uuid.UUID | None = None) -> CelulaPresenca:
    # Internal catalog-only contract. Human callers omit it and retain the
    # original body below, including historical own/third-party attendance.
    if expected_actor_pessoa_id is not None:
        if type(expected_actor_pessoa_id) is not uuid.UUID or pessoa_id is not None:
            raise HTTPException(403, "Ação não autorizada")
        return _confirm_own_meeting_attendance(db, current_user,
            reuniao_id=reuniao_id, expected_actor_pessoa_id=expected_actor_pessoa_id)
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


def _confirm_own_meeting_attendance(db: Session, current_user: CurrentUser, *,
                                   reuniao_id: uuid.UUID,
                                   expected_actor_pessoa_id: uuid.UUID) -> CelulaPresenca:
    """Lock fresh server facts in actor/meeting/cell/member/presence order.

    The caller owns the transaction. No model argument can select this branch.
    """
    tenant = uuid.UUID(current_user.igreja_id)
    actor = db.execute(select(AppUser.pessoa_id).where(
        AppUser.id == uuid.UUID(current_user.app_user_id), AppUser.igreja_id == tenant,
    ).with_for_update()).scalar_one_or_none()
    if actor is None or actor != expected_actor_pessoa_id:
        raise HTTPException(403, "Vínculo do usuário alterado")
    meeting = db.execute(select(CelulaReuniao).where(
        CelulaReuniao.id == reuniao_id, CelulaReuniao.igreja_id == tenant,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(404, "Reunião não encontrada")
    cell = db.execute(select(Celula).where(
        Celula.id == meeting.celula_id, Celula.igreja_id == tenant,
        Celula.ativo.is_(True),
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if cell is None:
        raise HTTPException(403, "Célula sem vínculo elegível")
    member = db.execute(select(CelulaMembro).where(
        CelulaMembro.igreja_id == tenant, CelulaMembro.celula_id == cell.id,
        CelulaMembro.pessoa_id == actor, CelulaMembro.ativo.is_(True),
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if member is None:
        raise HTTPException(403, "Pessoa sem vínculo ativo na célula desta reunião")
    query = select(CelulaPresenca).where(
        CelulaPresenca.igreja_id == tenant, CelulaPresenca.reuniao_id == meeting.id,
        CelulaPresenca.pessoa_id == actor,
    ).with_for_update().execution_options(populate_existing=True)
    attendance = db.execute(query).scalar_one_or_none()

    def confirmation_time() -> dt.datetime:
        now = cell_meetings_schedule.now_in_sao_paulo()
        if cell_meetings_schedule.meeting_has_passed(data=meeting.data, hora=meeting.hora, now=now):
            raise HTTPException(409, "A reunião já ocorreu; não é possível confirmar presença")
        return now.astimezone(dt.timezone.utc)

    inserted = False
    if attendance is None:
        db.flush()
        try:
            with db.begin_nested():
                # Capture again after lock waits and savepoint flush, directly
                # before the insert. E4 allows equality with the meeting time.
                confirmed_at = confirmation_time()
                attendance = CelulaPresenca(igreja_id=tenant, reuniao_id=meeting.id,
                    pessoa_id=actor, estado="confirmada", origem="auto", updated_at=confirmed_at)
                db.add(attendance)
                db.flush()
                inserted = True
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if sqlstate != "23505":
                raise
            # Keep the outer actor/meeting/cell/member locks; reacquire the
            # conflicting presence row and check the clock before its update.
            attendance = db.execute(query).scalar_one_or_none()
            if attendance is None:
                raise
    if not inserted:
        confirmed_at = confirmation_time()
        attendance.estado = "confirmada"
        attendance.origem = "auto"
        attendance.updated_at = confirmed_at
        db.flush()
    db.refresh(attendance)
    return attendance

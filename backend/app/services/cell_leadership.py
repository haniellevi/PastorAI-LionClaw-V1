"""Fonte única da liderança efetiva de célula.

Liderança não é um papel editável isolado. Ela existe quando uma célula ativa
aponta para uma Pessoa e essa Pessoa possui exatamente um acesso utilizável ao
painel na mesma igreja. Este serviço mantém ``celulas.lider_id``/``ativo`` e o
papel derivado ``lider_celula`` na mesma transação do chamador; nunca commita.

Sem uma constraint nova, a trava pessimista da Pessoa é o ponto de
serialização defensivo: duas transações que tentem atribuir a mesma pessoa a
células diferentes não passam simultaneamente pela checagem de conflito.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, CelulaMembro, Pessoa, UserRole

LEADER_ROLE = "lider_celula"
BASE_MEMBER_ROLE = "membro"
ACTIVE_ACCESS_STATUS = "ativo"


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _load_candidate_for_update(
    db: Session, *, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> Pessoa:
    pessoa = db.execute(
        select(Pessoa)
        .where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="liderId: pessoa não encontrada nesta igreja",
        )
    if getattr(pessoa, "arquivada_em", None) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="liderId: pessoa arquivada não pode liderar célula",
        )
    if bool(pessoa.sem_interesse):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="liderId: pessoa fora da igreja não pode liderar célula",
        )
    if not bool(pessoa.apto_lider):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="liderId: pessoa ainda não fez o Reencontro (não apta a liderar)",
        )
    return pessoa


def resolve_effective_access(
    db: Session, *, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> AppUser:
    """Retorna o único acesso utilizável da Pessoa ou falha fechado com 409.

    ``status IS NULL`` é compatibilidade explícita com acessos legados. Um
    convidado, revogado ou acesso ainda sem identidade Clerk nunca habilita uma
    nova liderança. A query é escopada por tenant mesmo quando o caller roda
    sob RLS.
    """

    accesses = list(
        db.execute(
            select(AppUser)
            .where(
                AppUser.igreja_id == igreja_id,
                AppUser.pessoa_id == pessoa_id,
                AppUser.clerk_user_id.is_not(None),
                or_(
                    AppUser.status.is_(None),
                    AppUser.status == ACTIVE_ACCESS_STATUS,
                ),
            )
            .order_by(AppUser.id.asc())
            .with_for_update(of=AppUser)
        ).scalars().all()
    )
    if len(accesses) != 1:
        raise _conflict(
            "A liderança exige exatamente um acesso ativo da pessoa nesta igreja"
        )
    return accesses[0]


def validate_new_effective_leader(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    exclude_cell_id: uuid.UUID | str | None = None,
) -> AppUser:
    """Valida e trava candidato, conflito de célula e acesso utilizável."""

    _load_candidate_for_update(db, igreja_id=igreja_id, pessoa_id=pessoa_id)

    filters = [
        Celula.igreja_id == igreja_id,
        Celula.lider_id == pessoa_id,
        Celula.ativo.is_(True),
    ]
    if exclude_cell_id is not None:
        filters.append(Celula.id != uuid.UUID(str(exclude_cell_id)))
    existing = db.execute(select(Celula.id).where(*filters).limit(1)).scalar_one_or_none()
    if existing is not None:
        raise _conflict("liderId: pessoa já lidera uma célula ativa")

    if exclude_cell_id is not None:
        target_membership = db.execute(
            select(CelulaMembro.id)
            .where(
                CelulaMembro.igreja_id == igreja_id,
                CelulaMembro.celula_id == uuid.UUID(str(exclude_cell_id)),
                CelulaMembro.pessoa_id == pessoa_id,
                CelulaMembro.ativo.is_(True),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if target_membership is not None:
            raise _conflict(
                "liderId: remova a pessoa dos membros antes de torná-la líder"
            )

    return resolve_effective_access(db, igreja_id=igreja_id, pessoa_id=pessoa_id)


def _ensure_leader_role(
    db: Session, *, igreja_id: uuid.UUID, app_user_id: uuid.UUID
) -> None:
    role = db.execute(
        select(UserRole).where(
            UserRole.igreja_id == igreja_id,
            UserRole.user_id == app_user_id,
            UserRole.papel == LEADER_ROLE,
        )
    ).scalar_one_or_none()
    if role is None:
        db.add(
            UserRole(
                igreja_id=igreja_id,
                user_id=app_user_id,
                papel=LEADER_ROLE,
            )
        )


def _lock_leadership_identities(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_ids: set[uuid.UUID],
) -> None:
    """Trava Pessoas e AppUsers antigos/novos em ordem determinística.

    Compartilha o serializador com ativação, revogação e edição de papéis. A
    célula persistida já foi travada pelo router antes deste serviço.
    """

    ordered_people = sorted(pessoa_ids, key=str)
    for pessoa_id in ordered_people:
        found = db.execute(
            select(Pessoa.id)
            .where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
            .with_for_update()
        ).scalar_one_or_none()
        if found is None:
            raise _conflict("A liderança referencia uma pessoa inconsistente")
    for pessoa_id in ordered_people:
        # Trava também convidado/revogado: uma transição de status concorrente
        # não pode passar entre a decisão de liderança e a sincronização do role.
        db.execute(
            select(AppUser)
            .where(
                AppUser.igreja_id == igreja_id,
                AppUser.pessoa_id == pessoa_id,
            )
            .order_by(AppUser.id.asc())
            .with_for_update(of=AppUser)
        ).scalars().all()


def _remove_leader_roles_if_unused(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    exclude_cell_id: uuid.UUID | str | None,
) -> None:
    filters = [
        Celula.igreja_id == igreja_id,
        Celula.lider_id == pessoa_id,
        Celula.ativo.is_(True),
    ]
    if exclude_cell_id is not None:
        filters.append(Celula.id != uuid.UUID(str(exclude_cell_id)))
    still_leads = db.execute(
        select(Celula.id).where(*filters).limit(1)
    ).scalar_one_or_none()
    if still_leads is not None:
        return

    user_ids = list(
        db.execute(
            select(AppUser.id).where(
                AppUser.igreja_id == igreja_id,
                AppUser.pessoa_id == pessoa_id,
            )
        ).scalars().all()
    )
    if not user_ids:
        return
    roles = list(
        db.execute(
            select(UserRole).where(
                UserRole.igreja_id == igreja_id,
                UserRole.user_id.in_(user_ids),
                UserRole.papel == LEADER_ROLE,
            )
        ).scalars().all()
    )
    for role in roles:
        db.delete(role)

    eligible_users = list(
        db.execute(
            select(AppUser).where(
                AppUser.igreja_id == igreja_id,
                AppUser.id.in_(user_ids),
                AppUser.clerk_user_id.is_not(None),
                or_(
                    AppUser.status.is_(None),
                    AppUser.status == ACTIVE_ACCESS_STATUS,
                ),
            )
        ).scalars().all()
    )
    for user in eligible_users:
        other_role = db.execute(
            select(UserRole.id)
            .where(
                UserRole.igreja_id == igreja_id,
                UserRole.user_id == user.id,
                UserRole.papel != LEADER_ROLE,
            )
            .limit(1)
        ).scalar_one_or_none()
        if other_role is None:
            db.add(
                UserRole(
                    igreja_id=igreja_id,
                    user_id=user.id,
                    papel=BASE_MEMBER_ROLE,
                )
            )


def set_cell_leadership(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    cell: Celula,
    new_leader_id: uuid.UUID | None,
    new_active: bool,
) -> None:
    """Aplica líder/estado e sincroniza o papel derivado, sem commit.

    Uma manutenção que preserva exatamente a mesma liderança efetiva é no-op
    para compatibilidade com registros legados. Atribuir, trocar, ativar ou
    desativar passa por este serviço e fica atômico com a gravação da célula.
    """

    old_leader_id = cell.lider_id
    old_effective = old_leader_id if bool(cell.ativo) else None
    new_effective = new_leader_id if new_active else None

    identity_ids = {
        pessoa_id
        for pessoa_id in (old_effective, new_effective)
        if pessoa_id is not None
    }
    if identity_ids:
        _lock_leadership_identities(
            db, igreja_id=igreja_id, pessoa_ids=identity_ids
        )

    access: AppUser | None = None
    if new_effective is not None and str(new_effective) != str(old_effective):
        access = validate_new_effective_leader(
            db,
            igreja_id=igreja_id,
            pessoa_id=new_effective,
            exclude_cell_id=getattr(cell, "id", None),
        )
    elif new_effective is not None:
        # Grandfather apenas a aptidão pastoral histórica. Qualquer gravação de
        # célula ativa reconcilia a parte técnica: acesso único utilizável e
        # papel derivado, ou falha fechado sem persistir alterações parciais.
        access = resolve_effective_access(
            db, igreja_id=igreja_id, pessoa_id=new_effective
        )

    cell.lider_id = new_leader_id
    cell.ativo = new_active

    if access is not None:
        _ensure_leader_role(
            db, igreja_id=igreja_id, app_user_id=access.id
        )

    if old_effective is not None and str(old_effective) != str(new_effective):
        _remove_leader_roles_if_unused(
            db,
            igreja_id=igreja_id,
            pessoa_id=old_effective,
            exclude_cell_id=getattr(cell, "id", None),
        )


def sync_role_after_activation(db: Session, *, app_user: AppUser) -> None:
    """Concede o papel derivado ao ativar um líder legado já cadastrado.

    Novas atribuições exigem acesso ativo antes de ocorrer. Este caminho existe
    somente para a compatibilidade solicitada: uma Pessoa que já liderava uma
    célula ativa antes da separação pode receber acesso e, ao ativá-lo, entrar
    com a visão correta sem reparo global de dados.
    """

    if app_user.pessoa_id is None:
        return
    leads = db.execute(
        select(Celula.id)
        .where(
            Celula.igreja_id == app_user.igreja_id,
            Celula.lider_id == app_user.pessoa_id,
            Celula.ativo.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()
    if leads is not None:
        _ensure_leader_role(
            db, igreja_id=app_user.igreja_id, app_user_id=app_user.id
        )

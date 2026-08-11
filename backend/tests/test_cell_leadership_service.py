"""Contrato transacional do papel derivado de liderança de célula."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Base,
    Celula,
    CelulaMembro,
    Igreja,
    Pessoa,
    UserRole,
)
from app.services.cell_leadership import LEADER_ROLE, set_cell_leadership


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _sqlite_now(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function(
            "now", 0, lambda: dt.datetime.now(dt.timezone.utc).isoformat()
        )
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(
        engine,
        tables=[
            Igreja.__table__,
            Pessoa.__table__,
            AppUser.__table__,
            UserRole.__table__,
            Celula.__table__,
            CelulaMembro.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _church(db: Session, name: str = "Igreja") -> uuid.UUID:
    igreja = Igreja(id=uuid.uuid4(), nome=name, status="ativa")
    db.add(igreja)
    db.flush()
    return igreja.id


def _person(
    db: Session,
    igreja_id: uuid.UUID,
    *,
    apto: bool = True,
) -> Pessoa:
    pessoa = Pessoa(
        id=uuid.uuid4(),
        igreja_id=igreja_id,
        nome="Pessoa",
        telefone=str(uuid.uuid4().int)[-11:],
        apto_lider=apto,
        sem_interesse=False,
    )
    db.add(pessoa)
    db.flush()
    return pessoa


def _access(
    db: Session,
    igreja_id: uuid.UUID,
    pessoa: Pessoa,
    *,
    status: str | None = "ativo",
    clerk: str | None = None,
) -> AppUser:
    user = AppUser(
        id=uuid.uuid4(),
        igreja_id=igreja_id,
        pessoa_id=pessoa.id,
        nome=pessoa.nome,
        email=f"{uuid.uuid4()}@igreja.org",
        clerk_user_id=clerk if clerk is not None else f"clerk_{uuid.uuid4()}",
        status=status,
    )
    db.add(user)
    db.flush()
    return user


def _cell(
    db: Session,
    igreja_id: uuid.UUID,
    *,
    leader: Pessoa | None = None,
    active: bool = False,
) -> Celula:
    cell = Celula(
        id=uuid.uuid4(),
        igreja_id=igreja_id,
        nome="Célula",
        cobertura_espiritual="Rede",
        lider_id=leader.id if leader else None,
        ativo=active,
    )
    db.add(cell)
    db.flush()
    return cell


def _roles(db: Session, user: AppUser) -> set[str]:
    return set(
        db.execute(
            select(UserRole.papel).where(UserRole.user_id == user.id)
        ).scalars().all()
    )


def test_assignment_requires_exactly_one_active_access_and_adds_role(db: Session) -> None:
    igreja_id = _church(db)
    pessoa = _person(db, igreja_id)
    user = _access(db, igreja_id, pessoa)
    cell = _cell(db, igreja_id)

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=pessoa.id,
        new_active=True,
    )
    db.flush()

    assert cell.lider_id == pessoa.id
    assert cell.ativo is True
    assert _roles(db, user) == {LEADER_ROLE}


@pytest.mark.parametrize(
    ("status_value", "has_clerk"),
    [
        ("convidado", True),
        ("revogado", True),
        ("ativo", False),
    ],
)
def test_invited_revoked_or_clerkless_access_fails_closed(
    db: Session, status_value: str, has_clerk: bool
) -> None:
    igreja_id = _church(db)
    pessoa = _person(db, igreja_id)
    _access(
        db,
        igreja_id,
        pessoa,
        status=status_value,
        clerk=f"clerk_{uuid.uuid4()}" if has_clerk else None,
    ).clerk_user_id = None if not has_clerk else f"clerk_{uuid.uuid4()}"
    cell = _cell(db, igreja_id)

    with pytest.raises(HTTPException) as exc:
        set_cell_leadership(
            db,
            igreja_id=igreja_id,
            cell=cell,
            new_leader_id=pessoa.id,
            new_active=True,
        )
    assert exc.value.status_code == 409
    assert cell.lider_id is None
    assert cell.ativo is False


def test_zero_or_multiple_active_accesses_are_conflicts(db: Session) -> None:
    igreja_id = _church(db)
    sem_acesso = _person(db, igreja_id)
    duplicado = _person(db, igreja_id)
    _access(db, igreja_id, duplicado)
    _access(db, igreja_id, duplicado)

    for pessoa in (sem_acesso, duplicado):
        cell = _cell(db, igreja_id)
        with pytest.raises(HTTPException) as exc:
            set_cell_leadership(
                db,
                igreja_id=igreja_id,
                cell=cell,
                new_leader_id=pessoa.id,
                new_active=True,
            )
        assert exc.value.status_code == 409


def test_swap_moves_derived_role_and_deactivation_removes_it(db: Session) -> None:
    igreja_id = _church(db)
    old = _person(db, igreja_id)
    new = _person(db, igreja_id)
    old_user = _access(db, igreja_id, old)
    new_user = _access(db, igreja_id, new)
    cell = _cell(db, igreja_id, leader=old, active=True)
    db.add(UserRole(igreja_id=igreja_id, user_id=old_user.id, papel=LEADER_ROLE))
    db.commit()

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=new.id,
        new_active=True,
    )
    db.flush()
    assert _roles(db, old_user) == {"membro"}
    assert _roles(db, new_user) == {LEADER_ROLE}

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=new.id,
        new_active=False,
    )
    db.flush()
    assert _roles(db, new_user) == {"membro"}


def test_removing_leader_role_preserves_other_role_without_member_fallback(db: Session) -> None:
    igreja_id = _church(db)
    old = _person(db, igreja_id)
    new = _person(db, igreja_id)
    old_user = _access(db, igreja_id, old)
    _access(db, igreja_id, new)
    cell = _cell(db, igreja_id, leader=old, active=True)
    db.add_all(
        [
            UserRole(igreja_id=igreja_id, user_id=old_user.id, papel=LEADER_ROLE),
            UserRole(igreja_id=igreja_id, user_id=old_user.id, papel="operador"),
        ]
    )
    db.commit()

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=new.id,
        new_active=True,
    )
    db.flush()
    assert _roles(db, old_user) == {"operador"}


def test_old_role_is_kept_when_person_still_leads_another_active_cell(db: Session) -> None:
    igreja_id = _church(db)
    old = _person(db, igreja_id)
    new = _person(db, igreja_id)
    old_user = _access(db, igreja_id, old)
    _access(db, igreja_id, new)
    cell = _cell(db, igreja_id, leader=old, active=True)
    _cell(db, igreja_id, leader=old, active=True)  # legado divergente
    db.add(UserRole(igreja_id=igreja_id, user_id=old_user.id, papel=LEADER_ROLE))
    db.commit()

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=new.id,
        new_active=True,
    )
    db.flush()
    assert _roles(db, old_user) == {LEADER_ROLE}


def test_same_legacy_leader_reconciles_role_without_rechecking_aptitude(db: Session) -> None:
    igreja_id = _church(db)
    pessoa = _person(db, igreja_id, apto=False)
    user = _access(db, igreja_id, pessoa, status=None)
    cell = _cell(db, igreja_id, leader=pessoa, active=True)
    db.commit()

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=pessoa.id,
        new_active=True,
    )
    db.flush()
    assert _roles(db, user) == {LEADER_ROLE}


def test_caller_rollback_restores_cell_and_both_roles(db: Session) -> None:
    igreja_id = _church(db)
    old = _person(db, igreja_id)
    new = _person(db, igreja_id)
    old_user = _access(db, igreja_id, old)
    new_user = _access(db, igreja_id, new)
    cell = _cell(db, igreja_id, leader=old, active=True)
    db.add(UserRole(igreja_id=igreja_id, user_id=old_user.id, papel=LEADER_ROLE))
    db.commit()

    set_cell_leadership(
        db,
        igreja_id=igreja_id,
        cell=cell,
        new_leader_id=new.id,
        new_active=True,
    )
    db.flush()
    db.rollback()

    persisted = db.get(Celula, cell.id)
    assert persisted is not None
    assert persisted.lider_id == old.id
    assert _roles(db, old_user) == {LEADER_ROLE}
    assert _roles(db, new_user) == set()

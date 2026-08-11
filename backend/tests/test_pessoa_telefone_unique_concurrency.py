"""UNIQ-PESSOA-1: unicidade do telefone por tenant + guarda de corrida.

``uq_pessoas_telefone_ativa`` (índice único PARCIAL em (igreja_id, telefone) onde
``arquivada_em IS NULL``) impõe "no máximo UMA pessoa ATIVA por telefone/tenant".
Os três pontos que criam Pessoa por telefone (queue_worker de inbound, POST
/contacts, ativação de convite) faziam "procura-antes-de-criar" — TOCTOU: duas
criações concorrentes do MESMO telefone/tenant não se veem e ambas inseririam.
``app.services.pessoa_dedup.insert_pessoa_or_get_winner`` fecha isso: o INSERT
roda num SAVEPOINT; no unique_violation da perdedora, re-busca a Pessoa vencedora
e segue com ela (caminho feliz idêntico).

Dois blocos:

  * Unitário (sempre roda) — prova a lógica de ramificação de
    ``insert_pessoa_or_get_winner`` com um ``db`` falso: caminho feliz devolve a
    própria Pessoa; unique_violation (23505) re-busca e devolve a vencedora;
    qualquer outra IntegrityError sobe; 23505 sem vencedora casável também sobe.

  * Integração Postgres (opt-in via ``RLS_TEST_DATABASE_URL``, skip LIMPO sem
    ela) — só um Postgres REAL tem o índice parcial e o SQLSTATE 23505. Prova as
    três invariantes da missão entre conexões concorrentes de verdade:
      (a) duas criações concorrentes do mesmo telefone/tenant ⇒ UMA Pessoa;
      (b) tenants diferentes com o mesmo telefone COEXISTEM;
      (c) telefone de pessoa ARQUIVADA não bloqueia recriar uma ativa.
"""

from __future__ import annotations

import datetime as dt
import inspect
import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm import Session, sessionmaker

# Importar session.py registra (uma vez) o listener after_begin do seam de tenant
# — paridade com produção. As sessões deste teste NÃO são marcadas ⇒ no-op.
import app.db.session  # noqa: F401
from app.db.models import Base, Igreja, Pessoa
from app.domain.phone import normalize_phone
from app.services import pessoa_dedup
from app.services.pessoa_dedup import (
    find_active_pessoa_by_phone,
    insert_pessoa_or_get_winner,
    lock_canonical_phone,
)

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — fixture
# do pytest usada por injeção, não importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401


# ===========================================================================
# Bloco 1 — unitário (sem Postgres): lógica de ramificação da guarda
# ===========================================================================
def _integrity_error(
    *,
    pgcode: str | None = None,
    sqlstate: str | None = None,
    constraint_name: str | None = None,
) -> IntegrityError:
    """Create a DBAPI-shaped error for both psycopg major versions."""

    class _Orig:
        pass

    orig = _Orig()
    orig.pgcode = pgcode
    orig.sqlstate = sqlstate
    orig.diag = type("_Diag", (), {"constraint_name": constraint_name})()
    return IntegrityError("insert", {}, orig)


def _unique_violation(*, via_sqlstate: bool = False, constraint_name: str | None = None) -> IntegrityError:
    """unique_violation from psycopg2 (pgcode) or psycopg3 (sqlstate)."""

    return _integrity_error(
        pgcode=None if via_sqlstate else "23505",
        sqlstate="23505" if via_sqlstate else None,
        constraint_name=constraint_name or "uq_pessoas_telefone_ativa",
    )


def _foreign_key_violation() -> IntegrityError:
    """IntegrityError NÃO-unique (23503) — deve subir inalterada."""

    return _integrity_error(pgcode="23503", constraint_name="pessoas_igreja_id_fkey")


class _FakeNested:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db

    def __enter__(self) -> _FakeNested:
        self._db.events.append("enter_nested")
        return self

    def __exit__(self, *exc: object) -> bool:
        self._db.events.append("exit_nested")
        return False


class _FakeResult:
    def __init__(self, rows: list[Pessoa]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Pessoa]:
        return self._rows


class _FakeDB:
    """Session mínima que separa flush externo do flush da candidata."""

    def __init__(
        self,
        *,
        raise_on_flush: IntegrityError | None,
        winners: list[Pessoa],
        winner_batches: list[list[Pessoa]] | None = None,
        raise_on_outer_flush: BaseException | None = None,
    ) -> None:
        self._raise_on_candidate_flush = raise_on_flush
        self._raise_on_outer_flush = raise_on_outer_flush
        self._winners = winners
        self._winner_batches = list(winner_batches or [])
        self.added: list[Pessoa] = []
        self.execute_calls = 0
        self.events: list[str] = []

    def begin_nested(self) -> _FakeNested:
        self.events.append("begin_nested")
        return _FakeNested(self)

    def add(self, obj: Pessoa) -> None:
        self.events.append("add")
        self.added.append(obj)

    def flush(self) -> None:
        if not self.added:
            self.events.append("outer_flush")
            if self._raise_on_outer_flush is not None:
                raise self._raise_on_outer_flush
            return
        self.events.append("candidate_flush")
        if self._raise_on_candidate_flush is not None:
            raise self._raise_on_candidate_flush

    def execute(self, _stmt: object) -> _FakeResult:
        self.execute_calls += 1
        rows = self._winner_batches.pop(0) if self._winner_batches else self._winners
        return _FakeResult(rows)


_IGREJA = uuid.UUID("0e0e1e0e-0000-0000-0000-0000000000e1")


def _pessoa(telefone: str) -> Pessoa:
    return Pessoa(id=uuid.uuid4(), igreja_id=_IGREJA, nome="X", telefone=telefone)


def test_happy_path_returns_the_new_pessoa() -> None:
    db = _FakeDB(raise_on_flush=None, winners=[])
    novo = _pessoa("11912345678")
    got = insert_pessoa_or_get_winner(
        db, novo, igreja_id=_IGREJA, canonical="11912345678"
    )
    assert got is novo
    assert db.added == [novo]
    assert db.events == [
        "outer_flush",
        "begin_nested",
        "enter_nested",
        "add",
        "candidate_flush",
        "exit_nested",
    ]


@pytest.mark.parametrize(
    "outer_error",
    [_unique_violation(), RuntimeError("outer flush failed")],
    ids=["unique-violation", "non-integrity-error"],
)
def test_outer_flush_error_bubbles_without_winner_lookup(
    outer_error: BaseException,
) -> None:
    db = _FakeDB(
        raise_on_flush=None,
        raise_on_outer_flush=outer_error,
        winners=[_pessoa("11912345678")],
    )

    with pytest.raises(type(outer_error)) as exc_info:
        insert_pessoa_or_get_winner(
            db, _pessoa("21912345678"), igreja_id=_IGREJA, canonical="21912345678"
        )

    assert exc_info.value is outer_error
    assert db.execute_calls == 0
    assert db.added == []
    assert db.events == ["outer_flush"]


def test_unique_violation_refetches_and_returns_winner() -> None:
    vencedora = _pessoa("11912345678")
    db = _FakeDB(raise_on_flush=_unique_violation(), winners=[vencedora])
    perdedora = _pessoa("11912345678")
    got = insert_pessoa_or_get_winner(
        db, perdedora, igreja_id=_IGREJA, canonical="11912345678"
    )
    assert got is vencedora
    assert got is not perdedora


def test_psycopg3_sqlstate_unique_violation_refetches_and_returns_winner() -> None:
    vencedora = _pessoa("11912345678")
    db = _FakeDB(
        raise_on_flush=_unique_violation(via_sqlstate=True), winners=[vencedora]
    )
    got = insert_pessoa_or_get_winner(
        db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
    )
    assert got is vencedora


def test_non_unique_integrity_error_bubbles_up() -> None:
    db = _FakeDB(raise_on_flush=_foreign_key_violation(), winners=[])
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )


def test_unique_violation_without_matching_winner_bubbles_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 23505 mas o re-fetch não acha vencedora canônica (ex.: colisão em outro
    # índice) — não mascarar: sobe.
    db = _FakeDB(raise_on_flush=_unique_violation(), winners=[])
    monkeypatch.setattr(pessoa_dedup.time, "sleep", lambda _delay: None)
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )
    assert db.execute_calls == 3


def test_other_unique_constraint_bubbles_up_even_with_a_matching_winner() -> None:
    vencedora = _pessoa("11912345678")
    db = _FakeDB(
        raise_on_flush=_unique_violation(constraint_name="uq_other_unique"),
        winners=[vencedora],
    )
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )
    assert db.execute_calls == 0


def test_winner_visibility_retry_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    vencedora = _pessoa("11912345678")
    db = _FakeDB(
        raise_on_flush=_unique_violation(),
        winners=[],
        winner_batches=[[], [], [vencedora]],
    )
    sleeps: list[float] = []
    monkeypatch.setattr(pessoa_dedup.time, "sleep", sleeps.append)

    got = insert_pessoa_or_get_winner(
        db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
    )

    assert got is vencedora
    assert db.execute_calls == 3
    assert sleeps == [0.01, 0.05]


def test_refetch_ignores_suffix_collision_of_a_different_number() -> None:
    # Mesmo sufixo de 8 dígitos, DDD diferente ⇒ número CANÔNICO diferente. O
    # re-fetch confirma a igualdade canônica em Python e NÃO devolve o intruso.
    intruso = _pessoa("21912345678")  # DDD 21, mesmo sufixo 12345678
    db = _FakeDB(raise_on_flush=_unique_violation(), winners=[intruso])
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )


class _PhoneLockDB:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, int]]] = []

    def execute(self, statement, params=None) -> _FakeResult:
        self.calls.append((str(statement), dict(params or {})))
        return _FakeResult([])


def test_canonical_phone_lock_is_stable_and_tenant_scoped() -> None:
    db = _PhoneLockDB()
    lock_canonical_phone(db, igreja_id=_IGREJA, canonical="5511912345678")
    lock_canonical_phone(db, igreja_id=_IGREJA, canonical="5511912345678")
    lock_canonical_phone(db, igreja_id=uuid.uuid4(), canonical="5511912345678")

    assert all("pg_advisory_xact_lock" in sql for sql, _ in db.calls)
    keys = [params["canonical_phone_key"] for _, params in db.calls]
    assert keys[0] == keys[1]
    assert keys[0] != keys[2]


def test_all_canonical_phone_writers_lock_before_lookup() -> None:
    from app.routers import auth, contacts
    from app.workers import queue_worker

    writers = (
        auth._prepare_cadastro_pessoa,
        contacts.create_contact,
        queue_worker.ingest_message_event_ex,
    )
    for writer in writers:
        source = inspect.getsource(writer)
        lock_at = source.index("lock_canonical_phone(")
        lookup_at = source.index("stored_digits")
        insert_at = source.index("insert_pessoa_or_get_winner(")
        assert lock_at < lookup_at < insert_at
        between_lock_and_insert = source[lock_at:insert_at]
        assert "db.commit(" not in between_lock_and_insert
        assert "db.rollback(" not in between_lock_and_insert
        assert "db.begin(" not in between_lock_and_insert


# ===========================================================================
# Bloco 2 — integração Postgres (opt-in): índice parcial + corrida real
# ===========================================================================
pytestmark_integration = pytest.mark.rls_integration

_SCHEMA = "uniq_pessoa1"
_IGREJA_A = uuid.UUID("0a0a1a0a-0000-0000-0000-00000000aa01")
_IGREJA_B = uuid.UUID("0b0b1b0b-0000-0000-0000-00000000bb01")
_TELEFONE = "11912345678"


@pytest.fixture
def engine_fx(rls_database_url: str) -> Iterator[Engine]:
    """Engine contra o Postgres descartável, schema próprio recriado do zero.

    ``Base.metadata.create_all`` materializa ``uq_pessoas_telefone_ativa`` a
    partir do ``__table_args__`` do modelo Pessoa (mesma definição da migration).
    """
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA}"},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
        )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _seed_igrejas(factory: sessionmaker) -> None:
    session = factory()
    try:
        session.add(Igreja(id=_IGREJA_A, nome="Igreja A"))
        session.add(Igreja(id=_IGREJA_B, nome="Igreja B"))
        session.commit()
    finally:
        session.close()


def _count_active(
    factory: sessionmaker, igreja_id: uuid.UUID, telefone: str = _TELEFONE
) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text(
                    "select count(*) from pessoas where igreja_id = :i "
                    "and telefone = :t and arquivada_em is null"
                ),
                {"i": igreja_id, "t": telefone},
            ).scalar_one()
        )
    finally:
        session.close()


def _active_with_canonical_phone(
    factory: sessionmaker, igreja_id: uuid.UUID, canonical: str
) -> list[Pessoa]:
    session = factory()
    try:
        pessoas = session.execute(
            select(Pessoa).where(
                Pessoa.igreja_id == igreja_id,
                Pessoa.arquivada_em.is_(None),
            )
        ).scalars()
        return [pessoa for pessoa in pessoas if normalize_phone(pessoa.telefone) == canonical]
    finally:
        session.close()


def _run_concurrent_creates(
    factory: sessionmaker,
    *,
    igreja_id: uuid.UUID,
    raw_phones: list[str],
    acquire_advisory_lock: bool,
) -> tuple[list[tuple[uuid.UUID, bool]], list[BaseException], list[threading.Thread]]:
    """Run real concurrent creates and record ``(pessoa_id, created)``."""

    barrier = threading.Barrier(len(raw_phones))
    results: list[tuple[uuid.UUID, bool]] = []
    errors: list[BaseException] = []

    def worker(idx: int, raw_phone: str) -> None:
        session = factory()
        try:
            canonical = normalize_phone(raw_phone)
            assert canonical
            novo = Pessoa(igreja_id=igreja_id, nome=f"P{idx}", telefone=raw_phone)
            barrier.wait(timeout=10)
            if acquire_advisory_lock:
                lock_canonical_phone(
                    session, igreja_id=igreja_id, canonical=canonical
                )
                pessoa = find_active_pessoa_by_phone(
                    session, igreja_id=igreja_id, canonical=canonical
                )
                if pessoa is None:
                    pessoa = insert_pessoa_or_get_winner(
                        session, novo, igreja_id=igreja_id, canonical=canonical
                    )
                created = pessoa is novo
            else:
                pessoa = insert_pessoa_or_get_winner(
                    session, novo, igreja_id=igreja_id, canonical=canonical
                )
                created = pessoa is novo
            session.commit()
            results.append((pessoa.id, created))
        except BaseException as exc:  # noqa: BLE001 — reportar no thread principal
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(idx, raw_phone))
        for idx, raw_phone in enumerate(raw_phones)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return results, errors, threads


def _waiting_advisory_locks(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("select count(*) from pg_locks where locktype = 'advisory' and not granted")
            ).scalar_one()
        )


@pytestmark_integration
def test_concurrent_creates_same_phone_yield_one_pessoa(engine_fx: Engine) -> None:
    """(a) Duas criações concorrentes do mesmo telefone/tenant ⇒ UMA Pessoa.

    Dispara ``insert_pessoa_or_get_winner`` em duas Sessions/conexões distintas
    ao mesmo tempo; o índice serializa, a perdedora pega 23505 e re-busca a
    vencedora. Ao final: exatamente UMA pessoa ativa, e ambas as chamadas
    devolvem a MESMA Pessoa.
    """
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    results, errors, threads = _run_concurrent_creates(
        factory,
        igreja_id=_IGREJA_A,
        raw_phones=[_TELEFONE, _TELEFONE],
        acquire_advisory_lock=False,
    )
    assert not errors, f"nenhum worker devia falhar: {errors!r}"
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert len({pessoa_id for pessoa_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert _count_active(factory, _IGREJA_A) == 1
    assert _waiting_advisory_locks(engine_fx) == 0


@pytestmark_integration
@pytest.mark.parametrize("workers", (2, 5, 10))
def test_canonical_phone_variations_converge_under_advisory_lock(
    engine_fx: Engine, workers: int
) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    variants = ["11912345678", "+55 11 91234-5678", "11 1234-5678"]
    raw_phones = [variants[index % len(variants)] for index in range(workers)]
    canonical = normalize_phone(raw_phones[0])

    results, errors, threads = _run_concurrent_creates(
        factory,
        igreja_id=_IGREJA_A,
        raw_phones=raw_phones,
        acquire_advisory_lock=True,
    )

    assert all(normalize_phone(raw_phone) == canonical for raw_phone in raw_phones)
    assert not errors, f"nenhum worker devia falhar: {errors!r}"
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == workers
    assert len({pessoa_id for pessoa_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert len(_active_with_canonical_phone(factory, _IGREJA_A, canonical)) == 1
    assert _waiting_advisory_locks(engine_fx) == 0


@pytestmark_integration
def test_repeated_two_way_race_converges_fifty_times(engine_fx: Engine) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)

    for iteration in range(50):
        telefone = f"119{12_340_000 + iteration:08d}"
        results, errors, threads = _run_concurrent_creates(
            factory,
            igreja_id=_IGREJA_A,
            raw_phones=[telefone, telefone],
            acquire_advisory_lock=False,
        )

        assert not errors, f"iteration={iteration}: {errors!r}"
        assert not any(thread.is_alive() for thread in threads)
        assert len({pessoa_id for pessoa_id, _ in results}) == 1
        assert sum(created for _, created in results) == 1
        assert _count_active(factory, _IGREJA_A, telefone) == 1

    assert _waiting_advisory_locks(engine_fx) == 0


@pytestmark_integration
def test_different_phones_same_tenant_remain_independent(engine_fx: Engine) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    phones = ["11912345678", "21912345678"]

    results, errors, threads = _run_concurrent_creates(
        factory,
        igreja_id=_IGREJA_A,
        raw_phones=phones,
        acquire_advisory_lock=True,
    )

    assert not errors, f"nenhum worker devia falhar: {errors!r}"
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert len({pessoa_id for pessoa_id, _ in results}) == 2
    assert all(created for _, created in results)
    assert all(
        len(_active_with_canonical_phone(factory, _IGREJA_A, normalize_phone(phone)))
        == 1
        for phone in phones
    )
    assert _waiting_advisory_locks(engine_fx) == 0


@pytestmark_integration
def test_different_tenants_same_phone_coexist(engine_fx: Engine) -> None:
    """(b) Tenants diferentes com o MESMO telefone coexistem (chave por igreja)."""
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)

    for igreja in (_IGREJA_A, _IGREJA_B):
        session = factory()
        try:
            insert_pessoa_or_get_winner(
                session,
                Pessoa(igreja_id=igreja, nome="P", telefone=_TELEFONE),
                igreja_id=igreja,
                canonical=_TELEFONE,
            )
            session.commit()
        finally:
            session.close()

    assert _count_active(factory, _IGREJA_A) == 1
    assert _count_active(factory, _IGREJA_B) == 1


@pytestmark_integration
def test_pending_outer_phone_unique_violation_bubbles_without_winner_lookup(
    engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A falha anterior ao SAVEPOINT não é a corrida da candidata."""

    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    owner_session = factory()
    try:
        owner_session.add(
            Pessoa(igreja_id=_IGREJA_A, nome="Owner", telefone=_TELEFONE)
        )
        owner_session.commit()
    finally:
        owner_session.close()

    session = factory()
    try:
        session.add(
            Pessoa(igreja_id=_IGREJA_A, nome="Outer duplicate", telefone=_TELEFONE)
        )
        candidate = Pessoa(
            igreja_id=_IGREJA_A,
            nome="Candidate",
            telefone="21912345678",
        )

        def winner_lookup_must_not_run(*_args: object, **_kwargs: object) -> Pessoa:
            raise AssertionError("não deve procurar vencedora após flush externo")

        monkeypatch.setattr(
            pessoa_dedup, "find_active_pessoa_by_phone", winner_lookup_must_not_run
        )
        with pytest.raises(IntegrityError) as exc_info:
            insert_pessoa_or_get_winner(
                session,
                candidate,
                igreja_id=_IGREJA_A,
                canonical="21912345678",
            )

        assert not isinstance(exc_info.value, PendingRollbackError)
        assert getattr(exc_info.value.orig, "pgcode", None) == "23505"
        assert exc_info.value.orig.diag.constraint_name == "uq_pessoas_telefone_ativa"
        assert not session.is_active
        assert sa_inspect(candidate).transient
    finally:
        session.rollback()
        session.close()

    assert _count_active(factory, _IGREJA_A, _TELEFONE) == 1
    assert _count_active(factory, _IGREJA_A, "21912345678") == 0


@pytestmark_integration
def test_other_unique_constraint_is_repropagated_and_outer_rollback_works(
    engine_fx: Engine,
) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    with engine_fx.begin() as connection:
        connection.execute(
            text(
                "create unique index uq_pessoas_email_hotfix "
                "on pessoas (igreja_id, email) where email is not null"
            )
        )

    session = factory()
    try:
        session.add(
            Pessoa(
                igreja_id=_IGREJA_A,
                nome="Email owner",
                telefone=_TELEFONE,
                email="duplicate@example.test",
            )
        )
        session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            insert_pessoa_or_get_winner(
                session,
                Pessoa(
                    igreja_id=_IGREJA_A,
                    nome="Email contender",
                    telefone="21912345678",
                    email="duplicate@example.test",
                ),
                igreja_id=_IGREJA_A,
                canonical="21912345678",
            )

        assert exc_info.value.orig.diag.constraint_name == "uq_pessoas_email_hotfix"
        assert session.in_transaction()
        session.rollback()
        session.add(
            Pessoa(
                igreja_id=_IGREJA_A,
                nome="Usable after rollback",
                telefone="31912345678",
                email="unique@example.test",
            )
        )
        session.commit()
    finally:
        session.close()

    assert _count_active(factory, _IGREJA_A, "31912345678") == 1


@pytestmark_integration
def test_pending_outer_other_unique_violation_bubbles_without_winner_lookup(
    engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    with engine_fx.begin() as connection:
        connection.execute(
            text(
                "create unique index uq_pessoas_email_pending_hotfix "
                "on pessoas (igreja_id, email) where email is not null"
            )
        )

    owner_session = factory()
    try:
        owner_session.add(
            Pessoa(
                igreja_id=_IGREJA_A,
                nome="Email owner",
                telefone=_TELEFONE,
                email="duplicate@example.test",
            )
        )
        owner_session.commit()
    finally:
        owner_session.close()

    session = factory()
    try:
        session.add(
            Pessoa(
                igreja_id=_IGREJA_A,
                nome="Outer email duplicate",
                telefone="21912345678",
                email="duplicate@example.test",
            )
        )
        candidate = Pessoa(
            igreja_id=_IGREJA_A,
            nome="Candidate",
            telefone="31912345678",
            email="candidate@example.test",
        )

        def winner_lookup_must_not_run(*_args: object, **_kwargs: object) -> Pessoa:
            raise AssertionError("não deve procurar vencedora após flush externo")

        monkeypatch.setattr(
            pessoa_dedup, "find_active_pessoa_by_phone", winner_lookup_must_not_run
        )
        with pytest.raises(IntegrityError) as exc_info:
            insert_pessoa_or_get_winner(
                session,
                candidate,
                igreja_id=_IGREJA_A,
                canonical="31912345678",
            )

        assert not isinstance(exc_info.value, PendingRollbackError)
        assert getattr(exc_info.value.orig, "pgcode", None) == "23505"
        assert exc_info.value.orig.diag.constraint_name == "uq_pessoas_email_pending_hotfix"
        assert not session.is_active
        assert sa_inspect(candidate).transient
    finally:
        session.rollback()
        session.close()


@pytestmark_integration
def test_deduplication_preserves_pending_outer_transaction_changes(
    engine_fx: Engine,
) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    winner_session = factory()
    try:
        winner = Pessoa(igreja_id=_IGREJA_A, nome="Winner", telefone=_TELEFONE)
        winner_session.add(winner)
        winner_session.commit()
        winner_id = winner.id
    finally:
        winner_session.close()

    session = factory()
    try:
        pending = Pessoa(
            igreja_id=_IGREJA_A,
            nome="Pending outer transaction",
            telefone="21912345678",
        )
        session.add(pending)
        deduped = insert_pessoa_or_get_winner(
            session,
            Pessoa(igreja_id=_IGREJA_A, nome="Loser", telefone=_TELEFONE),
            igreja_id=_IGREJA_A,
            canonical=_TELEFONE,
        )

        assert deduped.id == winner_id
        assert session.in_transaction()
        assert sa_inspect(pending).persistent
        session.rollback()
    finally:
        session.close()

    assert _count_active(factory, _IGREJA_A) == 1
    assert _count_active(factory, _IGREJA_A, "21912345678") == 0


@pytestmark_integration
@pytest.mark.parametrize(
    ("candidate_state", "message_fragment"),
    [
        ("pending", "pending"),
        ("persistent", "persistent"),
        ("detached", "detached"),
        ("other-session", "outra Session"),
    ],
)
def test_non_transient_candidate_is_rejected_without_helper_insert(
    engine_fx: Engine, candidate_state: str, message_fragment: str
) -> None:
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)
    session = factory()
    other_session: Session | None = None
    candidate = Pessoa(
        igreja_id=_IGREJA_A,
        nome="Already attached",
        telefone="31912345678",
    )
    try:
        if candidate_state == "pending":
            session.add(candidate)
        elif candidate_state == "persistent":
            session.add(candidate)
            session.flush()
        elif candidate_state == "detached":
            session.add(candidate)
            session.commit()
            session.expunge(candidate)
        else:
            other_session = factory()
            other_session.add(candidate)

        with pytest.raises(ValueError, match=message_fragment):
            insert_pessoa_or_get_winner(
                session,
                candidate,
                igreja_id=_IGREJA_A,
                canonical="31912345678",
            )

        if candidate_state == "pending":
            assert sa_inspect(candidate).pending
        elif candidate_state == "persistent":
            assert sa_inspect(candidate).persistent
        elif candidate_state == "detached":
            assert sa_inspect(candidate).detached
        else:
            assert other_session is not None
            assert sa_inspect(candidate).session is other_session
        assert session.is_active
    finally:
        session.rollback()
        session.close()
        if other_session is not None:
            other_session.rollback()
            other_session.close()


@pytestmark_integration
def test_archived_phone_does_not_block_new_active(engine_fx: Engine) -> None:
    """(c) Telefone de pessoa ARQUIVADA não bloqueia recriar uma ativa.

    Índice parcial sobre ``arquivada_em IS NULL`` ⇒ a arquivada sai do índice.
    """
    _seed_igrejas(_factory(engine_fx))
    factory = _factory(engine_fx)

    # Arquivada com o telefone.
    session = factory()
    try:
        session.add(
            Pessoa(
                igreja_id=_IGREJA_A,
                nome="Arquivada",
                telefone=_TELEFONE,
                arquivada_em=dt.datetime.now(dt.timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()

    # Nova ATIVA com o MESMO telefone entra sem colidir.
    session = factory()
    try:
        nova = insert_pessoa_or_get_winner(
            session,
            Pessoa(igreja_id=_IGREJA_A, nome="Nova", telefone=_TELEFONE),
            igreja_id=_IGREJA_A,
            canonical=_TELEFONE,
        )
        session.commit()
        assert nova.nome == "Nova"
    finally:
        session.close()

    assert _count_active(factory, _IGREJA_A) == 1
    # E o re-fetch de ativa acha a NOVA, não a arquivada.
    session = factory()
    try:
        found = find_active_pessoa_by_phone(
            session, igreja_id=_IGREJA_A, canonical=_TELEFONE
        )
        assert found is not None and found.nome == "Nova"
    finally:
        session.close()

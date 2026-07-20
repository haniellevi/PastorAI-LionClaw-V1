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
import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

# Importar session.py registra (uma vez) o listener after_begin do seam de tenant
# — paridade com produção. As sessões deste teste NÃO são marcadas ⇒ no-op.
import app.db.session  # noqa: F401
from app.db.models import Base, Igreja, Pessoa
from app.services.pessoa_dedup import (
    find_active_pessoa_by_phone,
    insert_pessoa_or_get_winner,
)

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — fixture
# do pytest usada por injeção, não importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401


# ===========================================================================
# Bloco 1 — unitário (sem Postgres): lógica de ramificação da guarda
# ===========================================================================
def _unique_violation() -> IntegrityError:
    """IntegrityError com orig.pgcode == '23505' (unique_violation do Postgres)."""

    class _Orig:
        pgcode = "23505"

    return IntegrityError("insert", {}, _Orig())


def _foreign_key_violation() -> IntegrityError:
    """IntegrityError NÃO-unique (23503) — deve subir inalterada."""

    class _Orig:
        pgcode = "23503"

    return IntegrityError("insert", {}, _Orig())


class _FakeNested:
    def __enter__(self) -> _FakeNested:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeResult:
    def __init__(self, rows: list[Pessoa]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Pessoa]:
        return self._rows


class _FakeDB:
    """Session mínima: begin_nested/add/flush + execute do re-fetch."""

    def __init__(
        self, *, raise_on_flush: IntegrityError | None, winners: list[Pessoa]
    ) -> None:
        self._raise = raise_on_flush
        self._winners = winners
        self.added: list[Pessoa] = []

    def begin_nested(self) -> _FakeNested:
        return _FakeNested()

    def add(self, obj: Pessoa) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        if self._raise is not None:
            raise self._raise

    def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._winners)


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


def test_unique_violation_refetches_and_returns_winner() -> None:
    vencedora = _pessoa("11912345678")
    db = _FakeDB(raise_on_flush=_unique_violation(), winners=[vencedora])
    perdedora = _pessoa("11912345678")
    got = insert_pessoa_or_get_winner(
        db, perdedora, igreja_id=_IGREJA, canonical="11912345678"
    )
    assert got is vencedora
    assert got is not perdedora


def test_non_unique_integrity_error_bubbles_up() -> None:
    db = _FakeDB(raise_on_flush=_foreign_key_violation(), winners=[])
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )


def test_unique_violation_without_matching_winner_bubbles_up() -> None:
    # 23505 mas o re-fetch não acha vencedora canônica (ex.: colisão em outro
    # índice) — não mascarar: sobe.
    db = _FakeDB(raise_on_flush=_unique_violation(), winners=[])
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )


def test_refetch_ignores_suffix_collision_of_a_different_number() -> None:
    # Mesmo sufixo de 8 dígitos, DDD diferente ⇒ número CANÔNICO diferente. O
    # re-fetch confirma a igualdade canônica em Python e NÃO devolve o intruso.
    intruso = _pessoa("21912345678")  # DDD 21, mesmo sufixo 12345678
    db = _FakeDB(raise_on_flush=_unique_violation(), winners=[intruso])
    with pytest.raises(IntegrityError):
        insert_pessoa_or_get_winner(
            db, _pessoa("11912345678"), igreja_id=_IGREJA, canonical="11912345678"
        )


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


def _count_active(factory: sessionmaker, igreja_id: uuid.UUID) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text(
                    "select count(*) from pessoas where igreja_id = :i "
                    "and telefone = :t and arquivada_em is null"
                ),
                {"i": igreja_id, "t": _TELEFONE},
            ).scalar_one()
        )
    finally:
        session.close()


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

    barrier = threading.Barrier(2)
    results: dict[int, uuid.UUID] = {}
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        session = factory()
        try:
            novo = Pessoa(igreja_id=_IGREJA_A, nome=f"P{idx}", telefone=_TELEFONE)
            barrier.wait(timeout=10)
            pessoa = insert_pessoa_or_get_winner(
                session, novo, igreja_id=_IGREJA_A, canonical=_TELEFONE
            )
            session.commit()
            results[idx] = pessoa.id
        except BaseException as exc:  # noqa: BLE001 — reportar no thread principal
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"nenhum worker devia falhar: {errors!r}"
    assert set(results) == {0, 1}
    assert results[0] == results[1], "ambas as chamadas devem convergir na mesma Pessoa"
    assert _count_active(factory, _IGREJA_A) == 1


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

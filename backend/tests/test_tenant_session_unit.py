"""Testes unitários do seam de tenant (PR2) — SEM Postgres real.

Exercitam APENAS a mecânica das funções de marcação e do listener: o contrato de
`session.info`, a hierarquia de exceções e o no-op do listener quando a sessão
não está marcada. NÃO exercitam o enforcement da RLS (isso é integração, em
`test_rls_invariant.py`). Rodam SEMPRE, offline (sem RLS_TEST_DATABASE_URL).
"""

from __future__ import annotations

import pytest

from app.db.tenant_session import (
    CROSS_TENANT_KEY,
    TENANT_IGREJA_KEY,
    TENANT_META_KEY,
    TenantPinConflictError,
    TenantPromotionError,
    TenantScopeError,
    _reapply_tenant_scope,
    mark_cross_tenant,
    mark_tenant_scoped,
    promote_to_tenant,
)

IGREJA_A = "0a0a0a0a-0000-0000-0000-00000000000a"
IGREJA_B = "0b0b0b0b-0000-0000-0000-00000000000b"


# ---------------------------------------------------------------------------
# Fakes mínimos (sem DB): capturam o SQL emitido, guardam session.info.
# ---------------------------------------------------------------------------
class _FakeSession:
    """Sessão fake: `.info` dict + `.execute` que só registra (no-op no banco)."""

    def __init__(self) -> None:
        self.info: dict = {}
        self.executed: list[tuple[str, dict | None]] = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return None


class _FakeConnection:
    """Conexão fake: registra cada exec_driver_sql (statement, params)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple | None]] = []

    def exec_driver_sql(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        return None


# ---------------------------------------------------------------------------
# mark_tenant_scoped — grava session.info + aplica
# ---------------------------------------------------------------------------
def test_mark_tenant_scoped_writes_info_and_applies() -> None:
    s = _FakeSession()
    mark_tenant_scoped(
        s, IGREJA_A, actor_sub="clerk-x", actor_role="pastor", source="http"
    )

    assert s.info[TENANT_IGREJA_KEY] == IGREJA_A
    meta = s.info[TENANT_META_KEY]
    assert meta["source"] == "http"
    assert meta["actor_sub"] == "clerk-x"
    assert meta["actor_role"] == "pastor"
    assert meta["cross_tenant"] is False
    assert CROSS_TENANT_KEY not in s.info

    # Aplicou o escopo imediatamente na transação atual (GUC + role).
    sqls = " ".join(sql for sql, _ in s.executed)
    assert "app.tenant_igreja_id" in sqls
    assert "set local role authenticated" in sqls
    bound = [p for _, p in s.executed if p]
    assert bound and bound[0]["igreja_id"] == IGREJA_A


def test_mark_tenant_scoped_coerces_non_str_id() -> None:
    s = _FakeSession()
    mark_tenant_scoped(s, 12345, source="http")
    assert s.info[TENANT_IGREJA_KEY] == "12345"


def test_mark_tenant_scoped_same_igreja_is_idempotent() -> None:
    s = _FakeSession()
    mark_tenant_scoped(s, IGREJA_A, actor_sub="first", source="http")
    first_meta = s.info[TENANT_META_KEY]
    # Segunda marcação no MESMO tenant: sem erro, meta original preservada.
    mark_tenant_scoped(s, IGREJA_A, actor_sub="second", source="worker")
    assert s.info[TENANT_IGREJA_KEY] == IGREJA_A
    assert s.info[TENANT_META_KEY] is first_meta  # meta não sobrescrita
    # Reaplicou (mais SQL emitido na 2ª chamada).
    assert len(s.executed) >= 4


def test_mark_tenant_scoped_different_igreja_conflicts() -> None:
    s = _FakeSession()
    mark_tenant_scoped(s, IGREJA_A, source="http")
    with pytest.raises(TenantPinConflictError):
        mark_tenant_scoped(s, IGREJA_B, source="http")
    # O pin original permanece intocado.
    assert s.info[TENANT_IGREJA_KEY] == IGREJA_A


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_mark_tenant_scoped_rejects_empty_igreja(bad) -> None:
    s = _FakeSession()
    with pytest.raises(ValueError):
        mark_tenant_scoped(s, bad, source="http")
    # Não marcou nada (recusa na entrada, fail-closed).
    assert TENANT_IGREJA_KEY not in s.info
    assert not s.executed


# ---------------------------------------------------------------------------
# mark_cross_tenant — sessão unscoped; sem igreja em session.info
# ---------------------------------------------------------------------------
def test_mark_cross_tenant_sets_flag_without_igreja() -> None:
    s = _FakeSession()
    mark_cross_tenant(s, actor_sub="platform-admin", source="console")
    assert s.info[CROSS_TENANT_KEY] is True
    assert TENANT_IGREJA_KEY not in s.info
    meta = s.info[TENANT_META_KEY]
    assert meta["cross_tenant"] is True
    assert meta["source"] == "console"
    # cross-tenant NÃO aplica escopo (nenhum SQL de GUC/role).
    assert not s.executed


def test_mark_cross_tenant_listener_is_noop() -> None:
    s = _FakeSession()
    mark_cross_tenant(s, source="console")
    conn = _FakeConnection()
    _reapply_tenant_scope(s, transaction=None, connection=conn)
    assert conn.calls == []  # listener não reaplica escopo em cross-tenant


# ---------------------------------------------------------------------------
# Exclusão mútua scoped × cross-tenant
# ---------------------------------------------------------------------------
def test_scoped_then_cross_tenant_raises() -> None:
    s = _FakeSession()
    mark_tenant_scoped(s, IGREJA_A, source="http")
    with pytest.raises(TenantPinConflictError):
        mark_cross_tenant(s, source="console")


def test_cross_tenant_then_scoped_raises() -> None:
    s = _FakeSession()
    mark_cross_tenant(s, source="console")
    with pytest.raises(TenantPinConflictError):
        mark_tenant_scoped(s, IGREJA_A, source="http")


# ---------------------------------------------------------------------------
# promote_to_tenant — só válido a partir de cross-tenant
# ---------------------------------------------------------------------------
def test_promote_from_cross_tenant_succeeds() -> None:
    s = _FakeSession()
    mark_cross_tenant(s, source="console")
    promote_to_tenant(s, IGREJA_A, source="promoted")
    assert s.info[TENANT_IGREJA_KEY] == IGREJA_A
    assert CROSS_TENANT_KEY not in s.info
    meta = s.info[TENANT_META_KEY]
    assert meta["promoted_from_cross_tenant"] is True
    # Promoção aplica o escopo imediatamente.
    sqls = " ".join(sql for sql, _ in s.executed)
    assert "app.tenant_igreja_id" in sqls
    assert "set local role authenticated" in sqls


def test_promote_without_cross_tenant_phase_raises() -> None:
    s = _FakeSession()  # sessão nova, nunca marcada cross-tenant
    with pytest.raises(TenantPromotionError):
        promote_to_tenant(s, IGREJA_A, source="promoted")


def test_promote_over_pinned_session_raises() -> None:
    s = _FakeSession()
    mark_tenant_scoped(s, IGREJA_A, source="http")
    # Já pinada num tenant (não veio de cross-tenant) → não pode promover.
    with pytest.raises(TenantPromotionError):
        promote_to_tenant(s, IGREJA_A, source="promoted")


def test_promote_to_different_igreja_of_pinned_raises() -> None:
    s = _FakeSession()
    mark_tenant_scoped(s, IGREJA_A, source="http")
    with pytest.raises(TenantPromotionError):
        promote_to_tenant(s, IGREJA_B, source="promoted")


# ---------------------------------------------------------------------------
# Hierarquia de exceções
# ---------------------------------------------------------------------------
def test_exception_hierarchy() -> None:
    assert issubclass(TenantPinConflictError, TenantScopeError)
    assert issubclass(TenantPromotionError, TenantScopeError)
    assert issubclass(TenantScopeError, RuntimeError)


# ---------------------------------------------------------------------------
# Listener no-op quando a sessão NÃO está marcada
# ---------------------------------------------------------------------------
def test_listener_noop_when_unmarked() -> None:
    s = _FakeSession()  # session.info vazio
    conn = _FakeConnection()
    _reapply_tenant_scope(s, transaction=None, connection=conn)
    assert conn.calls == []


def test_listener_reapplies_when_marked() -> None:
    s = _FakeSession()
    s.info[TENANT_IGREJA_KEY] = IGREJA_A  # simula sessão já marcada
    conn = _FakeConnection()
    _reapply_tenant_scope(s, transaction=None, connection=conn)

    statements = [stmt for stmt, _ in conn.calls]
    assert any("app.tenant_igreja_id" in s for s in statements)
    assert any("set local role authenticated" in s for s in statements)
    # igreja_id vai como PARÂMETRO de bind (tupla), não interpolado na string.
    guc_call = next(c for c in conn.calls if "set_config" in c[0])
    assert guc_call[1] == (IGREJA_A,)
    # Só formas transaction-local: is_local=true no set_config, SET LOCAL no role.
    assert ", true)" in guc_call[0]
    assert "set local role" in " ".join(statements)

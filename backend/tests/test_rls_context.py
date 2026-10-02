"""Helpers de tenant-context para RLS.

HTTP usa o claim do Clerk (set_tenant_context); o caminho assíncrono/worker usa
o GUC app.tenant_igreja_id (set_tenant_context_for_igreja, #10b Fase 0). Ambos
caem no papel `authenticated` para a RLS valer (o role de conexão tem BYPASSRLS).
A correção REAL da RLS só dá pra validar contra o Postgres do Supabase; aqui
garantimos que os helpers emitem o SQL certo e parametrizado (sem injeção).
"""

from __future__ import annotations

from app.db.rls import set_tenant_context, set_tenant_context_for_igreja


class _RecordingSession:
    """Captura cada execute(statement, params) como (sql_str, params)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return None


_ROLE_LOCAL = "set_config('role', 'authenticated', true)"


def test_set_tenant_context_for_igreja_sets_guc_and_role() -> None:
    s = _RecordingSession()
    set_tenant_context_for_igreja(s, "11111111-1111-1111-1111-111111111111")

    # GUC e papel numa única ida ao banco, ambos transaction-local.
    assert len(s.calls) == 1
    sql, params = s.calls[0]
    assert "set_config('app.tenant_igreja_id', :igreja_id, true)" in sql
    assert _ROLE_LOCAL in sql
    # igreja_id vai como parâmetro (cast a uuid em current_igreja_id) — sem
    # interpolação de string / injeção.
    assert params == {"igreja_id": "11111111-1111-1111-1111-111111111111"}
    assert "11111111" not in sql


def test_set_tenant_context_for_igreja_coerces_to_str() -> None:
    s = _RecordingSession()
    set_tenant_context_for_igreja(s, 12345)  # id não-str é coagido a str
    bound = [p for _, p in s.calls if p]
    assert bound and bound[0]["igreja_id"] == "12345"


def test_set_tenant_context_uses_clerk_subject() -> None:
    s = _RecordingSession()
    set_tenant_context(s, "clerk_user_42")

    # Claim e papel numa única ida ao banco, ambos transaction-local.
    assert len(s.calls) == 1
    sql, params = s.calls[0]
    assert "set_config('request.jwt.claims', :claims, true)" in sql
    assert _ROLE_LOCAL in sql
    assert params is not None and "clerk_user_42" in params["claims"]
    assert "clerk_user_42" not in sql

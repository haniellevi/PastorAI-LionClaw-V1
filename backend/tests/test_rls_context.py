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


def test_set_tenant_context_for_igreja_sets_guc_and_role() -> None:
    s = _RecordingSession()
    set_tenant_context_for_igreja(s, "11111111-1111-1111-1111-111111111111")

    sqls = " ".join(sql for sql, _ in s.calls)
    assert "app.tenant_igreja_id" in sqls
    assert "set local role authenticated" in sqls
    # igreja_id vai como parâmetro (cast a uuid em current_igreja_id) — sem
    # interpolação de string / injeção.
    bound = [p for _, p in s.calls if p]
    assert bound and bound[0]["igreja_id"] == "11111111-1111-1111-1111-111111111111"


def test_set_tenant_context_for_igreja_coerces_to_str() -> None:
    s = _RecordingSession()
    set_tenant_context_for_igreja(s, 12345)  # id não-str é coagido a str
    bound = [p for _, p in s.calls if p]
    assert bound and bound[0]["igreja_id"] == "12345"


def test_set_tenant_context_uses_clerk_subject() -> None:
    s = _RecordingSession()
    set_tenant_context(s, "clerk_user_42")

    sqls = " ".join(sql for sql, _ in s.calls)
    assert "request.jwt.claims" in sqls
    assert "set local role authenticated" in sqls
    bound = [p for _, p in s.calls if p]
    assert bound and "clerk_user_42" in bound[0]["claims"]

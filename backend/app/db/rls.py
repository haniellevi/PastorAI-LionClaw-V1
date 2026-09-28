"""Tenant context injection for Postgres Row Level Security.

The migration `current_igreja_id()` (SPEC 2.2) derives the tenant from
`request.jwt.claims ->> 'sub'`. To make the RLS policies effective for a
request we set that GUC on the active session so every query is automatically
scoped to the authenticated user's igreja.

We use `set_config(..., is_local => true)` so the value lives only for the
current transaction, preventing leakage across pooled connections.

Critically, the Supabase connection role (`postgres`) has BYPASSRLS, so RLS
policies are skipped entirely when querying as that role — the tenant claim
alone is not enough. We therefore drop the transaction to the `authenticated`
role (NOBYPASSRLS, already granted DML on the public tables) so the
`current_igreja_id()`-based policies are actually enforced at the database.
Without this, every tenant-scoped query would return all tenants' rows.

The role drop travels in the SAME statement as the tenant GUC, as
`set_config('role', 'authenticated', true)`. PostgreSQL applies it through the
same path as `SET LOCAL ROLE authenticated` (same membership check, reverted on
commit/rollback); PostgREST sets the role this way too. One statement means one
round trip to the database instead of two — each one costs ~185 ms between the
VPS and Supabase us-west-2.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

# Transaction-local equivalent of `SET LOCAL ROLE authenticated`, usable inside
# a SELECT so it shares the round trip with the tenant GUC. Also used, with the
# driver's own placeholder, by the after_begin listener in tenant_session.py.
ROLE_AUTHENTICATED_SQL = "set_config('role', 'authenticated', true)"


def set_tenant_context(session: Session, clerk_user_id: str) -> None:
    """Inject the Clerk subject into the session so RLS resolves the tenant.

    `current_igreja_id()` reads `request.jwt.claims ->> 'sub'`; we set exactly
    that claim shape. Bound as a parameter to avoid any injection.

    The same statement drops the transaction to a role subject to RLS. The
    connection role has BYPASSRLS, so without the role the policies are ignored
    and tenant isolation is lost. Both settings revert on commit/rollback.
    """
    claims = json.dumps({"sub": clerk_user_id})
    session.execute(
        text(
            "select set_config('request.jwt.claims', :claims, true), "
            f"{ROLE_AUTHENTICATED_SQL}"
        ),
        {"claims": claims},
    )


def set_tenant_context_for_igreja(session: Session, igreja_id: str) -> None:
    """Inject the tenant directly for async/worker paths that have no Clerk JWT.

    The WhatsApp worker processes inbound messages on behalf of a contact who
    has no Clerk login, so `set_tenant_context` (which needs a clerk_user_id)
    does not apply. We set the `app.tenant_igreja_id` GUC that
    `current_igreja_id()` also honors, then drop to the `authenticated` role so
    the RLS policies are actually enforced — exactly as the HTTP path does.

    Must be called AFTER any deliberately cross-tenant lookup (e.g. resolving an
    igreja from a WhatsApp `instance`), since dropping to `authenticated` makes
    every subsequent query in this transaction RLS-scoped to this igreja. The id
    is bound as a parameter (cast to uuid in `current_igreja_id`) to avoid any
    injection. GUC and role go in one statement, as in `set_tenant_context`.
    """
    session.execute(
        text(
            "select set_config('app.tenant_igreja_id', :igreja_id, true), "
            f"{ROLE_AUTHENTICATED_SQL}"
        ),
        {"igreja_id": str(igreja_id)},
    )


def clear_tenant_context(session: Session) -> None:
    """Reset the tenant claim for the current transaction.

    Auditoria OQ#3 (PR4+): esta função NÃO tem chamadores no código de produção
    (grep em ``backend/``). É intencionalmente mantida como primitivo, mas o
    novo modelo de escopo torna-a INÓCUA: ela apenas limpa
    ``request.jwt.claims`` e NÃO reverte o GUC ``app.tenant_igreja_id`` nem o
    ``SET LOCAL ROLE authenticated`` — que é o que de fato governa a RLS. Um
    caminho que queira DELIBERADAMENTE sair do escopo (rodar cross-tenant) deve
    usar ``app.db.tenant_session.mark_cross_tenant`` (saída nomeada/auditável,
    D4), nunca esta função — que não conseguiria "sair da RLS" de qualquer forma.
    """
    session.execute(
        text("select set_config('request.jwt.claims', '', true)"),
    )

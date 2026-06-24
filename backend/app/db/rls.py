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
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_tenant_context(session: Session, clerk_user_id: str) -> None:
    """Inject the Clerk subject into the session so RLS resolves the tenant.

    `current_igreja_id()` reads `request.jwt.claims ->> 'sub'`; we set exactly
    that claim shape. Bound as a parameter to avoid any injection.
    """
    claims = json.dumps({"sub": clerk_user_id})
    session.execute(
        text("select set_config('request.jwt.claims', :claims, true)"),
        {"claims": claims},
    )
    # Drop to a role subject to RLS for the rest of this transaction. The
    # connection role has BYPASSRLS, so without this the policies are ignored
    # and tenant isolation is lost. SET LOCAL reverts on commit/rollback.
    session.execute(text("set local role authenticated"))


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
    injection.
    """
    session.execute(
        text("select set_config('app.tenant_igreja_id', :igreja_id, true)"),
        {"igreja_id": str(igreja_id)},
    )
    # Same role drop as set_tenant_context: the connection role has BYPASSRLS,
    # so without this the policies are ignored. SET LOCAL reverts on commit.
    session.execute(text("set local role authenticated"))


def clear_tenant_context(session: Session) -> None:
    """Reset the tenant claim for the current transaction."""
    session.execute(
        text("select set_config('request.jwt.claims', '', true)"),
    )

"""Tenant context injection for Postgres Row Level Security.

The migration `current_igreja_id()` (SPEC 2.2) derives the tenant from
`request.jwt.claims ->> 'sub'`. To make the RLS policies effective for a
request we set that GUC on the active session so every query is automatically
scoped to the authenticated user's igreja.

We use `set_config(..., is_local => true)` so the value lives only for the
current transaction, preventing leakage across pooled connections.
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


def clear_tenant_context(session: Session) -> None:
    """Reset the tenant claim for the current transaction."""
    session.execute(
        text("select set_config('request.jwt.claims', '', true)"),
    )

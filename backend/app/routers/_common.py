"""Shared router helpers: pagination contract and tenant-context safety.

RNF-09 requires list endpoints to paginate. `PaginationParams` provides a
single, validated page/page_size contract reused across routers, and
`Page` is the standard envelope returned to clients.

`ensure_tenant_context` re-asserts the Postgres RLS GUC on the request session.
The GUC is transaction-local (set_config is_local=true): once a router commits,
the claim is cleared, so any read performed *after* a commit would lose tenant
scoping. Routers therefore call this at the top and avoid RLS-dependent reads
after committing (preferring flush + refresh before a single final commit).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.rls import set_tenant_context
from app.deps import CurrentUser

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class PaginationParams:
    """Validated pagination query parameters (?page=&pageSize=)."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="1-based page number"),
        page_size: int = Query(
            default=DEFAULT_PAGE_SIZE,
            ge=1,
            le=MAX_PAGE_SIZE,
            alias="pageSize",
            description="Items per page (max 100)",
        ),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page(BaseModel, Generic[T]):
    """Standard pagination envelope (RNF-09)."""

    items: list[T]
    page: int
    pageSize: int  # noqa: N815 - external contract uses camelCase
    total: int


def ensure_tenant_context(db: Session, current_user: CurrentUser) -> None:
    """Re-assert the RLS tenant claim for the current transaction."""
    set_tenant_context(db, current_user.clerk_user_id)

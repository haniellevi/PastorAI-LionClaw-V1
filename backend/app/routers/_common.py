"""Shared router helpers: pagination contract and tenant-context safety.

RNF-09 requires list endpoints to paginate. `PaginationParams` provides a
single, validated page/page_size contract reused across routers, and
`Page` is the standard envelope returned to clients.

`ensure_tenant_context` era historicamente chamado no topo de cada router para
re-asserir o GUC de RLS. Após o seam profundo por tenant (app/db/tenant_session),
essa re-asserção manual virou redundante — ver a docstring da própria função para
a decisão OQ#3 (PR4+): ela foi convertida num SHIM DE ASSERT fail-closed e as
chamadas foram removidas dos 26 routers.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.tenant_session import TENANT_IGREJA_KEY, TenantScopeError
from app.deps import CurrentUser

T = TypeVar("T")

# List screens load a single batch (no pagination UI yet), and plan tiers go up
# to 201+ people, so the cap matches the frontend's batch size (200) to avoid
# silently truncating contacts/cells/reports. True pagination is the long-term
# fix for tenants beyond a single batch.
MAX_PAGE_SIZE = 200
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
            description="Items per page (max 200)",
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
    """Shim de observabilidade fail-closed do escopo por tenant (decisão OQ#3).

    Historicamente esta função RE-SETAVA o GUC de RLS a cada chamada de router.
    Isso virou redundante: ``get_current_user`` (deps.py) marca a sessão com
    ``mark_tenant_scoped`` e o listener ``after_begin``
    (app/db/tenant_session.py) reaplica o escopo em TODA transação da sessão —
    inclusive nas leituras pós-commit. As chamadas nos 26 routers foram
    removidas no PR4+.

    Decisão OQ#3 (documentada aqui, no lugar canônico): em vez de REMOVER o
    símbolo, ele é MANTIDO como um SHIM DE ASSERT fail-closed. Se algum caminho
    (existente esquecido ou código futuro) o invocar, ele NÃO re-seta o escopo às
    cegas nem degrada para "seguir sem escopo": ele FALHA (``TenantScopeError``)
    caso a sessão não esteja marcada como tenant-scoped no MESMO igreja do usuário
    autenticado. É um sinal de regressão barulhento — nunca deixa uma sessão em
    BYPASSRLS passar por engano. Preferimos o shim à remoção justamente pela
    observabilidade contínua (fail-closed) que ele oferece a chamadores futuros.

    Raises:
        TenantScopeError: se a sessão não estiver marcada (seam não ativado) ou
            estiver pinada num igreja diferente do usuário autenticado.
    """
    igreja_id = db.info.get(TENANT_IGREJA_KEY)
    if not igreja_id or str(igreja_id) != str(current_user.igreja_id):
        raise TenantScopeError(
            "sessão não está marcada como tenant-scoped no igreja do usuário "
            "autenticado: get_current_user deveria tê-la marcado via "
            f"mark_tenant_scoped (esperado {current_user.igreja_id!r}, "
            f"marcado {igreja_id!r})"
        )

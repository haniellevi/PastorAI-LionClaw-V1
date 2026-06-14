"""Panel assistant router (api-assistant — O5).

Endpoint:
  - POST /assistant/message  {tenantId, usuarioId, papeis, texto}
                             -> {resposta, telasSugeridas}

The panel assistant is a **separate channel** from the WhatsApp Orchestrator
(delta-034): it answers a logged-in panel user and suggests only the screens the
user's role may open. Authorization is never trusted from the request body: the
tenant must match the authenticated igreja, and screen suggestions are computed
from the user's *real* accumulated roles (`role_permissions`), intersected with
any `papeis` the client narrows to.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.routers._common import ensure_tenant_context
from app.services.assistant import answer_panel_message

logger = logging.getLogger("pastorai.assistant")

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantMessageRequest(BaseModel):
    """Payload for POST /assistant/message (api-assistant contract)."""

    tenantId: str = Field(min_length=1)  # noqa: N815 - external contract
    usuarioId: str | None = Field(default=None)  # noqa: N815 - external contract
    papeis: list[str] | None = Field(default=None)
    texto: str = Field(min_length=1, max_length=2000)

    @field_validator("texto")
    @classmethod
    def _texto(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("texto obrigatório")
        return value

    @field_validator("papeis")
    @classmethod
    def _papeis(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [p.strip().lower() for p in value if p and p.strip()]


class AssistantMessageResponse(BaseModel):
    """Result: the phrased reply plus role-permitted screen suggestions."""

    resposta: str
    telasSugeridas: list[str]  # noqa: N815 - external contract


@router.post("/message", response_model=AssistantMessageResponse)
def assistant_message(
    payload: AssistantMessageRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AssistantMessageResponse:
    """Answer a panel message, suggesting only screens allowed to the role.

    - 403 when the body's tenantId does not match the authenticated igreja
      (no cross-tenant access, never trusting the client).
    - Roles used for screen suggestions are the user's real accumulated roles;
      when `papeis` is provided it can only *narrow* (intersection), never widen.
    """
    if payload.tenantId != current_user.igreja_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant não corresponde ao usuário autenticado",
        )

    ensure_tenant_context(db, current_user)

    effective_roles = list(current_user.roles)
    if payload.papeis:
        narrowed = [r for r in effective_roles if r in set(payload.papeis)]
        # Ignore an empty/incompatible narrowing to avoid losing real access.
        if narrowed:
            effective_roles = narrowed

    result = answer_panel_message(
        db,
        igreja_id=current_user.igreja_id,
        roles=effective_roles,
        texto=payload.texto,
    )

    logger.info(
        "Panel assistant replied (llm=%s, telas=%d)",
        result.llm_used,
        len(result.telas_sugeridas),
    )
    return AssistantMessageResponse(
        resposta=result.resposta,
        telasSugeridas=result.telas_sugeridas,
    )

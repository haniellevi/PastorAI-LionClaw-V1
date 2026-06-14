"""Agent router — BYO LLM credential management (US-27 / RNF-03).

Endpoint:
  - POST /agent/credential   {provedor, apiKey} -> {status}

The provided key is validated against the provider, encrypted at rest, and
never returned in clear text after being saved (RNF-03). An invalid key does
NOT activate the credential, so the agent will not operate with it. Config
screens are admin-only (delta-005), so the endpoint requires the `admin` role.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentConfig, Cron, LlmCredential
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.routers._common import ensure_tenant_context
from app.services.crypto import encrypt_secret
from app.services.llm import (
    SUPPORTED_PROVIDERS,
    LLMProviderError,
    UnsupportedProviderError,
    validate_credential,
)

logger = logging.getLogger("pastorai.agent")

router = APIRouter(prefix="/agent", tags=["agent"])


class SaveCredentialRequest(BaseModel):
    """Payload for saving a BYO LLM credential (action-save-llm-key)."""

    provedor: str = Field(min_length=1, max_length=40)
    apiKey: str = Field(min_length=1, max_length=400)  # noqa: N815 - external contract

    @field_validator("provedor")
    @classmethod
    def _provedor(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in SUPPORTED_PROVIDERS:
            raise ValueError(f"provedor não suportado: {value}")
        return value

    @field_validator("apiKey")
    @classmethod
    def _api_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("apiKey obrigatório")
        return value


class SaveCredentialResponse(BaseModel):
    """Result of saving a credential. `status` never echoes the key (RNF-03)."""

    status: str  # active | invalid
    provedor: str
    validado: bool


@router.post("/credential", response_model=SaveCredentialResponse)
def save_credential(
    payload: SaveCredentialRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> SaveCredentialResponse:
    """Validate, encrypt and persist the igreja's BYO LLM credential.

    - Valid key   -> stored encrypted, validado=true, ativo=true, status=active.
    - Invalid key -> stored encrypted but NOT activated (status=invalid); the
      agent will not operate until a valid key is provided.
    - Provider/network error -> 502 (the credential is not falsely deactivated).
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    try:
        is_valid = validate_credential(payload.provedor, payload.apiKey)
    except UnsupportedProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível validar a credencial com o provedor",
        ) from exc

    encrypted = encrypt_secret(payload.apiKey)

    cred = db.execute(
        select(LlmCredential)
        .where(LlmCredential.igreja_id == igreja_uuid)
        .with_for_update()
    ).scalar_one_or_none()

    if cred is None:
        cred = LlmCredential(igreja_id=igreja_uuid, provedor=payload.provedor)
        db.add(cred)

    cred.provedor = payload.provedor
    cred.api_key_encrypted = encrypted
    cred.validado = is_valid
    cred.ativo = is_valid  # an invalid key never activates the agent (US-27)
    db.commit()

    logger.info(
        "LLM credential saved for igreja (provedor=%s, validado=%s)",
        payload.provedor,
        is_valid,
    )
    return SaveCredentialResponse(
        status="active" if is_valid else "invalid",
        provedor=payload.provedor,
        validado=is_valid,
    )


# ---------------------------------------------------------------------------
# Agent config (PUT /agent/config) — US-28
# ---------------------------------------------------------------------------
class AgentConfigRequest(BaseModel):
    """Payload for saving the agent behaviour config (api-agent-config)."""

    comportamento: str = Field(min_length=1, max_length=4000)
    nome: str | None = Field(default=None, max_length=120)
    tom: str | None = Field(default=None, max_length=120)
    publicoAlvo: list[str] | None = Field(default=None)  # noqa: N815
    acessos: list[str] | None = Field(default=None)
    ativo: bool = Field(default=True)

    @field_validator("comportamento")
    @classmethod
    def _comportamento(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("comportamento obrigatório")
        return value


class AgentConfigResponse(BaseModel):
    nome: str | None = None
    tom: str | None = None
    comportamento: str
    publicoAlvo: list[str] | None = None  # noqa: N815
    acessos: list[str] | None = None
    ativo: bool


def _has_active_credential(db: Session, igreja_uuid: uuid.UUID) -> bool:
    """True only when a validated AND active BYO credential exists (US-27)."""
    cred = db.execute(
        select(LlmCredential).where(LlmCredential.igreja_id == igreja_uuid)
    ).scalar_one_or_none()
    return bool(cred and cred.validado and cred.ativo)


@router.put("/config", response_model=AgentConfigResponse)
def save_agent_config(
    payload: AgentConfigRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> AgentConfigResponse:
    """Save the agent behaviour/tone/audience/access config (1:1 per igreja).

    Activating the agent (`ativo=true`) requires a validated+active BYO LLM
    credential (US-27); otherwise the request is rejected (409) and the agent is
    not turned on.
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    if payload.ativo and not _has_active_credential(db, igreja_uuid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ative uma credencial de IA validada antes de ligar o agente",
        )

    cfg = db.execute(
        select(AgentConfig)
        .where(AgentConfig.igreja_id == igreja_uuid)
        .with_for_update()
    ).scalar_one_or_none()
    if cfg is None:
        cfg = AgentConfig(igreja_id=igreja_uuid, comportamento=payload.comportamento)
        db.add(cfg)

    cfg.comportamento = payload.comportamento
    cfg.nome = payload.nome
    cfg.tom = payload.tom
    cfg.publico_alvo = payload.publicoAlvo
    cfg.acessos = payload.acessos
    cfg.ativo = payload.ativo
    db.commit()

    return AgentConfigResponse(
        nome=cfg.nome,
        tom=cfg.tom,
        comportamento=cfg.comportamento,
        publicoAlvo=cfg.publico_alvo,
        acessos=cfg.acessos,
        ativo=cfg.ativo,
    )


# ---------------------------------------------------------------------------
# Agent crons (POST /agent/crons) — state-triggered automations
# ---------------------------------------------------------------------------
# Valid state triggers a cron may react to. Validated before saving so a cron
# never references an unknown gatilho de estado.
VALID_CRON_GATILHOS = {
    "relatorio_pendente",
    "conexao_pendente",
    "fonovisita_pendente",
    "visitante_novo",
    "decisao_registrada",
    "consolidacao_aberta",
    "multiplicacao_agendada",
}


class CreateCronRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    frequencia: str = Field(min_length=1, max_length=80)
    gatilhoEstado: str | None = Field(default=None)  # noqa: N815
    acao: str | None = Field(default=None, max_length=400)
    ativo: bool = Field(default=True)

    @field_validator("nome", "frequencia")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatório")
        return value

    @field_validator("gatilhoEstado")
    @classmethod
    def _gatilho(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            return None
        if value not in VALID_CRON_GATILHOS:
            raise ValueError(f"gatilho de estado inválido: {value}")
        return value


class CronResponse(BaseModel):
    id: str
    nome: str
    frequencia: str
    gatilhoEstado: str | None = None  # noqa: N815
    acao: str | None = None
    ativo: bool


@router.post("/crons", response_model=CronResponse, status_code=status.HTTP_201_CREATED)
def create_cron(
    payload: CreateCronRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> CronResponse:
    """Create a cron/state-triggered automation, validating the gatilho first.

    The state trigger (`gatilhoEstado`) is validated against the known set before
    persisting, so an invalid trigger never reaches the cron_worker.
    """
    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    cron = Cron(
        igreja_id=igreja_uuid,
        nome=payload.nome,
        frequencia=payload.frequencia,
        gatilho_estado=payload.gatilhoEstado,
        acao=payload.acao,
        ativo=payload.ativo,
    )
    db.add(cron)
    db.flush()
    db.refresh(cron)
    db.commit()

    return CronResponse(
        id=str(cron.id),
        nome=cron.nome,
        frequencia=cron.frequencia,
        gatilhoEstado=cron.gatilho_estado,
        acao=cron.acao,
        ativo=cron.ativo,
    )

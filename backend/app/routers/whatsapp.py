"""WhatsApp router — official-number connection and inbound webhook.

Endpoints:
  - GET  /whatsapp/connection   current numero / status / ultima_sync (admin)
  - POST /whatsapp/connection   connect|reconnect|disconnect -> {status, qr} (admin)
  - POST /whatsapp/webhook      Evolution inbound events (signature-gated)

A single official number per igreja is enforced by the UNIQUE igreja_id on
whatsapp_connections (RF-07). Config screens are admin-only (delta-005), so the
authenticated endpoints require the `admin` role. The webhook is public but
gated by a shared-secret token (query `?token=` / HMAC) instead of Clerk auth
(SPEC 3.3). Connecting an instance also registers this webhook on it, so a
number paired via the panel QR forwards messages without a manual step.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import WhatsappConnection
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.routers._common import ensure_tenant_context
from app.services.evolution import (
    EvolutionClient,
    EvolutionError,
    get_evolution_client,
    verify_shared_secret,
    verify_webhook_signature,
)
from app.workers.queue_worker import WebhookQueue

logger = logging.getLogger("pastorai.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConnectionStatusOut(BaseModel):
    numero: str | None = None
    status: str  # online | offline | reconectando
    ultimaSync: str | None = None  # noqa: N815 - external contract camelCase


class ConnectRequest(BaseModel):
    action: str  # connect | reconnect


class ConnectResponse(BaseModel):
    status: str
    qr: str | None = None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def get_webhook_queue() -> WebhookQueue:
    """FastAPI dependency providing the Redis-backed webhook queue."""
    return WebhookQueue()


def _instance_name(igreja_id: str) -> str:
    """Deterministic Evolution instance name for an igreja (1 per tenant)."""
    return f"igreja-{igreja_id}"


# ---------------------------------------------------------------------------
# Authenticated connection management (admin only)
# ---------------------------------------------------------------------------
@router.get("/connection", response_model=ConnectionStatusOut)
def get_connection(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> ConnectionStatusOut:
    """Return the igreja's official number, status and last sync.

    Refreshes the live state + paired number from Evolution when an instance
    exists. The number is unknown at QR time and only appears after the device
    pairs, so a pure DB read would never show it (the connect response carries
    no number). Best-effort: when Evolution is unreachable or unconfigured the
    stored values are returned. Values are captured into locals before any
    commit so no attribute reload runs outside the tenant context.
    """
    ensure_tenant_context(db, current_user)

    conn = db.execute(
        select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == uuid.UUID(current_user.igreja_id)
        )
    ).scalar_one_or_none()

    if conn is None:
        return ConnectionStatusOut(numero=None, status="offline", ultimaSync=None)

    numero = conn.numero
    status_val = conn.status or "offline"
    ultima = conn.ultima_sync

    if conn.instance:
        try:
            live = evolution.fetch_status(conn.instance)
        except EvolutionError:
            live = None
        if live is not None:
            changed = False
            if live.status and live.status != conn.status:
                conn.status = status_val = live.status
                changed = True
            if live.numero and live.numero != conn.numero:
                conn.numero = numero = live.numero
                changed = True
            if changed:
                ultima = conn.ultima_sync = dt.datetime.now(dt.timezone.utc)
                db.commit()

    return ConnectionStatusOut(
        numero=numero,
        status=status_val,
        ultimaSync=ultima.isoformat() if ultima else None,
    )


@router.post("/connection", response_model=ConnectResponse)
def post_connection(
    payload: ConnectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> ConnectResponse:
    """Connect or reconnect the official number, returning a QR + status.

    Keeps a single connection row per igreja (RF-07). The status is persisted so
    the UI reflects drops/reconnects without a reload.
    """
    if payload.action not in ("connect", "reconnect", "disconnect"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="action deve ser 'connect', 'reconnect' ou 'disconnect'",
        )

    ensure_tenant_context(db, current_user)
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    conn = db.execute(
        select(WhatsappConnection)
        .where(WhatsappConnection.igreja_id == igreja_uuid)
        .with_for_update()
    ).scalar_one_or_none()

    # Disconnect: log out the paired device but keep the row so a later connect
    # reuses the same instance (RF-07). No-op when the igreja never connected.
    if payload.action == "disconnect":
        if conn is None or not conn.instance:
            return ConnectResponse(status="offline", qr=None)
        try:
            result = evolution.disconnect(conn.instance)
        except EvolutionError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        conn.status = result.status
        conn.numero = None
        conn.ultima_sync = dt.datetime.now(dt.timezone.utc)
        db.commit()
        return ConnectResponse(status=result.status, qr=None)

    # Reuse the igreja's existing instance when present (it may have been
    # provisioned out-of-band, e.g. an already-connected number); only mint a
    # deterministic name when creating the connection for the first time.
    instance = (
        conn.instance
        if conn is not None and conn.instance
        else _instance_name(current_user.igreja_id)
    )

    if conn is None:
        conn = WhatsappConnection(igreja_id=igreja_uuid, instance=instance)
        db.add(conn)
        try:
            db.flush()
        except IntegrityError as exc:
            # Another request already created the (unique) connection (RF-07).
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um número conectado para esta igreja",
            ) from exc

    try:
        if payload.action == "connect":
            result = evolution.connect(instance)
        else:
            result = evolution.reconnect(instance)
    except EvolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    conn.status = result.status
    conn.instance = instance
    conn.ultima_sync = dt.datetime.now(dt.timezone.utc)
    if result.numero:
        conn.numero = result.numero
    db.commit()

    return ConnectResponse(status=result.status, qr=result.qr)


# ---------------------------------------------------------------------------
# Inbound webhook (signature-gated, no Clerk auth)
# ---------------------------------------------------------------------------
@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def webhook(
    request: Request,
    x_evolution_signature: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
    queue: WebhookQueue = Depends(get_webhook_queue),
) -> dict[str, str]:
    """Authenticate and enqueue the event for the worker.

    Evolution API v2 self-hosted neither HMAC-signs its webhooks nor supports
    custom headers (header support exists only on the Cloud edition), so the
    primary authentication is a static shared-secret carried in the webhook URL
    query string (`?token=...`) — Evolution preserves query params on the
    configured global/instance webhook URL. The request is accepted when ANY of
    the following matches, all compared in constant time:
      - a valid HMAC signature (GitHub-style, future-proofing / Cloud edition);
      - a matching `x-webhook-token` header (Cloud edition / reverse proxy);
      - a matching `?token=` query param (Evolution v2 self-hosted — the path
        actually used by this deploy).
    An unauthenticated request is rejected with 401 before any parsing. Accepted
    events are queued and processed asynchronously (RNF-17).
    """
    raw = await request.body()
    secret = get_settings().evolution_webhook_secret
    signature = x_evolution_signature or x_hub_signature_256

    if not (
        verify_webhook_signature(secret, raw, signature)
        or verify_shared_secret(secret, x_webhook_token)
        or verify_shared_secret(secret, token)
    ):
        logger.warning("Rejected webhook with invalid signature/token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Assinatura do webhook inválida",
        )

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload do webhook inválido",
        ) from exc

    try:
        queue.enqueue(payload)
    except Exception as exc:  # noqa: BLE001 - surface as retryable to provider
        logger.exception("Failed to enqueue webhook payload")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fila indisponível, tente novamente",
        ) from exc

    return {"status": "queued"}

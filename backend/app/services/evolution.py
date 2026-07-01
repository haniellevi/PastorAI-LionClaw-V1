"""Evolution API client for WhatsApp connection management (US-05..US-08).

Responsibilities:

1. Bring an instance online and return its QR code + connection state
   (`connect` / `reconnect`), keeping a single official number per igreja.
2. Register the inbound webhook on the instance at connect time (`set_webhook`)
   so a freshly-paired number actually forwards messages to the backend.
3. Read the live connection state (`fetch_status`).
4. Verify inbound webhook signatures (HMAC-SHA256) so spoofed payloads are
   rejected before any processing (webhook signature requirement).

The client never raises raw HTTP errors to callers: failures are normalized to
`EvolutionError` and logged without leaking the API key.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings
from app.services.outbound_guard import external_sends_allowed, log_suppressed

logger = logging.getLogger("pastorai.evolution")

# Map Evolution connection states to our whatsapp_status enum.
_STATE_MAP = {
    "open": "online",
    "connected": "online",
    "connecting": "reconectando",
    "close": "offline",
    "closed": "offline",
    "disconnected": "offline",
}


def map_connection_state(raw_state: str | None) -> str:
    """Translate an Evolution connection state into a whatsapp_status value."""
    if not raw_state:
        return "offline"
    return _STATE_MAP.get(raw_state.lower(), "offline")


def numero_from_jid(jid: str | None) -> str | None:
    """Extract a bare phone number from a WhatsApp owner JID.

    Evolution reports the paired device as a JID such as
    ``5511999999999@s.whatsapp.net`` or ``5511999999999:12@s.whatsapp.net``
    (the ``:n`` is a device index). The paired number is unknown at QR time and
    only appears once the device pairs, so this is how we recover it. Returns
    the digits before the ``@`` (and before any ``:device`` suffix), or None
    when the JID is absent/malformed.
    """
    if not jid or not isinstance(jid, str):
        return None
    local = jid.split("@", 1)[0].split(":", 1)[0]
    digits = "".join(ch for ch in local if ch.isdigit())
    return digits or None


class EvolutionError(Exception):
    """Raised when the Evolution API call fails or is misconfigured."""


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of a connect/reconnect/status call."""

    status: str  # online | offline | reconectando
    qr: str | None = None
    numero: str | None = None
    pairing_code: str | None = None  # numeric pairing code (connect with number)


def verify_webhook_signature(secret: str, payload: bytes, signature: str | None) -> bool:
    """Validate an inbound webhook HMAC-SHA256 signature in constant time.

    The signature header may be sent as a bare hex digest or prefixed with
    `sha256=` (GitHub-style). An empty secret or signature is rejected.
    """
    if not secret or not signature:
        return False
    provided = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.strip())


def verify_shared_secret(secret: str, token: str | None) -> bool:
    """Constant-time check of a static shared-secret webhook token.

    Evolution API v2 self-hosted neither HMAC-signs its webhooks nor supports
    custom headers, so the secret is carried in the webhook URL as a `?token=`
    query param (and accepted as an `x-webhook-token` header on Cloud/proxied
    setups). This authenticates inbound webhooks in constant time. An empty
    secret or token is rejected.
    """
    if not secret or not token:
        return False
    return hmac.compare_digest(secret, token.strip())


class EvolutionClient:
    """Thin HTTP client around the Evolution API instance endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require_config(self) -> tuple[str, str]:
        base_url = self._settings.evolution_api_url
        api_key = self._settings.evolution_api_key
        if not base_url or not api_key:
            raise EvolutionError("Evolution API is not configured")
        return base_url.rstrip("/"), api_key

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"apikey": api_key, "Content-Type": "application/json"}

    def connect(self, instance: str, numero: str | None = None) -> ConnectionResult:
        """Connect (or resume) an instance and return its QR + state.

        Idempotent: connecting an already-online instance returns its state
        without a QR. The instance is created on demand when missing. When
        ``numero`` (a full phone number, digits only) is given, Evolution issues a
        numeric **pairing code** for that number instead of a QR-only session —
        the fallback when QR scanning fails.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("WhatsApp", "connect")
            return ConnectionResult(status="offline")
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        params = {"number": numero} if numero else None
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                self._ensure_instance(client, headers, instance)
                resp = client.get(
                    f"/instance/connect/{instance}", headers=headers, params=params
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Evolution connect failed: %s", type(exc).__name__)
            raise EvolutionError("Falha ao conectar à Evolution API") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Evolution connect response shape")
            raise EvolutionError("Resposta inesperada da Evolution API") from exc

        result = self._result_from_connect(body)
        # Register the inbound webhook so the instance forwards messages. Best
        # effort: a webhook failure must not hide the QR from the admin.
        try:
            self.set_webhook(instance)
        except EvolutionError:
            logger.warning(
                "Instance %s connected but webhook registration failed", instance
            )
        return result

    def reconnect(self, instance: str, numero: str | None = None) -> ConnectionResult:
        """Restart an instance and return a fresh QR/pairing code + state.

        Evolution v2.3.7 answers ``PUT /instance/restart`` with 404 when the
        instance has no live socket yet, so the restart is best-effort: its
        failure is logged but never aborts the reconnect. The instance is
        (re)created if missing and ``/instance/connect`` still yields a fresh QR
        (a plain restart alone would 404 on a never-connected instance). When
        ``numero`` is given a numeric pairing code is requested instead of a QR.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("WhatsApp", "reconnect")
            return ConnectionResult(status="offline")
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        params = {"number": numero} if numero else None
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                # Ensure the instance exists so a never-connected igreja can pair.
                self._ensure_instance(client, headers, instance)
                # Restart drops the current socket so connect yields a fresh QR.
                # A 404/failure here is expected on v2.3.7 and must not hide the
                # QR from the admin — log it and fall through to connect.
                try:
                    restart = client.put(
                        f"/instance/restart/{instance}", headers=headers
                    )
                    if restart.status_code >= 400:
                        logger.info(
                            "Evolution restart returned %s for %s; connecting anyway",
                            restart.status_code,
                            instance,
                        )
                except httpx.HTTPError:
                    logger.info(
                        "Evolution restart unavailable for %s; connecting anyway",
                        instance,
                    )
                resp = client.get(
                    f"/instance/connect/{instance}", headers=headers, params=params
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Evolution reconnect failed: %s", type(exc).__name__)
            raise EvolutionError("Falha ao reconectar à Evolution API") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Evolution reconnect response shape")
            raise EvolutionError("Resposta inesperada da Evolution API") from exc

        result = self._result_from_connect(body)
        # Re-register the webhook on reconnect too (idempotent), so a recovered
        # instance keeps forwarding messages.
        try:
            self.set_webhook(instance)
        except EvolutionError:
            logger.warning(
                "Instance %s reconnected but webhook registration failed", instance
            )
        # A reconnect in progress is surfaced as 'reconectando' when neither a QR
        # nor a pairing code came back yet.
        if (
            result.qr is None
            and result.pairing_code is None
            and result.status == "offline"
        ):
            return ConnectionResult(status="reconectando")
        return result

    def disconnect(self, instance: str) -> ConnectionResult:
        """Log out (unpair) an instance's WhatsApp session (US-06).

        Drops the paired device so a different number can be paired, but keeps
        the instance so a later connect reuses it (RF-07). A missing/already
        logged-out instance is treated as success (idempotent). Returns offline.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("WhatsApp", "disconnect")
            return ConnectionResult(status="offline")
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.delete(
                    f"/instance/logout/{instance}", headers=headers
                )
                # 200 ok, or 404/409 (already logged out / missing) are fine.
                if resp.status_code not in (200, 201, 404, 409):
                    resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Evolution logout failed: %s", type(exc).__name__)
            raise EvolutionError(
                "Falha ao desconectar na Evolution API"
            ) from exc
        return ConnectionResult(status="offline")

    def send_text(self, instance: str, telefone: str, texto: str) -> bool:
        """Send a text message through the official number (agent single reply).

        Returns True on success. Failures are normalized to EvolutionError so the
        caller can retry; the API key is never logged.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("WhatsApp", "send_text")
            return True
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post(
                    f"/message/sendText/{instance}",
                    headers=headers,
                    json={"number": telefone, "text": texto},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Evolution sendText failed: %s", type(exc).__name__)
            raise EvolutionError("Falha ao enviar mensagem pela Evolution API") from exc
        return True

    def get_media_base64(
        self, instance: str, key: dict[str, object]
    ) -> tuple[str, str | None]:
        """Download a received media message's bytes (base64) + mimetype.

        Evolution does not push media bytes in the webhook by default, so the
        worker pulls them on demand via the message `key`. Returns
        ``(base64, mimetype)``; raises EvolutionError when the media has no
        content. The key only needs id/remoteJid/fromMe to locate the message.
        """
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=30.0) as client:
                resp = client.post(
                    f"/chat/getBase64FromMediaMessage/{instance}",
                    headers=headers,
                    json={"message": {"key": key}, "convertToMp4": False},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Evolution getBase64 failed: %s", type(exc).__name__)
            raise EvolutionError("Falha ao baixar a mídia da Evolution API") from exc
        except ValueError as exc:
            raise EvolutionError("Resposta inesperada da Evolution API") from exc

        data = body.get("base64") if isinstance(body, dict) else None
        mimetype = body.get("mimetype") if isinstance(body, dict) else None
        if not isinstance(data, str) or not data:
            raise EvolutionError("Mídia sem conteúdo na resposta da Evolution API")
        return data, (mimetype if isinstance(mimetype, str) and mimetype else None)

    def send_media(
        self,
        instance: str,
        telefone: str,
        *,
        mediatype: str,
        media_base64: str,
        mime: str | None = None,
        filename: str | None = None,
        caption: str | None = None,
    ) -> bool:
        """Send an image/document/audio through the official number (Etapa 2).

        `mediatype` is Evolution's `image|document|audio`; `media_base64` is the
        raw base64 (no `data:` prefix). Returns True on success; failures are
        normalized to EvolutionError so the caller can surface a 502.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("WhatsApp", "send_media")
            return True
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        body: dict[str, object] = {
            "number": telefone,
            "mediatype": mediatype,
            "media": media_base64,
        }
        if mime:
            body["mimetype"] = mime
        if filename:
            body["fileName"] = filename
        if caption:
            body["caption"] = caption
        try:
            with httpx.Client(base_url=base_url, timeout=30.0) as client:
                resp = client.post(
                    f"/message/sendMedia/{instance}", headers=headers, json=body
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Evolution sendMedia failed: %s", type(exc).__name__)
            raise EvolutionError("Falha ao enviar a mídia pela Evolution API") from exc
        return True

    def set_webhook(self, instance: str) -> bool:
        """Register the inbound webhook on an instance (US-08).

        Without this an instance is "deaf": Evolution receives WhatsApp messages
        but forwards them nowhere. Called right after connecting so a number
        paired through the panel QR starts delivering events immediately.

        The callback URL comes from settings; the shared secret is appended as a
        `?token=` query param because Evolution v2 self-hosted supports neither
        HMAC signing nor custom webhook headers. No-ops (logs a warning) when no
        callback URL is configured. Tries the nested v2.1+ body first, falling
        back to the flat body for older shapes. Returns True when registered.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("WhatsApp", "set_webhook")
            return True
        callback = (self._settings.evolution_webhook_callback_url or "").strip()
        if not callback:
            logger.warning(
                "evolution_webhook_callback_url not set; instance %s will not "
                "receive inbound messages until a webhook is configured",
                instance,
            )
            return False

        secret = self._settings.evolution_webhook_secret
        url = callback
        if secret:
            sep = "&" if "?" in callback else "?"
            url = f"{callback}{sep}token={secret}"

        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        events = ["MESSAGES_UPSERT"]
        body = {
            "enabled": True,
            "url": url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": events,
        }
        # v2.1+ wraps the config under a `webhook` key; older shapes are flat.
        nested = {"webhook": body}
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post(
                    f"/webhook/set/{instance}", headers=headers, json=nested
                )
                if resp.status_code >= 400:
                    resp = client.post(
                        f"/webhook/set/{instance}", headers=headers, json=body
                    )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Evolution set_webhook failed: %s", type(exc).__name__)
            raise EvolutionError(
                "Falha ao registrar webhook na Evolution API"
            ) from exc
        return True

    def fetch_status(self, instance: str) -> ConnectionResult:
        """Read the live connection state **and paired number** of an instance.

        Uses ``/instance/fetchInstances`` (filtered by name) instead of
        ``/instance/connectionState`` because only the former carries the owner
        JID — the paired phone number is unknown at QR time and only becomes
        available after the device pairs, so the connect/reconnect responses
        never include it. The response shape differs across Evolution versions,
        so both the flat v2 shape (``name`` / ``connectionStatus`` /
        ``ownerJid``) and the nested v1 shape (``instance.instanceName`` /
        ``instance.status`` / ``instance.owner``) are handled.
        """
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=10.0) as client:
                resp = client.get(
                    "/instance/fetchInstances",
                    headers=headers,
                    params={"instanceName": instance},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Evolution status failed: %s", type(exc).__name__)
            raise EvolutionError("Falha ao consultar status na Evolution API") from exc
        except ValueError as exc:
            raise EvolutionError("Resposta inesperada da Evolution API") from exc

        entry = self._select_instance(body, instance)
        state, owner = self._state_and_owner(entry)
        return ConnectionResult(
            status=map_connection_state(state), numero=numero_from_jid(owner)
        )

    @staticmethod
    def _select_instance(body: object, instance: str) -> dict:
        """Pick the entry matching `instance` from a fetchInstances response.

        Evolution returns a list (one item per instance); filtering by name may
        still return several on some versions. Falls back to the first dict
        entry when no name matches (single-instance servers).
        """
        items = body if isinstance(body, list) else [body]
        for item in items:
            if not isinstance(item, dict):
                continue
            inner = item.get("instance") if isinstance(item.get("instance"), dict) else item
            name = inner.get("instanceName") or inner.get("name") or item.get("name")
            if name == instance:
                return item
        for item in items:
            if isinstance(item, dict):
                return item
        return {}

    @staticmethod
    def _state_and_owner(entry: dict) -> tuple[str | None, str | None]:
        """Extract ``(state, owner_jid)`` from a fetchInstances entry (any version)."""
        inner = entry.get("instance") if isinstance(entry.get("instance"), dict) else entry
        state = (
            inner.get("connectionStatus")
            or inner.get("state")
            or inner.get("status")
            or entry.get("connectionStatus")
        )
        owner = (
            inner.get("ownerJid")
            or inner.get("owner")
            or inner.get("wuid")
            or entry.get("ownerJid")
            or entry.get("owner")
        )
        return state, owner

    def fetch_profile_picture_url(
        self, instance: str, telefone: str
    ) -> str | None:
        """Fetch a contact's WhatsApp profile photo URL (Etapa 4 do chat).

        Best-effort: returns the URL (a public WhatsApp CDN link) or **None** when
        the contact has no photo, hides it by privacy, or anything fails. Never
        raises — a missing avatar must never break the inbox; the UI falls back to
        the contact's initials.
        """
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=10.0) as client:
                resp = client.post(
                    f"/chat/fetchProfilePictureUrl/{instance}",
                    headers=headers,
                    json={"number": telefone},
                )
                if resp.status_code >= 400:
                    return None
                body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Evolution fetchProfilePictureUrl failed: %s", type(exc).__name__
            )
            return None

        if not isinstance(body, dict):
            return None
        url = body.get("profilePictureUrl") or body.get("url")
        return url if isinstance(url, str) and url else None

    # ---- helpers ------------------------------------------------------------
    def _ensure_instance(
        self, client: httpx.Client, headers: dict[str, str], instance: str
    ) -> None:
        """Create the instance if it does not exist yet (best-effort)."""
        resp = client.post(
            "/instance/create",
            headers=headers,
            json={"instanceName": instance, "integration": "WHATSAPP-BAILEYS"},
        )
        # 201 created or 403/409 already-exists are both acceptable.
        if resp.status_code not in (200, 201, 403, 409):
            resp.raise_for_status()

    @staticmethod
    def _result_from_connect(body: dict) -> ConnectionResult:
        """Normalize a /instance/connect response to a ConnectionResult.

        Evolution returns the QR as a base64 PNG under ``base64`` (newer shapes)
        or nested under ``qrcode`` (older ones). The sibling ``code`` field is the
        QR's *text* payload, not an image, so it is never surfaced as the QR
        (rendering it as a base64 image is what produced broken/blank QRs). When
        the connect carried a phone number, a numeric ``pairingCode`` is returned
        too — top-level on v2 or nested under ``qrcode``.
        """
        qrcode = body.get("qrcode") if isinstance(body.get("qrcode"), dict) else {}
        qr = body.get("base64") or qrcode.get("base64")
        if isinstance(qr, dict):  # defensive: some builds double-nest base64
            qr = qr.get("base64")
        pairing = body.get("pairingCode") or qrcode.get("pairingCode")

        state = (body.get("instance") or {}).get("state") or body.get("state")
        status = map_connection_state(state)
        # A QR or pairing code means the device is pairing -> reconectando.
        if (qr or pairing) and status == "offline":
            status = "reconectando"
        return ConnectionResult(
            status=status,
            qr=qr if isinstance(qr, str) else None,
            pairing_code=pairing if isinstance(pairing, str) and pairing else None,
        )


def get_evolution_client() -> EvolutionClient:
    """FastAPI dependency / factory for the Evolution client."""
    return EvolutionClient()

"""Supabase Storage client for WhatsApp media (Etapa 2 do chat).

Media binaries are kept out of Postgres (DB quota + LGPD): they live in a
private Supabase Storage bucket (`whatsapp-media`). The backend uploads with the
service-role key and serves reads through short-lived **signed URLs**, so a
church's media is never publicly reachable and stays tenant-scoped by path
(`{igreja_id}/{conversation_id}/...`). The service-role key bypasses Storage
RLS, so tenant isolation is enforced here: every path is built from the
authenticated `igreja_id` and the backend only ever signs paths it stored.

Transport to/from the Evolution API is base64; this module deals in raw bytes.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.storage")

# Private bucket holding all WhatsApp media. Created once (see migration notes /
# deploy docs); never public.
MEDIA_BUCKET = "whatsapp-media"

# TTL (seconds) of the signed read URLs handed to the panel. The inbox refetches
# messages periodically, so an open panel keeps getting fresh URLs.
SIGNED_URL_TTL = 60 * 60  # 1 hour

# Defense-in-depth size cap (the UI also limits). WhatsApp's own image ceiling
# is ~16 MB; documents can be larger but we cap to keep base64 bodies sane.
MAX_MEDIA_BYTES = 16 * 1024 * 1024

# MIME -> file extension for the stored object name (best-effort; falls back to
# the original filename's extension, then to "bin").
_EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "txt",
    "application/zip": "zip",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/wav": "wav",
}


class StorageError(Exception):
    """Raised when a Supabase Storage call fails or is misconfigured."""


class StoredMedia:
    """A media object that now lives in the bucket."""

    __slots__ = ("path", "mime", "nome", "tamanho")

    def __init__(
        self, path: str, mime: str, nome: str | None, tamanho: int
    ) -> None:
        self.path = path
        self.mime = mime
        self.nome = nome
        self.tamanho = tamanho


def kind_for_mime(mime: str | None) -> str:
    """Map a MIME type to a message `tipo` (imagem|audio|arquivo)."""
    m = (mime or "").lower()
    if m.startswith("image/"):
        return "imagem"
    if m.startswith("audio/"):
        return "audio"
    return "arquivo"


def mediatype_for_tipo(tipo: str) -> str:
    """Map a message `tipo` to an Evolution sendMedia `mediatype`."""
    if tipo == "imagem":
        return "image"
    if tipo == "audio":
        return "audio"
    return "document"


def _ext_for(mime: str | None, nome: str | None) -> str:
    """Pick a file extension from MIME, falling back to the filename."""
    ext = _EXT_BY_MIME.get((mime or "").lower())
    if ext:
        return ext
    if nome and "." in nome:
        candidate = nome.rsplit(".", 1)[-1].strip().lower()
        if candidate and candidate.isalnum() and len(candidate) <= 8:
            return candidate
    return "bin"


class SupabaseStorage:
    """Thin HTTP client around the Supabase Storage REST API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require(self) -> tuple[str, str]:
        url = (self._settings.supabase_url or "").rstrip("/")
        key = self._settings.supabase_service_role_key
        if not url or not key:
            raise StorageError("Supabase Storage não está configurado")
        return url, key

    def upload(
        self,
        igreja_id: object,
        conversation_id: object,
        data: bytes,
        mime: str | None,
        nome: str | None = None,
    ) -> StoredMedia:
        """Upload bytes to the bucket and return the stored-object pointer.

        Path is tenant-scoped: ``{igreja_id}/{conversation_id}/{uuid}.{ext}``.
        Raises StorageError on oversize or transport failure.
        """
        if not data:
            raise StorageError("Mídia vazia")
        if len(data) > MAX_MEDIA_BYTES:
            raise StorageError("Arquivo excede o limite de 16 MB")

        url, key = self._require()
        content_type = mime or "application/octet-stream"
        path = f"{igreja_id}/{conversation_id}/{uuid.uuid4().hex}.{_ext_for(mime, nome)}"
        endpoint = f"{url}/storage/v1/object/{MEDIA_BUCKET}/{path}"
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": content_type,
                        "x-upsert": "true",
                    },
                    content=data,
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Supabase Storage upload failed: %s", type(exc).__name__)
            raise StorageError("Falha ao enviar a mídia ao armazenamento") from exc

        return StoredMedia(
            path=path, mime=content_type, nome=nome, tamanho=len(data)
        )

    def sign(self, paths: list[str]) -> dict[str, str]:
        """Batch-sign read URLs. Returns ``{path: absolute_url}``.

        Best-effort: a transport failure yields an empty map (the panel then
        renders a "mídia indisponível" placeholder instead of breaking).
        Deduplicates and ignores empty paths.
        """
        clean = [p for p in dict.fromkeys(paths) if p]
        if not clean:
            return {}
        try:
            url, key = self._require()
        except StorageError:
            return {}
        endpoint = f"{url}/storage/v1/object/sign/{MEDIA_BUCKET}"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={"expiresIn": SIGNED_URL_TTL, "paths": clean},
                )
                resp.raise_for_status()
                body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Supabase Storage sign failed: %s", type(exc).__name__)
            return {}

        out: dict[str, str] = {}
        for item in body if isinstance(body, list) else []:
            if not isinstance(item, dict):
                continue
            p = item.get("path")
            signed = item.get("signedURL") or item.get("signedUrl")
            if not isinstance(p, str) or not isinstance(signed, str) or not signed:
                continue
            out[p] = f"{url}/storage/v1{signed}" if signed.startswith("/") else signed
        return out


def get_storage() -> SupabaseStorage:
    """FastAPI dependency / factory for the storage client."""
    return SupabaseStorage()

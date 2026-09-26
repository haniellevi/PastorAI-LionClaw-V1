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
import re
import uuid
from collections.abc import Callable, Iterable
from hashlib import sha256

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

# Missão 4 (branding): bucket PÚBLICO das logos das igrejas — URL estável, sem
# TTL (o shell exibe a logo em todo pageload). Criado manualmente em DEV/PROD
# (runbook na spec docs/design/BRANDING-IDENTIDADE-VISUAL-IGREJA.md §6).
LOGO_BUCKET = "church-logos"

# Teto próprio da logo (D5): uma logo tem poucos KB; 1 MB já é generoso.
MAX_LOGO_BYTES = 1 * 1024 * 1024

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
_STORAGE_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_TENANT_LIST_PAGE_SIZE = 100
_TENANT_REMOVE_BATCH_SIZE = 100


class StorageError(Exception):
    """Raised when a Supabase Storage call fails or is misconfigured."""


class StoragePathError(StorageError):
    """A cleanup target is outside the tenant-owned storage namespace."""


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


def _tenant_prefix(igreja_id: object) -> str:
    try:
        return f"{uuid.UUID(str(igreja_id))}/"
    except (TypeError, ValueError, AttributeError) as exc:
        raise StoragePathError("Identificador de igreja inválido") from exc


def tenant_owned_paths(igreja_id: object, paths: Iterable[object]) -> list[str]:
    """Validate object keys before a privileged tenant cleanup.

    The storage service-role key bypasses RLS. Cleanup therefore accepts only
    canonical paths inside the tenant UUID prefix and rejects malformed paths
    instead of broadening a delete request.
    """
    prefix = _tenant_prefix(igreja_id)

    clean: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path.startswith(prefix):
            raise StoragePathError("Caminho fora do namespace da igreja")
        suffix = path.removeprefix(prefix)
        components = suffix.split("/")
        if (
            not suffix
            or any(part in {"", ".", ".."} for part in components)
            or any(not _STORAGE_PATH_COMPONENT_RE.fullmatch(part) for part in components)
        ):
            raise StoragePathError("Caminho de armazenamento inválido")
        if path not in clean:
            clean.append(path)
    return clean


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
        object_id: str | None = None,
    ) -> StoredMedia:
        """Upload bytes to the bucket and return the stored-object pointer.

        Path is tenant-scoped. When ``object_id`` is provided, the object name
        is deterministic, so a recovered queue claim safely upserts the same
        object instead of leaving duplicate/orphaned media. Ad-hoc uploads keep
        the legacy random UUID name. Raises StorageError on oversize or
        transport failure.
        """
        if not data:
            raise StorageError("Mídia vazia")
        if len(data) > MAX_MEDIA_BYTES:
            raise StorageError("Arquivo excede o limite de 16 MB")

        url, key = self._require()
        content_type = mime or "application/octet-stream"
        extension = _ext_for(mime, nome)
        if object_id:
            # Do not include the conversation id: two fenced workers handling
            # the first message may have provisional conversation UUIDs. The
            # stable provider key makes both attempts upsert the exact object.
            object_name = sha256(object_id.encode("utf-8")).hexdigest()
            path = f"{igreja_id}/provider/{object_name}.{extension}"
        else:
            path = (
                f"{igreja_id}/{conversation_id}/"
                f"{uuid.uuid4().hex}.{extension}"
            )
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

    def remove(self, paths: list[str]) -> None:
        """Best-effort delete of stored objects (used when a conversa is excluded).

        Silent on failure: a user-facing conversation delete must not break just
        because the media couldn't be cleaned up (the orphan is a minor cost; the
        DB row — the source of truth — is already gone). Dedupes and ignores
        empty paths; a no-op when there's nothing to remove.
        """
        clean = [p for p in dict.fromkeys(paths) if p]
        if not clean:
            return
        try:
            url, key = self._require()
        except StorageError:
            return
        endpoint = f"{url}/storage/v1/object/{MEDIA_BUCKET}"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.request(
                    "DELETE",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={"prefixes": clean},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Supabase Storage remove failed: %s", type(exc).__name__)

    def _remove_tenant_owned(
        self,
        bucket: str,
        igreja_id: object,
        paths: Iterable[object],
        *,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        """Delete known tenant-owned objects and make a missing object idempotent."""
        clean = tenant_owned_paths(igreja_id, paths)
        if not clean:
            return
        url, key = self._require()
        endpoint = f"{url}/storage/v1/object/{bucket}"
        try:
            if before_request is not None:
                before_request()
            with httpx.Client(timeout=15.0) as client:
                resp = client.request(
                    "DELETE",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={"prefixes": clean},
                )
                if resp.status_code != 404:
                    resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Supabase Storage tenant cleanup failed: %s", type(exc).__name__)
            raise StorageError("Falha ao remover objetos da igreja") from exc

    def remove_tenant_media(self, igreja_id: object, paths: Iterable[object]) -> None:
        """Strict cleanup of WhatsApp media owned by one tenant."""
        self._remove_tenant_owned(MEDIA_BUCKET, igreja_id, paths)

    def _list_tenant_namespace(
        self,
        bucket: str,
        igreja_id: object,
        *,
        before_request: Callable[[], None] | None = None,
    ) -> list[str]:
        """Return every object below one exact tenant UUID prefix."""
        root_prefix = _tenant_prefix(igreja_id)
        url, key = self._require()
        endpoint = f"{url}/storage/v1/object/list/{bucket}"
        pending_prefixes = [root_prefix]
        visited_prefixes: set[str] = set()
        paths: list[str] = []

        try:
            with httpx.Client(timeout=15.0) as client:
                while pending_prefixes:
                    prefix = pending_prefixes.pop()
                    if prefix in visited_prefixes:
                        continue
                    visited_prefixes.add(prefix)
                    offset = 0
                    while True:
                        if before_request is not None:
                            before_request()
                        response = client.post(
                            endpoint,
                            headers={
                                "Authorization": f"Bearer {key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "prefix": prefix,
                                "limit": _TENANT_LIST_PAGE_SIZE,
                                "offset": offset,
                                "sortBy": {"column": "name", "order": "asc"},
                            },
                        )
                        response.raise_for_status()
                        entries = response.json()
                        if not isinstance(entries, list):
                            raise StorageError("Listagem de armazenamento inválida")
                        for entry in entries:
                            if not isinstance(entry, dict):
                                raise StorageError("Listagem de armazenamento inválida")
                            name = entry.get("name")
                            if not isinstance(name, str) or not name or "id" not in entry:
                                raise StorageError("Listagem de armazenamento inválida")
                            entry_id = entry["id"]
                            if entry_id is None:
                                if entry.get("metadata") is not None:
                                    raise StorageError("Listagem de armazenamento inválida")
                                is_directory = True
                            elif isinstance(entry_id, str) and entry_id:
                                is_directory = False
                            else:
                                raise StorageError("Listagem de armazenamento inválida")
                            if name.startswith(prefix):
                                relative_name = name.removeprefix(prefix)
                            else:
                                first_component, separator, _ = name.partition("/")
                                if separator:
                                    try:
                                        uuid.UUID(first_component)
                                    except ValueError:
                                        pass
                                    else:
                                        raise StoragePathError(
                                            "Listagem fora do namespace da igreja"
                                        )
                                relative_name = name
                            if is_directory and relative_name.endswith("/"):
                                relative_name = relative_name[:-1]
                            if not relative_name or relative_name.endswith("/"):
                                raise StorageError("Listagem de armazenamento inválida")
                            candidate = f"{prefix}{relative_name}"
                            clean_path = tenant_owned_paths(igreja_id, [candidate])[0]
                            if is_directory:
                                pending_prefixes.append(f"{clean_path}/")
                            elif clean_path not in paths:
                                paths.append(clean_path)
                        if len(entries) < _TENANT_LIST_PAGE_SIZE:
                            break
                        offset += len(entries)
        except httpx.HTTPError as exc:
            logger.warning("Supabase Storage tenant list failed: %s", type(exc).__name__)
            raise StorageError("Falha ao listar objetos da igreja") from exc
        return paths

    def _remove_tenant_namespace(
        self,
        bucket: str,
        igreja_id: object,
        *,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        paths = self._list_tenant_namespace(
            bucket,
            igreja_id,
            before_request=before_request,
        )
        for index in range(0, len(paths), _TENANT_REMOVE_BATCH_SIZE):
            self._remove_tenant_owned(
                bucket,
                igreja_id,
                paths[index : index + _TENANT_REMOVE_BATCH_SIZE],
                before_request=before_request,
            )

    def remove_tenant_media_namespace(
        self,
        igreja_id: object,
        *,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        """Strictly delete every media object below one tenant UUID prefix."""
        self._remove_tenant_namespace(
            MEDIA_BUCKET,
            igreja_id,
            before_request=before_request,
        )


    # ---- Logo da igreja (Missão 4) — bucket público church-logos ------------
    def upload_logo(self, path: str, data: bytes, content_type: str) -> None:
        """Upload da logo para o bucket público, no path tenant-scoped dado.

        O chamador (router) valida conteúdo/tamanho e deriva o path do
        igreja_id AUTENTICADO — a service-role key bypassa a RLS do Storage,
        então o isolamento entre igrejas é exatamente esta disciplina.
        """
        if not data:
            raise StorageError("Logo vazia")
        if len(data) > MAX_LOGO_BYTES:
            raise StorageError("A logo excede o limite de 1 MB")

        url, key = self._require()
        endpoint = f"{url}/storage/v1/object/{LOGO_BUCKET}/{path}"
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
            logger.warning("Supabase Storage logo upload failed: %s", type(exc).__name__)
            raise StorageError("Falha ao enviar a logo ao armazenamento") from exc

    def remove_logo(self, paths: list[str]) -> None:
        """Best-effort delete de logos antigas no bucket público.

        Silencioso em falha (mesma filosofia de ``remove``): o ponteiro no DB é
        a fonte de verdade; um objeto órfão no bucket é custo menor do que
        quebrar a troca/remoção da logo.
        """
        clean = [p for p in dict.fromkeys(paths) if p]
        if not clean:
            return
        try:
            url, key = self._require()
        except StorageError:
            return
        endpoint = f"{url}/storage/v1/object/{LOGO_BUCKET}"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.request(
                    "DELETE",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={"prefixes": clean},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Supabase Storage logo remove failed: %s", type(exc).__name__)

    def remove_tenant_logos(self, igreja_id: object, paths: Iterable[object]) -> None:
        """Strict cleanup of public logo objects owned by one tenant."""
        self._remove_tenant_owned(LOGO_BUCKET, igreja_id, paths)

    def remove_tenant_logos_namespace(
        self,
        igreja_id: object,
        *,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        """Strictly delete every logo object below one tenant UUID prefix."""
        self._remove_tenant_namespace(
            LOGO_BUCKET,
            igreja_id,
            before_request=before_request,
        )


def logo_public_url(path: str | None) -> str | None:
    """URL pública e estável da logo (bucket público — sem assinatura/TTL).

    None quando não há logo ou o Storage não está configurado (o frontend cai
    no fallback pelo nome da igreja).
    """
    if not path:
        return None
    url = (get_settings().supabase_url or "").rstrip("/")
    if not url:
        return None
    return f"{url}/storage/v1/object/public/{LOGO_BUCKET}/{path}"


def get_storage() -> SupabaseStorage:
    """FastAPI dependency / factory for the storage client."""
    return SupabaseStorage()

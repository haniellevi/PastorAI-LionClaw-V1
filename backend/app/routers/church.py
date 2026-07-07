"""Identidade visual da igreja (Missão 4 PR1) — branding tenant-scoped.

Spec: docs/design/BRANDING-IDENTIDADE-VISUAL-IGREJA.md. Endpoints admin-only
(gate padrão ``require_role(["admin"])`` + ``ensure_tenant_context``). A logo
vive no bucket PÚBLICO ``church-logos`` (criado manualmente em DEV/PROD — ver
runbook na spec §6); o Postgres guarda só o ponteiro ``igrejas.logo_path``.

Segurança:
- o path do objeto é SEMPRE derivado do igreja_id do token — nunca do payload —
  porque a service-role key bypassa a RLS do Storage;
- o UPDATE em ``igrejas`` roda sob role authenticated e depende da policy
  ``igrejas_self_update`` + grant por coluna (migration 20260707_011455); sem
  ela o flush do ORM falha alto (0 linhas → StaleDataError), nunca "sucesso"
  silencioso;
- a verdade sobre o formato é o CONTEÚDO (magic bytes), não o MIME declarado.
"""

from __future__ import annotations

import base64 as b64
import binascii
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Igreja
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.routers._common import ensure_tenant_context
from app.services.storage import (
    MAX_LOGO_BYTES,
    StorageError,
    SupabaseStorage,
    get_storage,
    logo_public_url,
)

router = APIRouter(prefix="/igreja", tags=["igreja"])

# Formatos aceitos (D5): PNG/JPEG/WebP. SVG fica fora do MVP (risco XSS, sem
# sanitização no projeto). "image/jpg" é alias comum de navegador para JPEG.
_CANONICAL_MIME = {
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/webp": "image/webp",
}

# (mime canônico, extensão, sniffer de magic bytes)
_MAGIC_SNIFFERS = (
    ("image/png", "png", lambda d: d[:8] == b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", "jpg", lambda d: d[:3] == b"\xff\xd8\xff"),
    ("image/webp", "webp", lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP"),
)


class UploadLogoRequest(BaseModel):
    """Logo como base64 puro em JSON (padrão do projeto — sem multipart)."""

    mime: str = Field(min_length=1, max_length=255)
    # Cap de fronteira: 1 MB de imagem ~= 1,37 MB de base64. O teto real (bytes
    # decodificados) é rechecado após o decode; este só rejeita cedo, na
    # validação, para não carregar um corpo gigante até o decode.
    base64: str = Field(min_length=1, max_length=1_500_000)


class BrandingOut(BaseModel):
    """Branding da igreja: nome (fallback textual) + URL pública da logo."""

    nome: str
    logoUrl: str | None = None  # noqa: N815 - external contract uses camelCase


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    """Identifica PNG/JPEG/WebP pelos magic bytes. None = não é formato aceito."""
    for mime, ext, matches in _MAGIC_SNIFFERS:
        if matches(data):
            return mime, ext
    return None


def _own_igreja(db: Session, current_user: CurrentUser) -> Igreja:
    """Carrega a linha da PRÓPRIA igreja (RLS: igrejas_self_select)."""
    igreja = db.execute(
        select(Igreja).where(Igreja.id == uuid.UUID(current_user.igreja_id))
    ).scalar_one_or_none()
    if igreja is None:
        # Não deve acontecer com um token válido; falha explícita > silêncio.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Igreja não encontrada",
        )
    return igreja


def _decode_and_validate(payload: UploadLogoRequest) -> tuple[bytes, str, str]:
    """Valida a logo (formato declarado, base64, tamanho, magic bytes).

    Retorna ``(bytes, mime canônico, extensão)`` ou levanta 400 com mensagem
    clara. O backend é a fonte de segurança (D5) — o frontend só pré-valida.
    """
    declared = _CANONICAL_MIME.get(payload.mime.strip().lower())
    if declared is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato não suportado. Envie uma imagem PNG, JPG ou WebP.",
        )
    try:
        data = b64.b64decode(payload.base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Imagem inválida (base64).",
        ) from exc
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Imagem inválida (base64).",
        )
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A logo excede o limite de 1 MB.",
        )
    sniffed = _sniff_image(data)
    if sniffed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo não é uma imagem PNG, JPG ou WebP válida.",
        )
    mime, ext = sniffed
    if mime != declared:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O conteúdo do arquivo não corresponde ao formato informado.",
        )
    return data, mime, ext


@router.get("/branding", response_model=BrandingOut)
def get_branding(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> BrandingOut:
    """Branding atual da igreja do token (tela Identidade Visual do admin)."""
    ensure_tenant_context(db, current_user)
    igreja = _own_igreja(db, current_user)
    return BrandingOut(nome=igreja.nome, logoUrl=logo_public_url(igreja.logo_path))


@router.put("/logo", response_model=BrandingOut)
def upload_logo(
    payload: UploadLogoRequest,
    db: Session = Depends(get_db),
    storage: SupabaseStorage = Depends(get_storage),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> BrandingOut:
    """Envia/troca a logo da igreja do token. Valida antes de tocar o Storage."""
    ensure_tenant_context(db, current_user)
    data, mime, ext = _decode_and_validate(payload)
    igreja = _own_igreja(db, current_user)
    old_path = igreja.logo_path

    # Sufixo rotativo por upload = cache-busting sem query string (spec §3.2):
    # a URL muda a cada troca, então navegador/CDN nunca servem logo antiga.
    # O prefixo continua sendo o igreja_id AUTENTICADO (D4).
    path = f"{current_user.igreja_id}/logo-{uuid.uuid4().hex[:8]}.{ext}"
    try:
        storage.upload_logo(path, data, mime)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível enviar a logo ao armazenamento. Tente novamente.",
        ) from exc

    igreja.logo_path = path
    try:
        db.commit()
    except SQLAlchemyError as exc:
        # 0 linhas sob RLS (migration não aplicada) vira StaleDataError no
        # flush — remove o objeto recém-enviado e falha alto.
        storage.remove_logo([path])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível salvar a logo. Tente novamente.",
        ) from exc

    if old_path and old_path != path:
        storage.remove_logo([old_path])  # best-effort, pós-commit
    return BrandingOut(nome=igreja.nome, logoUrl=logo_public_url(path))


@router.delete("/logo", response_model=BrandingOut)
def remove_logo(
    db: Session = Depends(get_db),
    storage: SupabaseStorage = Depends(get_storage),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> BrandingOut:
    """Remove a logo customizada (volta ao fallback pelo nome). Idempotente."""
    ensure_tenant_context(db, current_user)
    igreja = _own_igreja(db, current_user)
    old_path = igreja.logo_path
    if old_path is not None:
        igreja.logo_path = None
        try:
            db.commit()
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Não foi possível remover a logo. Tente novamente.",
            ) from exc
        storage.remove_logo([old_path])  # best-effort, pós-commit
    return BrandingOut(nome=igreja.nome, logoUrl=None)

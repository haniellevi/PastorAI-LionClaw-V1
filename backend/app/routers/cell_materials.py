"""Materiais de apoio das células — publicação, leitura e inativação (Células PR3-PR9).

Somente a Central (pastor/admin) PUBLICA e INATIVA materiais; qualquer papel
autenticado da igreja LÊ (E14). Não há upload real de arquivo: guarda-se apenas
o link + metadados (``url``/``titulo``/``descricao``/``tipo``). ``igreja_id`` e
papel derivam sempre do contexto autenticado — nunca do payload.

Validação de borda (E1/E2, → 422):
  - ``titulo`` obrigatório, ≤ 120;
  - ``descricao`` opcional, ≤ 2000;
  - ``url`` obrigatória, ≤ 2048, iniciando por ``http://`` ou ``https://``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CelulaMaterial
from app.db.session import get_db
from app.deps import (
    CurrentUser,
    get_current_user,
    require_central,
    resolve_actor_pessoa_id,
)
from app.routers._common import ensure_tenant_context

router = APIRouter(prefix="/cell-materials", tags=["cell-materials"])

# Limites de borda (E1/E2).
MAX_TITULO = 120
MAX_DESCRICAO = 2000
MAX_URL = 2048
MAX_TIPO = 50

# Esquemas de URL aceitos (allowlist fechada).
_ALLOWED_URL_PREFIXES = ("http://", "https://")

# Paginação (contrato snake_case): padrão 20, máx 100.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreateMaterialRequest(BaseModel):
    """Corpo de publicação de material (link + metadados; sem upload real)."""

    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1, max_length=MAX_TITULO)
    url: str = Field(min_length=1, max_length=MAX_URL)
    descricao: str | None = Field(default=None, max_length=MAX_DESCRICAO)
    tipo: str | None = Field(default=None, max_length=MAX_TIPO)


class MaterialOut(BaseModel):
    """Contrato de saída em snake_case (espelha as colunas relevantes)."""

    id: str
    titulo: str
    descricao: str | None = None
    url: str | None = None
    tipo: str | None = None
    ativo: bool
    publicado_em: dt.datetime | None = None

    @classmethod
    def from_model(cls, m: CelulaMaterial) -> "MaterialOut":
        return cls(
            id=str(m.id),
            titulo=m.titulo,
            descricao=m.descricao,
            url=m.url,
            tipo=m.tipo,
            ativo=m.ativo,
            publicado_em=m.publicado_em,
        )


class MaterialPage(BaseModel):
    items: list[MaterialOut]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_material(
    db: Session, igreja_id: uuid.UUID, material_id: str
) -> CelulaMaterial:
    """Carrega o material do tenant ou 404 (id malformado também → 404)."""
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Material não encontrado"
    )
    try:
        material_uuid = uuid.UUID(material_id)
    except (ValueError, AttributeError) as exc:
        raise not_found from exc
    material = db.execute(
        select(CelulaMaterial).where(
            CelulaMaterial.id == material_uuid,
            CelulaMaterial.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()
    if material is None:
        raise not_found
    return material


def _validate_url(url: str) -> str:
    """Valida/normaliza a URL (E2): não vazia, ≤ 2048, http(s):// (senão 422)."""
    normalized = url.strip()
    if not normalized or len(normalized) > MAX_URL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url é obrigatória e deve ter no máximo 2048 caracteres",
        )
    if not normalized.lower().startswith(_ALLOWED_URL_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url deve iniciar com http:// ou https://",
        )
    return normalized


# ---------------------------------------------------------------------------
# POST /cell-materials
# ---------------------------------------------------------------------------
@router.post("", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
def publish_material(
    payload: CreateMaterialRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> MaterialOut:
    """Central publica um material (link). 403 para não-Central; 422 inválido.

    ``url`` obrigatória (http(s)://, ≤ 2048); ``titulo`` ≤ 120; ``descricao`` ≤
    2000. Sem upload real de arquivo. ``autor_id`` deriva da Pessoa do usuário.
    """
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)

    titulo = payload.titulo.strip()
    if not titulo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="titulo é obrigatório",
        )
    url = _validate_url(payload.url)
    descricao = (payload.descricao or "").strip() or None
    tipo = (payload.tipo or "").strip() or None

    actor = resolve_actor_pessoa_id(db, current_user)
    autor_id = uuid.UUID(actor) if actor else None

    material = CelulaMaterial(
        igreja_id=igreja_id,
        autor_id=autor_id,
        titulo=titulo,
        descricao=descricao,
        url=url,
        tipo=tipo,
        ativo=True,
        publicado_em=dt.datetime.now(dt.timezone.utc),
    )
    db.add(material)
    db.flush()
    db.refresh(material)
    db.commit()
    return MaterialOut.from_model(material)


# ---------------------------------------------------------------------------
# GET /cell-materials
# ---------------------------------------------------------------------------
@router.get("", response_model=MaterialPage)
def list_materials(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Items per page (max 100)",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> MaterialPage:
    """Lista materiais ATIVOS da própria igreja (E14, leitura de qualquer papel).

    Mais recentes primeiro (``publicado_em`` desc). Apenas ``ativo=true``. Paginado.
    """
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)

    rows = db.execute(
        select(CelulaMaterial)
        .where(
            CelulaMaterial.igreja_id == igreja_id,
            CelulaMaterial.ativo.is_(True),
        )
        .order_by(CelulaMaterial.publicado_em.desc())
    ).scalars().all()

    total = len(rows)
    start = (page - 1) * page_size
    window = rows[start : start + page_size]
    return MaterialPage(
        items=[MaterialOut.from_model(m) for m in window],
        page=page,
        page_size=page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# DELETE /cell-materials/{material_id}
# ---------------------------------------------------------------------------
@router.delete("/{material_id}", response_model=MaterialOut)
def remove_material(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> MaterialOut:
    """Central inativa (``ativo=false``) um material. 403 não-Central; 404 se não existe.

    Sem exclusão física nem edição no MVP. Idempotente em ``ativo=false``.
    """
    ensure_tenant_context(db, current_user)
    igreja_id = uuid.UUID(current_user.igreja_id)

    material = _load_material(db, igreja_id, material_id)
    if material.ativo:
        material.ativo = False
        material.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        db.refresh(material)
        db.commit()
    return MaterialOut.from_model(material)

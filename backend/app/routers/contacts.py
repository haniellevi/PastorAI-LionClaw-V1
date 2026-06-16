"""Contacts router — unified person model (F2/F6/F7).

Endpoints:
  - GET  /contacts                 paginated tenant contacts (RNF-09)
  - POST /contacts                 create a contact, deduped by (telefone, igreja)
  - POST /contacts/{id}/cell       link a contact to a cell (fires trg_link_cell_promote)

All access is tenant-scoped by RLS (current_igreja_id). Writes set igreja_id
explicitly so the RLS WITH CHECK passes, and rely on the database triggers for
state-machine side effects rather than re-implementing them in the app.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Celula, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user, require_role
from app.domain.phone import normalize_phone, phone_suffix
from app.routers._common import Page, PaginationParams, ensure_tenant_context

logger = logging.getLogger("pastorai.contacts")

router = APIRouter(prefix="/contacts", tags=["contacts"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ContactOut(BaseModel):
    """Contact projection returned to clients."""

    id: str
    nome: str
    telefone: str
    email: str | None = None
    genero: str | None = None
    tipo: str | None = None
    etapa: str | None = None
    subetapa: str | None = None
    acompanhamento: str | None = None
    presencasCelula: int  # noqa: N815
    aceitouJesus: bool  # noqa: N815
    celulaId: str | None = None  # noqa: N815
    liderId: str | None = None  # noqa: N815

    @classmethod
    def from_model(cls, p: Pessoa) -> "ContactOut":
        return cls(
            id=str(p.id),
            nome=p.nome,
            telefone=p.telefone,
            email=p.email,
            genero=p.genero,
            tipo=p.tipo,
            etapa=p.etapa,
            subetapa=p.subetapa,
            acompanhamento=p.acompanhamento,
            presencasCelula=p.presencas_celula,
            aceitouJesus=p.aceitou_jesus,
            celulaId=str(p.celula_id) if p.celula_id else None,
            liderId=str(p.lider_id) if p.lider_id else None,
        )


class CreateContactRequest(BaseModel):
    """Payload for creating a contact (validated at the edge)."""

    nome: str = Field(min_length=1, max_length=200)
    telefone: str = Field(min_length=3, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    genero: str | None = Field(default=None)
    faixaEtaria: str | None = Field(default=None, max_length=40)  # noqa: N815
    endereco: str | None = Field(default=None, max_length=400)
    tipo: str | None = Field(default=None)
    origem: str | None = Field(default=None, max_length=120)

    @field_validator("nome", "telefone")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatório")
        return value

    @field_validator("genero")
    @classmethod
    def _genero(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in {"m", "f"}:
            raise ValueError("genero deve ser 'm' ou 'f'")
        return value

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        allowed = {"visitante", "membro", "lider", "pastor", "discipulo"}
        if value not in allowed:
            raise ValueError(f"tipo inválido: {value}")
        return value


class CreateContactResponse(BaseModel):
    """Create result; `deduped` flags a hit on an existing (telefone, igreja)."""

    contact: ContactOut
    deduped: bool


class UpdateContactRequest(BaseModel):
    """Edição de dados cadastrais (somente admin). Campos ausentes não mudam."""

    nome: str | None = Field(default=None, max_length=200)
    telefone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    genero: str | None = Field(default=None)
    faixaEtaria: str | None = Field(default=None, max_length=40)  # noqa: N815
    endereco: str | None = Field(default=None, max_length=400)
    tipo: str | None = Field(default=None)

    @field_validator("nome", "telefone")
    @classmethod
    def _strip_opt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Campo não pode ser vazio")
        return value

    @field_validator("genero")
    @classmethod
    def _genero(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in {"m", "f"}:
            raise ValueError("genero deve ser 'm' ou 'f'")
        return value

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        allowed = {"visitante", "membro", "lider", "pastor", "discipulo"}
        if value not in allowed:
            raise ValueError(f"tipo inválido: {value}")
        return value


class LinkCellRequest(BaseModel):
    celulaId: str = Field(min_length=1)  # noqa: N815

    @field_validator("celulaId")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("celulaId inválido") from exc
        return value


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[ContactOut])
def list_contacts(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[ContactOut]:
    """Return the tenant's contacts, newest first, paginated (RNF-09)."""
    ensure_tenant_context(db, current_user)

    total = db.execute(
        select(func.count()).select_from(Pessoa)
    ).scalar_one()

    rows = db.execute(
        select(Pessoa)
        .order_by(Pessoa.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    return Page[ContactOut](
        items=[ContactOut.from_model(p) for p in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("", response_model=CreateContactResponse)
def create_contact(
    payload: CreateContactRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CreateContactResponse:
    """Create a contact, deduping by normalized (telefone, igreja).

    When a contact with the same normalized phone already exists in the tenant,
    no duplicate is created: the existing record is returned with deduped=true.
    """
    ensure_tenant_context(db, current_user)

    normalized = normalize_phone(payload.telefone)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telefone inválido",
        )

    # Dedupe by CANONICAL phone (look up before creating): narrow by the stable
    # 8-digit suffix in SQL, then confirm the full canonical match in Python so
    # +55 / 9th-digit variations of the same number collapse to one contact.
    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidates = db.execute(
        select(Pessoa).where(func.right(stored_digits, 8) == phone_suffix(normalized))
    ).scalars().all()
    existing = next(
        (p for p in candidates if normalize_phone(p.telefone) == normalized),
        None,
    )

    if existing is not None:
        logger.info("create_contact deduped to existing pessoa")
        return CreateContactResponse(
            contact=ContactOut.from_model(existing), deduped=True
        )

    pessoa = Pessoa(
        igreja_id=uuid.UUID(current_user.igreja_id),
        nome=payload.nome,
        telefone=payload.telefone,
        email=payload.email,
        genero=payload.genero,
        faixa_etaria=payload.faixaEtaria,
        endereco=payload.endereco,
        tipo=payload.tipo or "visitante",
        origem=payload.origem,
    )
    db.add(pessoa)
    db.flush()  # fires person triggers; assigns server defaults
    db.refresh(pessoa)
    db.commit()

    return CreateContactResponse(
        contact=ContactOut.from_model(pessoa), deduped=False
    )


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: str,
    payload: UpdateContactRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> ContactOut:
    """Edita os dados cadastrais de uma pessoa (somente admin — RF-05).

    Tenant-scoped (RLS). Campos ausentes/None não mudam. Se o telefone mudar,
    re-checa o dedup canônico por igreja: não pode colidir com OUTRA pessoa
    (409). Os gatilhos de estado da pessoa não são reimplementados aqui.
    """
    ensure_tenant_context(db, current_user)

    try:
        pessoa_uuid = uuid.UUID(contact_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        ) from exc

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_uuid)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        )

    if payload.telefone is not None:
        normalized = normalize_phone(payload.telefone)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Telefone inválido",
            )
        # Colisão com OUTRA pessoa do tenant (mesmo telefone canônico).
        stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
        candidates = db.execute(
            select(Pessoa).where(
                func.right(stored_digits, 8) == phone_suffix(normalized),
                Pessoa.id != pessoa_uuid,
            )
        ).scalars().all()
        if any(normalize_phone(p.telefone) == normalized for p in candidates):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe outra pessoa com este telefone",
            )
        pessoa.telefone = payload.telefone

    if payload.nome is not None:
        pessoa.nome = payload.nome
    if payload.email is not None:
        pessoa.email = payload.email
    if payload.genero is not None:
        pessoa.genero = payload.genero
    if payload.faixaEtaria is not None:
        pessoa.faixa_etaria = payload.faixaEtaria
    if payload.endereco is not None:
        pessoa.endereco = payload.endereco
    if payload.tipo is not None:
        pessoa.tipo = payload.tipo

    db.flush()
    db.refresh(pessoa)
    db.commit()

    return ContactOut.from_model(pessoa)


@router.post("/{contact_id}/cell", response_model=ContactOut)
def link_cell(
    contact_id: str,
    payload: LinkCellRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ContactOut:
    """Link a contact to an active, led cell.

    Blocks linking to an inactive cell or one without a leader. The actual
    follow-up promotion is performed by the database trigger
    `trg_link_cell_promote` when celula_id transitions to a value.

    A person belongs to a single cell (delta-049): the first link is open to the
    normal flow, but MOVING someone from one cell to another is admin-only.
    """
    ensure_tenant_context(db, current_user)

    try:
        pessoa_uuid = uuid.UUID(contact_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        ) from exc

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_uuid)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        )

    celula = db.execute(
        select(Celula).where(Celula.id == uuid.UUID(payload.celulaId))
    ).scalar_one_or_none()
    if celula is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        )

    if not celula.ativo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Célula inativa não pode receber contatos",
        )
    if celula.lider_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Célula sem líder não pode receber contatos",
        )

    # Transferir alguém que já está numa célula para OUTRA é só do admin; a
    # primeira vinculação (sem célula) segue liberada ao fluxo normal.
    if (
        pessoa.celula_id is not None
        and pessoa.celula_id != celula.id
        and not current_user.has_role("admin")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas um administrador pode transferir alguém de célula",
        )

    pessoa.celula_id = celula.id
    db.flush()  # fires trg_link_cell_promote (acompanhamento -> consolidado)
    db.refresh(pessoa)
    db.commit()

    return ContactOut.from_model(pessoa)

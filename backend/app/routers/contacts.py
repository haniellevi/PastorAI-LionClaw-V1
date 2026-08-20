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

import dataclasses
import datetime as dt
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Celula,
    CelulaMembro,
    ConsentRecord,
    Conversation,
    Pessoa,
    PessoaArquivamentoEvento,
    WorkQueueItem,
)
from app.db.session import get_db
from app.deps import (
    CurrentUser,
    get_current_user,
    require_central,
    require_role,
    resolve_actor_pessoa_id,
)
from app.domain.phone import normalize_phone, phone_suffix
from app.services.pessoa_dedup import (
    _PG_UNIQUE_VIOLATION,
    insert_pessoa_or_get_winner,
    lock_canonical_phone,
)
from app.services import pessoa_offboarding_service
from app.services.celula_membro import ensure_active_membro
from app.routers._common import Page, PaginationParams

logger = logging.getLogger("pastorai.contacts")

router = APIRouter(prefix="/contacts", tags=["contacts"])

_CELL_CONNECTION_QUEUE_TYPE = "conectar_celula"
_OPEN_QUEUE_STATUSES = ("aberto", "assumido")

# Tipos atribuíveis manualmente. "lider" saiu de propósito: líder de célula é
# DERIVADO (celulas.lider_id em célula ativa), nunca um rótulo manual — a
# aptidão (Reencontro) é a flag apto_lider (decisão do dono 2026-07-06).
_TIPOS_PERMITIDOS = {"contato", "visitante", "membro", "pastor", "discipulo"}

# Papéis com visão tenant-wide de Pessoas. ``has_any_role`` preserva a união dos
# papéis e concede acesso implícito ao admin, mesmo sem listá-lo aqui.
CONTACTS_TENANT_WIDE_ROLES = [
    "pastor",
    "lider_g12",
    "lider_consol",
]

# Somente papéis que realmente operam uma caixa de entrada restrita recebem a
# exceção de Pessoa por conversa atribuída. ``membro`` e ``lider_mult`` não a
# herdam apenas porque uma Conversation foi associada artificialmente a eles.
CONTACTS_RESTRICTED_INBOX_ROLES = {"lider_celula", "operador"}

ContactView = Literal[
    "all",
    "pending",
    "contato",
    "visitante",
    "membro",
    "discipulo",
    "pastor",
    "lideres_celula",
    "aptos",
    "csim",
    "arquivadas",
]


def _validate_tipo(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if value == "lider":
        raise ValueError(
            "tipo 'lider' não é atribuível manualmente — "
            "liderança deriva do vínculo com célula ativa"
        )
    if value not in _TIPOS_PERMITIDOS:
        raise ValueError(f"tipo inválido: {value}")
    return value


def _leads_active_cell(db: Session, pessoa_id) -> bool:
    """True se a pessoa lidera alguma célula ATIVA (líder de célula derivado)."""
    return (
        db.execute(
            select(Celula.id)
            .where(Celula.lider_id == pessoa_id, Celula.ativo.is_(True))
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _active_leader_ids(
    db: Session, pessoa_ids: list[uuid.UUID]
) -> set[str]:
    """IDs da página que lideram célula ativa no tenant (RLS).

    A listagem chama esta projeção depois da paginação. Restringir o ``IN`` aos
    IDs retornados evita carregar todos os líderes ativos do tenant em cada
    página, sem duplicar na aplicação a regra de isolamento mantida pela RLS.
    """
    if not pessoa_ids:
        return set()

    rows = db.execute(
        select(Celula.lider_id)
        .where(
            Celula.ativo.is_(True),
            Celula.lider_id.in_(pessoa_ids),
        )
        .distinct()
    ).scalars().all()
    return {str(r) for r in rows}


def _contact_view_conditions(view: ContactView):
    """SQL predicates for the contacts tabs, applied before count/pagination.

    The active-cell leader predicate is a correlated EXISTS. Tenant isolation
    remains the database RLS policy for both ``pessoas`` and ``celulas``.
    """

    leads_active_cell = (
        select(Celula.id)
        .where(Celula.lider_id == Pessoa.id, Celula.ativo.is_(True))
        .correlate(Pessoa)
        .exists()
    )

    if view == "arquivadas":
        return (Pessoa.arquivada_em.is_not(None),)

    active = Pessoa.arquivada_em.is_(None)
    if view == "all":
        return (active,)
    if view in _TIPOS_PERMITIDOS:
        return (active, Pessoa.tipo == view)
    if view == "csim":
        return (active, Pessoa.sem_interesse.is_(True))
    if view == "lideres_celula":
        return (active, Pessoa.sem_interesse.is_(False), leads_active_cell)
    if view == "aptos":
        return (
            active,
            Pessoa.sem_interesse.is_(False),
            Pessoa.apto_lider.is_(True),
            ~leads_active_cell,
        )

    # ``pending`` mirrors followStatus(...).label == "Sem acompanhamento":
    # no consolidated/in-progress status, no cell, no pastor and not an active
    # cell leader. Archived records stay out through ``active``; CSIM follows
    # the previous client rule and can also be pending when no follow-up exists.
    return (
        active,
        func.lower(func.coalesce(Pessoa.acompanhamento, "")).not_in(
            ("consolidado", "em_consolidacao", "em_andamento")
        ),
        or_(Pessoa.subetapa.is_(None), Pessoa.subetapa != "consolidado"),
        Pessoa.celula_id.is_(None),
        or_(Pessoa.tipo.is_(None), Pessoa.tipo != "pastor"),
        ~leads_active_cell,
    )


def _contact_scope_conditions(
    db: Session,
    current_user: CurrentUser,
    *,
    include_assigned_conversation: bool = False,
):
    """Return SQL predicates for the caller's row-level Pessoas visibility.

    Tenant-wide roles retain the complete tenant view. A cell leader sees their
    own Pessoa plus Pessoas with an active canonical membership in an active
    cell they lead. Restricted inbox roles may additionally see Pessoas of
    tenant Conversations currently assigned to the caller. Other restricted
    roles see only their own Pessoa.

    Every branch carries explicit tenant predicates in addition to RLS. When a
    restricted caller has no linked Pessoa (and no detail exception applies),
    ``false()`` makes count and row queries return an empty result fail-closed.
    """

    igreja_id = uuid.UUID(current_user.igreja_id)
    tenant_condition = Pessoa.igreja_id == igreja_id

    if current_user.has_any_role(CONTACTS_TENANT_WIDE_ROLES):
        return (tenant_condition,)

    actor_pessoa_id = resolve_actor_pessoa_id(db, current_user)
    actor_uuid = uuid.UUID(actor_pessoa_id) if actor_pessoa_id else None
    visible = []

    if actor_uuid is not None:
        visible.append(Pessoa.id == actor_uuid)

        if "lider_celula" in current_user.roles:
            active_member_of_led_cell = (
                select(CelulaMembro.id)
                .join(Celula, Celula.id == CelulaMembro.celula_id)
                .where(
                    CelulaMembro.igreja_id == igreja_id,
                    CelulaMembro.pessoa_id == Pessoa.id,
                    CelulaMembro.ativo.is_(True),
                    Celula.igreja_id == igreja_id,
                    Celula.lider_id == actor_uuid,
                    Celula.ativo.is_(True),
                )
                .correlate(Pessoa)
                .exists()
            )
            visible.append(active_member_of_led_cell)

    if (
        include_assigned_conversation
        and current_user.roles & CONTACTS_RESTRICTED_INBOX_ROLES
    ):
        assigned_conversation = (
            select(Conversation.id)
            .where(
                Conversation.igreja_id == igreja_id,
                Conversation.pessoa_id == Pessoa.id,
                Conversation.assumido_por == uuid.UUID(current_user.app_user_id),
            )
            .correlate(Pessoa)
            .exists()
        )
        visible.append(assigned_conversation)

    return (tenant_condition, or_(*visible) if visible else false())


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
    semInteresse: bool = False  # noqa: N815 - CSIM (#1)
    semInteresseMotivo: str | None = None  # noqa: N815
    presencasCelula: int  # noqa: N815
    aceitouJesus: bool  # noqa: N815
    celulaId: str | None = None  # noqa: N815
    liderId: str | None = None  # noqa: N815
    aptoLider: bool = False  # noqa: N815 - realizou o Reencontro
    liderDeCelula: bool = False  # noqa: N815 - derivado: lidera célula ativa
    # FECH-06/REATIVAR-1: derivado de arquivada_em — permite à UI separar as
    # pessoas arquivadas das listas normais (sem expor por/motivo na listagem).
    arquivada: bool = False

    @classmethod
    def from_model(cls, p: Pessoa, *, lider_de_celula: bool = False) -> "ContactOut":
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
            semInteresse=bool(p.sem_interesse),
            semInteresseMotivo=p.sem_interesse_motivo,
            presencasCelula=p.presencas_celula,
            aceitouJesus=p.aceitou_jesus,
            celulaId=str(p.celula_id) if p.celula_id else None,
            liderId=str(p.lider_id) if p.lider_id else None,
            aptoLider=bool(p.apto_lider),
            liderDeCelula=lider_de_celula,
            arquivada=p.arquivada_em is not None,
        )


class ContactDetailOut(BaseModel):
    """Detalhe completo de uma pessoa — alimenta o painel de dados do chat.

    Estende ``ContactOut`` com os campos cadastrais e de jornada que só fazem
    sentido na visão de um contato (endereço, faixa etária, datas, consentimento)
    e resolve os nomes da célula e do líder para exibição direta.
    """

    id: str
    nome: str
    telefone: str
    email: str | None = None
    genero: str | None = None
    faixaEtaria: str | None = None  # noqa: N815
    endereco: str | None = None
    tipo: str | None = None
    etapa: str | None = None
    subetapa: str | None = None
    acompanhamento: str | None = None
    semInteresse: bool = False  # noqa: N815 - CSIM (#1)
    semInteresseMotivo: str | None = None  # noqa: N815
    presencasCelula: int  # noqa: N815
    aceitouJesus: bool  # noqa: N815
    celulaId: str | None = None  # noqa: N815
    celulaNome: str | None = None  # noqa: N815
    liderId: str | None = None  # noqa: N815
    liderNome: str | None = None  # noqa: N815
    aptoLider: bool = False  # noqa: N815 - realizou o Reencontro
    liderDeCelula: bool = False  # noqa: N815 - derivado: lidera célula ativa
    arquivada: bool = False
    consentimento: bool
    optout: bool
    origem: str | None = None
    primeiroContato: str | None = None  # noqa: N815
    criadoEm: str | None = None  # noqa: N815

    @classmethod
    def from_model(
        cls,
        p: Pessoa,
        *,
        celula_nome: str | None = None,
        lider_nome: str | None = None,
        lider_de_celula: bool = False,
    ) -> "ContactDetailOut":
        return cls(
            id=str(p.id),
            nome=p.nome,
            telefone=p.telefone,
            email=p.email,
            genero=p.genero,
            faixaEtaria=p.faixa_etaria,
            endereco=p.endereco,
            tipo=p.tipo,
            etapa=p.etapa,
            subetapa=p.subetapa,
            acompanhamento=p.acompanhamento,
            semInteresse=bool(p.sem_interesse),
            semInteresseMotivo=p.sem_interesse_motivo,
            presencasCelula=p.presencas_celula,
            aceitouJesus=p.aceitou_jesus,
            celulaId=str(p.celula_id) if p.celula_id else None,
            celulaNome=celula_nome,
            liderId=str(p.lider_id) if p.lider_id else None,
            liderNome=lider_nome,
            aptoLider=bool(p.apto_lider),
            liderDeCelula=lider_de_celula,
            arquivada=p.arquivada_em is not None,
            consentimento=p.consentimento,
            optout=p.optout,
            origem=p.origem,
            primeiroContato=(
                p.primeiro_contato.isoformat() if p.primeiro_contato else None
            ),
            criadoEm=p.created_at.isoformat() if p.created_at else None,
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
        return _validate_tipo(value)


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
    semInteresse: bool | None = Field(default=None)  # noqa: N815 - CSIM (#1)
    semInteresseMotivo: str | None = Field(default=None, max_length=200)  # noqa: N815
    aptoLider: bool | None = Field(default=None)  # noqa: N815 - Reencontro

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
        return _validate_tipo(value)


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


class PreflightItemOut(BaseModel):
    """Bloqueador, efeito automático ou item preservado (mesmo formato — M7B-W3.2A)."""

    tipo: str
    rotulo: str
    recurso_id: str | None = None
    recurso_nome: str | None = None
    acao_recomendada: str | None = None


class OffboardingPreflightOut(BaseModel):
    """Resposta de ``GET /contacts/{pessoa_id}/offboarding-preflight``."""

    pessoa_id: str
    pode_arquivar: bool
    bloqueadores: list[PreflightItemOut]
    automaticos: list[PreflightItemOut]
    preservados: list[PreflightItemOut]


class ArchiveContactRequest(BaseModel):
    """Payload de ``POST /contacts/{pessoa_id}/archive`` — motivo obrigatório."""

    motivo: str = Field(min_length=1, max_length=2000)

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("motivo é obrigatório")
        return trimmed


class ReactivateCommunicationsResponse(BaseModel):
    """Resposta de ``POST /contacts/{pessoa_id}/reactivate-communications`` (OPTIN-1).

    ``ja_ativa`` sinaliza a chamada idempotente (pessoa NÃO estava em opt-out):
    nada muda e nenhum consentimento novo é gravado — espelho do padrão
    ``ja_arquivada`` do archive. ``reativada_por`` registra o app_user que
    executou a reativação (auditoria da ação administrativa).
    """

    pessoa_id: str
    optout: bool
    termo_versao: str
    reativada_por: str | None
    ja_ativa: bool


class ArchiveContactResponse(BaseModel):
    pessoa_id: str
    arquivada: bool
    arquivada_em: str
    arquivada_por: str | None
    arquivada_motivo: str
    # W3.2A (revisão externa PR#163): sinaliza explicitamente quando a chamada
    # foi um no-op idempotente (pessoa já estava arquivada) — o cliente não
    # tem como distinguir "acabei de arquivar" de "já estava arquivada" só
    # olhando `arquivada=true`. `arquivada_motivo`/`arquivada_por` nesse caso
    # são sempre os do arquivamento ORIGINAL, nunca sobrescritos.
    ja_arquivada: bool


class UnarchiveContactResponse(BaseModel):
    """Resposta de ``POST /contacts/{pessoa_id}/unarchive`` (FECH-06/REATIVAR-1).

    Caminho de volta do archive: ``arquivada`` volta a ``False`` e
    ``reativada_por`` registra o app_user que executou a reativação
    (a trilha completa fica em ``pessoa_arquivamento_evento``).
    """

    pessoa_id: str
    arquivada: bool
    reativada_por: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[ContactOut])
def list_contacts(
    pagination: PaginationParams = Depends(),
    view: ContactView = Query(default="all"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[ContactOut]:
    """Return one filtered, role-scoped tenant page, newest first (RNF-09)."""

    conditions = (
        *_contact_view_conditions(view),
        *_contact_scope_conditions(
            db, current_user, include_assigned_conversation=True
        ),
    )

    total = db.execute(
        select(func.count()).select_from(Pessoa).where(*conditions)
    ).scalar_one()

    order_by = (
        (Pessoa.sem_interesse.asc(), Pessoa.created_at.desc(), Pessoa.id.desc())
        if view == "all"
        else (Pessoa.created_at.desc(), Pessoa.id.desc())
    )
    rows = db.execute(
        select(Pessoa)
        .where(*conditions)
        .order_by(*order_by)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    leader_ids = _active_leader_ids(db, [p.id for p in rows])
    return Page[ContactOut](
        items=[
            ContactOut.from_model(p, lider_de_celula=str(p.id) in leader_ids)
            for p in rows
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("", response_model=CreateContactResponse)
def create_contact(
    payload: CreateContactRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(CONTACTS_TENANT_WIDE_ROLES)),
) -> CreateContactResponse:
    """Create a contact for a tenant-wide role, deduped by (telefone, igreja).

    When a contact with the same normalized phone already exists in the tenant,
    no duplicate is created: the existing record is returned with deduped=true.
    """

    normalized = normalize_phone(payload.telefone)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telefone inválido",
        )
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    lock_canonical_phone(db, igreja_id=igreja_uuid, canonical=normalized)

    # Dedupe by CANONICAL phone (look up before creating): narrow by the stable
    # 8-digit suffix in SQL, then confirm the full canonical match in Python so
    # +55 / 9th-digit variations of the same number collapse to one contact.
    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidates = db.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_uuid,
            func.right(stored_digits, 8) == phone_suffix(normalized),
        )
    ).scalars().all()
    existing = next(
        (p for p in candidates if normalize_phone(p.telefone) == normalized),
        None,
    )

    if existing is not None:
        logger.info("create_contact deduped to existing pessoa")
        return CreateContactResponse(
            contact=ContactOut.from_model(
                existing, lider_de_celula=_leads_active_cell(db, existing.id)
            ),
            deduped=True,
        )

    new_pessoa = Pessoa(
        igreja_id=igreja_uuid,
        nome=payload.nome,
        telefone=payload.telefone,
        email=payload.email,
        genero=payload.genero,
        faixa_etaria=payload.faixaEtaria,
        endereco=payload.endereco,
        # Entrada da jornada: sem tipo explícito, nasce como "contato" (US-10).
        tipo=payload.tipo or "contato",
        origem=payload.origem,
    )
    # UNIQ-PESSOA-1: SAVEPOINT + re-fetch. Se uma criação concorrente do mesmo
    # telefone/tenant venceu entre a dedupe acima e este INSERT,
    # uq_pessoas_telefone_ativa levanta unique_violation e reaproveitamos a
    # Pessoa vencedora (deduped=True) — nada de duplicata nem 500.
    pessoa = insert_pessoa_or_get_winner(
        db,
        new_pessoa,
        igreja_id=igreja_uuid,
        canonical=normalized,
    )
    db.refresh(pessoa)
    db.commit()

    if pessoa is not new_pessoa:
        logger.info("create_contact deduped to existing pessoa (race)")
        return CreateContactResponse(
            contact=ContactOut.from_model(
                pessoa, lider_de_celula=_leads_active_cell(db, pessoa.id)
            ),
            deduped=True,
        )

    return CreateContactResponse(
        contact=ContactOut.from_model(pessoa), deduped=False
    )


@router.get("/{contact_id}", response_model=ContactDetailOut)
def get_contact(
    contact_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ContactDetailOut:
    """Detalhe completo de uma pessoa para o painel de dados do chat (Parte B).

    Tenant-wide roles see any Pessoa in the tenant. Restricted roles see their
    own Pessoa, active members of an active cell they lead, or the Pessoa of a
    tenant Conversation currently assigned to them. The visibility predicate is
    applied before loading cell/leader labels; out-of-scope IDs return 404.
    """

    try:
        pessoa_uuid = uuid.UUID(contact_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        ) from exc

    scope_conditions = _contact_scope_conditions(
        db, current_user, include_assigned_conversation=True
    )
    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_uuid, *scope_conditions)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        )

    # Nomes de célula e líder resolvidos à parte (consultas simples, escopo de
    # tenant garantido pela RLS) para exibir rótulos legíveis no painel.
    celula_nome: str | None = None
    if pessoa.celula_id:
        celula_nome = db.execute(
            select(Celula.nome).where(Celula.id == pessoa.celula_id)
        ).scalar_one_or_none()

    lider_nome: str | None = None
    if pessoa.lider_id:
        lider_nome = db.execute(
            select(Pessoa.nome).where(Pessoa.id == pessoa.lider_id)
        ).scalar_one_or_none()

    return ContactDetailOut.from_model(
        pessoa,
        celula_nome=celula_nome,
        lider_nome=lider_nome,
        lider_de_celula=_leads_active_cell(db, pessoa.id),
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
    igreja_uuid = uuid.UUID(current_user.igreja_id)

    try:
        pessoa_uuid = uuid.UUID(contact_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado"
        ) from exc

    pessoa = db.execute(
        select(Pessoa).where(
            Pessoa.id == pessoa_uuid,
            Pessoa.igreja_id == igreja_uuid,
        )
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
        lock_canonical_phone(db, igreja_id=igreja_uuid, canonical=normalized)
        # Colisão com OUTRA pessoa do tenant (mesmo telefone canônico).
        stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
        candidates = db.execute(
            select(Pessoa).where(
                Pessoa.igreja_id == uuid.UUID(current_user.igreja_id),
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
    # CSIM (#1): admin marca/desmarcar; ao desmarcar, limpa o motivo. Marcar
    # CSIM zera a aptidão — CSIM está fora da visão, nunca apto/líder. Quem
    # LIDERA célula ativa não pode virar CSIM sem antes trocar o líder (409).
    if payload.semInteresse is not None:
        if payload.semInteresse and _leads_active_cell(db, pessoa.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Pessoa lidera uma célula ativa — troque o líder da célula "
                    "antes de marcar sem interesse"
                ),
            )
        pessoa.sem_interesse = payload.semInteresse
        if not payload.semInteresse:
            pessoa.sem_interesse_motivo = None
        else:
            pessoa.apto_lider = False
            if payload.semInteresseMotivo is not None:
                pessoa.sem_interesse_motivo = payload.semInteresseMotivo

    # Aptidão (Reencontro): flag administrativa; CSIM não pode ser apto.
    if payload.aptoLider is not None:
        if payload.aptoLider and pessoa.sem_interesse:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Pessoa fora da igreja não pode ser apta a liderar",
            )
        pessoa.apto_lider = payload.aptoLider

    db.flush()
    db.refresh(pessoa)
    # Deriva ANTES do commit: o SET LOCAL da RLS reverte no commit e a query
    # passaria a rodar fora do contexto de tenant (role com BYPASSRLS).
    lider_de_celula = _leads_active_cell(db, pessoa.id)
    db.commit()

    return ContactOut.from_model(pessoa, lider_de_celula=lider_de_celula)


@router.post("/{contact_id}/cell", response_model=ContactOut)
def link_cell(
    contact_id: str,
    payload: LinkCellRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> ContactOut:
    """Link a contact to an active, led cell.

    Blocks linking to an inactive cell or one without a leader. The actual
    follow-up promotion is performed by the database trigger
    `trg_link_cell_promote` when celula_id transitions to a value.

    A person belongs to a single cell (delta-049): pastor/admin may create the
    first link, but MOVING someone from one cell to another remains admin-only.
    """

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
        select(Celula).where(
            Celula.id == uuid.UUID(payload.celulaId),
            Celula.igreja_id == uuid.UUID(current_user.igreja_id),
        )
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

    # D2: transferir alguém que já está numa célula para OUTRA é uma CAPACIDADE
    # decidida pelo domínio (pode_transferir); este adapter administrativo a
    # deriva do papel admin — a dependência da rota já restringe qualquer
    # vinculação à Central. A recusa (403 via handler global em app.main) acontece
    # DENTRO do ensure, antes de desativar o vínculo antigo — por isso o espelho
    # pessoas.celula_id só é tocado depois.
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    ensure_active_membro(
        db,
        igreja_id=igreja_uuid,
        celula_id=celula.id,
        pessoa_id=pessoa.id,
        pode_transferir=current_user.has_role("admin"),
    )
    pessoa.celula_id = celula.id
    db.flush()  # fires trg_link_cell_promote (acompanhamento -> consolidado)
    _resolve_cell_connection_queue_items(
        db,
        igreja_id=igreja_uuid,
        pessoa_id=pessoa.id,
    )
    db.flush()
    db.refresh(pessoa)
    # Deriva ANTES do commit (RLS: SET LOCAL reverte no commit).
    lider_de_celula = _leads_active_cell(db, pessoa.id)
    db.commit()

    return ContactOut.from_model(pessoa, lider_de_celula=lider_de_celula)


def _resolve_cell_connection_queue_items(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
) -> None:
    """Encerra pendências abertas cuja obrigação foi satisfeita pelo vínculo.

    O filtro explícito por tenant, pessoa e ``conectar_celula`` evita fechar
    outros trabalhos da mesma pessoa. ``NULL`` é um estado operacional legado
    aceito pela listagem da fila; ``resolvido`` e qualquer estado futuro não
    entram na seleção. O lock torna chamadas concorrentes idempotentes e todas
    as mudanças seguem no mesmo commit do vínculo canônico.
    """

    items = db.execute(
        select(WorkQueueItem)
        .where(
            WorkQueueItem.igreja_id == igreja_id,
            WorkQueueItem.pessoa_id == pessoa_id,
            WorkQueueItem.tipo == _CELL_CONNECTION_QUEUE_TYPE,
            or_(
                WorkQueueItem.status.is_(None),
                WorkQueueItem.status.in_(_OPEN_QUEUE_STATUSES),
            ),
        )
        .order_by(WorkQueueItem.id.asc())
        .with_for_update()
    ).scalars().all()
    for item in items:
        item.status = "resolvido"


def _get_pessoa_or_404(db: Session, pessoa_id: str) -> Pessoa:
    """Carrega a Pessoa no tenant (RLS) ou 404 — cross-tenant nunca revela existência."""
    try:
        pessoa_uuid = uuid.UUID(pessoa_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        ) from exc
    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_uuid)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )
    return pessoa


@router.get(
    "/{pessoa_id}/offboarding-preflight", response_model=OffboardingPreflightOut
)
def get_offboarding_preflight(
    pessoa_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> OffboardingPreflightOut:
    """Somente leitura: calcula se `pessoa_id` pode ser arquivada agora (M7B-W3.2A).

    Admin-only. Nenhuma mutação acontece aqui — inclusive o abandono automático
    de consolidação aberta só é aplicado dentro da transação real de
    ``POST .../archive`` (``automaticos`` aqui é só o aviso do que aconteceria).
    """
    pessoa = _get_pessoa_or_404(db, pessoa_id)
    result = pessoa_offboarding_service.preflight_archive(
        db,
        pessoa=pessoa,
        actor_app_user_id=uuid.UUID(current_user.app_user_id),
    )
    return OffboardingPreflightOut.model_validate(dataclasses.asdict(result))


@router.post("/{pessoa_id}/archive", response_model=ArchiveContactResponse)
def archive_contact(
    pessoa_id: str,
    payload: ArchiveContactRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> ArchiveContactResponse:
    """Arquiva `pessoa_id` (M7B-W3.2A) — nunca hard delete. Admin-only.

    Revalida o preflight DENTRO da transação travada (SEC-4B): qualquer
    bloqueador reverte e devolve 409 com a lista estruturada (mesmo formato do
    GET preflight). Pessoa já arquivada é idempotente (200, sem duplicar
    efeito). Única mutação em cascata: uma consolidação individual aberta da
    própria pessoa é encerrada como "abandonada" na mesma transação.
    """
    pessoa = _get_pessoa_or_404(db, pessoa_id)
    pessoa, ja_arquivada = pessoa_offboarding_service.archive_pessoa(
        db,
        pessoa=pessoa,
        actor_app_user_id=uuid.UUID(current_user.app_user_id),
        motivo=payload.motivo,
    )
    return ArchiveContactResponse(
        pessoa_id=str(pessoa.id),
        arquivada=True,
        arquivada_em=pessoa.arquivada_em.isoformat(),
        arquivada_por=str(pessoa.arquivada_por) if pessoa.arquivada_por else None,
        arquivada_motivo=pessoa.arquivada_motivo or "",
        ja_arquivada=ja_arquivada,
    )


@router.post("/{pessoa_id}/unarchive", response_model=UnarchiveContactResponse)
def unarchive_contact(
    pessoa_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin", "pastor"])),
) -> UnarchiveContactResponse:
    """Desarquiva `pessoa_id` (FECH-06/REATIVAR-1) — caminho de volta do archive.

    Restrito a admin/pastor (RBAC real via ``require_role``). Limpa
    ``arquivada_em/arquivada_por/arquivada_motivo`` e grava uma linha
    append-only em ``pessoa_arquivamento_evento`` com ``acao='reativada'`` —
    a metade do enum modelada em W3.2A e nunca usada até aqui. A pessoa volta
    às listas normais (o índice parcial ``uq_pessoas_telefone_ativa`` cobre
    apenas ``arquivada_em IS NULL``; se outra pessoa ATIVA já usa o mesmo
    telefone, o banco rejeita e nada é aplicado — rollback total).

    A query filtra ``igreja_id`` EXPLICITAMENTE (além da RLS): pessoa de outra
    igreja responde 404 sem revelar existência. Reativar pessoa NÃO arquivada
    responde 409 (mesmo status usado pelo archive para estado conflitante).
    O fluxo de arquivar (preflight + POST /archive) permanece intocado.
    """
    try:
        pessoa_uuid = uuid.UUID(pessoa_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        ) from exc

    igreja_uuid = uuid.UUID(current_user.igreja_id)
    pessoa = db.execute(
        select(Pessoa)
        .where(
            Pessoa.id == pessoa_uuid,
            # Filtro explícito de tenant (regra de ouro), além da RLS.
            Pessoa.igreja_id == igreja_uuid,
        )
        # Lock pessimista: serializa unarchives concorrentes da MESMA pessoa —
        # a segunda transação só lê o estado APÓS o commit da primeira e cai no
        # 409 "não está arquivada" em vez de gravar um 2º evento 'reativada'.
        .with_for_update()
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    if pessoa.arquivada_em is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pessoa não está arquivada",
        )

    motivo_original = (pessoa.arquivada_motivo or "").strip()
    pessoa.arquivada_em = None
    pessoa.arquivada_por = None
    pessoa.arquivada_motivo = None

    # Auditoria append-only na MESMA transação da reativação (espelho da linha
    # 'arquivada' gravada por archive_pessoa) — preserva o motivo original do
    # arquivamento, que acabou de ser limpo da Pessoa.
    db.add(
        PessoaArquivamentoEvento(
            igreja_id=igreja_uuid,
            pessoa_id=pessoa.id,
            ator_id=uuid.UUID(current_user.app_user_id),
            acao=pessoa_offboarding_service.ACAO_REATIVADA,
            motivo=(
                f"Reativação administrativa — motivo do arquivamento original: {motivo_original}"
                if motivo_original
                else "Reativação administrativa"
            ),
        )
    )
    logger.info(
        "unarchive_contact: pessoa=%s reativada por app_user=%s",
        pessoa.id,
        current_user.app_user_id,
    )
    try:
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Colisão com uq_pessoas_telefone_ativa: outra pessoa ATIVA do mesmo
        # tenant já usa este telefone (ex.: recriada via WhatsApp após o
        # arquivamento). Mesmo contrato 409 dos demais conflitos do endpoint.
        if getattr(exc.orig, "pgcode", None) != _PG_UNIQUE_VIOLATION:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Não é possível reativar: já existe uma pessoa ativa com este "
                "telefone nesta igreja."
            ),
        ) from exc

    return UnarchiveContactResponse(
        pessoa_id=str(pessoa.id),
        arquivada=False,
        reativada_por=str(current_user.app_user_id),
    )


@router.post(
    "/{pessoa_id}/reactivate-communications",
    response_model=ReactivateCommunicationsResponse,
)
def reactivate_communications(
    pessoa_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin", "pastor"])),
) -> ReactivateCommunicationsResponse:
    """Reativa comunicações de uma Pessoa em opt-out (FECH-05/OPTIN-1).

    Restrito a admin/pastor (RBAC real via ``require_role``). Caminho de volta
    do opt-out do agente (US-32/RNF-06): seta ``pessoas.optout=False`` e grava
    um ``ConsentRecord`` novo com ``termo_versao='reoptin:<versao>'`` — MESMA
    estrutura registrada por ``_apply_optout`` (agent/runtime.py), que usa
    ``'optout:<versao>'``. O histórico de consentimento fica íntegro: a
    retirada anterior nunca é apagada, a reativação é uma linha nova.

    A query filtra ``igreja_id`` EXPLICITAMENTE (além da RLS): pessoa de outra
    igreja responde 404 sem revelar existência. Chamada com a pessoa já ativa
    é idempotente (200, ``ja_ativa=True``, sem consentimento duplicado).

    O agente (silêncio em opt-out) e a exclusão de opt-out no broadcast NÃO
    são tocados por este fluxo — este endpoint é o ÚNICO caminho
    administrativo que escreve ``optout``.
    """
    try:
        pessoa_uuid = uuid.UUID(pessoa_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        ) from exc

    igreja_uuid = uuid.UUID(current_user.igreja_id)
    pessoa = db.execute(
        select(Pessoa)
        .where(
            Pessoa.id == pessoa_uuid,
            # Filtro explícito de tenant (regra de ouro), além da RLS.
            Pessoa.igreja_id == igreja_uuid,
        )
        # Lock pessimista: serializa reativações concorrentes da MESMA pessoa —
        # a segunda transação só lê o estado APÓS o commit da primeira, cai no
        # ramo idempotente (ja_ativa=True) e nenhum ConsentRecord duplicado é
        # gravado.
        .with_for_update()
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    termo_versao = f"reoptin:{get_settings().agent_term_version}"

    if not pessoa.optout:
        # Idempotente: já estava ativa — nada muda, nada é gravado.
        return ReactivateCommunicationsResponse(
            pessoa_id=str(pessoa.id),
            optout=False,
            termo_versao=termo_versao,
            reativada_por=str(current_user.app_user_id),
            ja_ativa=True,
        )

    pessoa.optout = False
    db.add(
        ConsentRecord(
            igreja_id=igreja_uuid,
            pessoa_id=pessoa.id,
            termo_versao=termo_versao,
            aceite_em=dt.datetime.now(dt.timezone.utc),
            # Autoria durável da ação administrativa (migration
            # 20260720_191143): QUEM reativou fica no próprio registro de
            # consentimento. NULL permanece o valor dos fluxos automáticos.
            ator_id=uuid.UUID(current_user.app_user_id),
        )
    )
    logger.info(
        "reactivate_communications: pessoa=%s reativada por app_user=%s (%s)",
        pessoa.id,
        current_user.app_user_id,
        termo_versao,
    )
    db.flush()
    db.commit()

    return ReactivateCommunicationsResponse(
        pessoa_id=str(pessoa.id),
        optout=False,
        termo_versao=termo_versao,
        reativada_por=str(current_user.app_user_id),
        ja_ativa=False,
    )

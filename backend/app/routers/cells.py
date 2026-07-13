"""Cells router — cells, alerts and leadership descendants (F7 / delta-007).

Endpoints:
  - GET  /cells                       paginated tenant cells
  - GET  /cells/{id}                  cell detail incl. its open alerts
  - POST /cells                       create or edit a cell (cobertura required)
  - POST /cells/{id}/alerts/{aid}/baixar  mark an alert as handled (tratado=true)
  - GET  /descendencias               leadership tree from pessoas.lider_id

Editing a cell (delta-007) is restricted to the cell's own leader, anyone above
that leader in the pessoas.lider_id chain, or a pastor/admin.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, CelulaMembro, CellAlert, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user, require_central
from app.domain.hierarchy import is_leader_or_superior
from app.routers._common import Page, PaginationParams
from app.services.celula_membro import (
    assert_membro_elegivel,
    assert_pessoas_nao_arquivadas,
    promote_tipo_para_membro,
)

logger = logging.getLogger("pastorai.cells")

router = APIRouter(tags=["cells"])

# Roles that may create a cell (admin always passes via has_any_role).
CELL_CREATE_ROLES = ["pastor", "lider_g12"]
# Roles treated as superior to any cell leader for edit authorization.
CELL_EDIT_SUPERIOR_ROLES = ["pastor"]
# Central de Células (decisão 3.1): pastor + admin (implícito) aprovam e alteram
# campos sensíveis. `lider_central` dedicado fica para o futuro (fora do MVP).
CENTRAL_ROLES = ["pastor"]
# Papéis válidos de vínculo em celula_membro (enum celula_membro_papel).
CELL_MEMBER_ROLES = ("membro", "auxiliar", "anfitriao")
# Horário no formato HH:MM (24h) — espelha o CHECK da migration.
_HORARIO_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AlertOut(BaseModel):
    id: str
    pessoaId: str  # noqa: N815
    gatilho: str | None = None
    acaoEsperada: str | None = None  # noqa: N815
    tratado: bool

    @classmethod
    def from_model(cls, a: CellAlert) -> "AlertOut":
        return cls(
            id=str(a.id),
            pessoaId=str(a.pessoa_id),
            gatilho=a.gatilho,
            acaoEsperada=a.acao_esperada,
            tratado=a.tratado,
        )


class CellOut(BaseModel):
    id: str
    nome: str
    liderId: str | None = None  # noqa: N815
    diaReuniao: str | None = None  # noqa: N815
    coberturaEspiritual: str  # noqa: N815
    # Sensíveis (3.2): só a Central altera direto.
    anfitriaoId: str | None = None  # noqa: N815
    auxiliarId: str | None = None  # noqa: N815
    endereco: str | None = None
    horario: str | None = None
    # Leves: o líder edita direto.
    linkGrupo: str | None = None  # noqa: N815
    linkLocalizacao: str | None = None  # noqa: N815
    mensagemConvite: str | None = None  # noqa: N815
    ativo: bool

    @classmethod
    def from_model(cls, c: Celula) -> "CellOut":
        return cls(
            id=str(c.id),
            nome=c.nome,
            liderId=str(c.lider_id) if c.lider_id else None,
            diaReuniao=c.dia_reuniao,
            coberturaEspiritual=c.cobertura_espiritual,
            anfitriaoId=str(c.anfitriao_id) if c.anfitriao_id else None,
            auxiliarId=str(c.auxiliar_id) if c.auxiliar_id else None,
            endereco=c.endereco,
            horario=c.horario,
            linkGrupo=c.link_grupo,
            linkLocalizacao=c.link_localizacao,
            mensagemConvite=c.mensagem_convite,
            ativo=c.ativo,
        )


class CellDetailOut(CellOut):
    alerts: list[AlertOut] = []


class MemberOut(BaseModel):
    id: str
    pessoaId: str  # noqa: N815
    papel: str
    ativo: bool

    @classmethod
    def from_model(cls, m: CelulaMembro) -> "MemberOut":
        return cls(
            id=str(m.id),
            pessoaId=str(m.pessoa_id),
            papel=m.papel,
            ativo=m.ativo,
        )


class AddMemberRequest(BaseModel):
    """Entrada direta de membro na célula (decisão 3.2 — sem Solicitação)."""

    pessoaId: str  # noqa: N815
    papel: str = "membro"

    @field_validator("pessoaId")
    @classmethod
    def _pessoa_uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("pessoaId inválido") from exc
        return value

    @field_validator("papel")
    @classmethod
    def _papel_valido(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in CELL_MEMBER_ROLES:
            raise ValueError(f"papel inválido: {value}")
        return value


class UpsertCellRequest(BaseModel):
    """Create (no id) or edit (with id) a cell. cobertura is mandatory.

    Campos sensíveis (diaReuniao, horario, endereco, anfitriaoId, auxiliarId) só
    são aplicáveis pela Central; um líder que não é Central e tenta alterá-los
    recebe 403 (decisão 3.2 — a alteração vira Solicitação no PR5).
    """

    id: str | None = None
    nome: str = Field(min_length=1, max_length=200)
    liderId: str | None = None  # noqa: N815
    coberturaEspiritual: str = Field(min_length=1, max_length=200)  # noqa: N815
    # Sensíveis.
    diaReuniao: str | None = Field(default=None, max_length=40)  # noqa: N815
    horario: str | None = Field(default=None, max_length=5)
    endereco: str | None = Field(default=None, max_length=400)
    anfitriaoId: str | None = None  # noqa: N815
    auxiliarId: str | None = None  # noqa: N815
    # Leves.
    linkGrupo: str | None = Field(default=None, max_length=500)  # noqa: N815
    linkLocalizacao: str | None = Field(default=None, max_length=500)  # noqa: N815
    mensagemConvite: str | None = Field(default=None, max_length=2000)  # noqa: N815
    ativo: bool = True

    @field_validator("nome", "coberturaEspiritual")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatório")
        return value

    @field_validator("id", "liderId", "anfitriaoId", "auxiliarId")
    @classmethod
    def _uuid_opt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("UUID inválido") from exc
        return value

    @field_validator("horario")
    @classmethod
    def _horario_fmt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _HORARIO_RE.match(value):
            raise ValueError("horário deve estar no formato HH:MM")
        return value

    @field_validator("diaReuniao", "endereco")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        # Normaliza vazio→None: evita 403 falso-positivo no guard de sensível
        # ("" vs None) e não persiste string vazia.
        if value is None:
            return None
        value = value.strip()
        return value or None


class TreeNode(BaseModel):
    id: str
    nome: str
    tipo: str | None = None
    children: list["TreeNode"] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _actor_pessoa_id(db: Session, current_user: CurrentUser) -> str | None:
    """Resolve the acting user's linked pessoa_id (for hierarchy checks)."""
    pessoa_id = db.execute(
        select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id)
        )
    ).scalar_one_or_none()
    return str(pessoa_id) if pessoa_id else None


def _lider_of_map(db: Session) -> dict[str, str | None]:
    """Tenant-scoped pessoa_id -> lider_id mapping for hierarchy walks."""
    rows = db.execute(select(Pessoa.id, Pessoa.lider_id)).all()
    return {str(pid): (str(lid) if lid else None) for pid, lid in rows}


def _leads_active_cell(
    db: Session, pessoa_id: uuid.UUID, igreja_id: uuid.UUID
) -> bool:
    """True se a pessoa lidera alguma célula ATIVA do tenant (espelha ``contacts.py``).

    igreja_id explícito = defesa em profundidade além da RLS, torna o
    isolamento testável no harness fake (igual list_cell_members).
    """
    return (
        db.execute(
            select(Celula.id)
            .where(
                Celula.lider_id == pessoa_id,
                Celula.ativo.is_(True),
                Celula.igreja_id == igreja_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _can_edit_cell(
    db: Session, current_user: CurrentUser, cell: Celula
) -> bool:
    """delta-007: leader of the cell, a superior in the chain, or pastor/admin."""
    if current_user.has_any_role(CELL_EDIT_SUPERIOR_ROLES):
        return True  # admin is covered by has_any_role's implicit access
    actor = _actor_pessoa_id(db, current_user)
    return is_leader_or_superior(
        actor_pessoa_id=actor,
        cell_leader_id=str(cell.lider_id) if cell.lider_id else None,
        lider_of=_lider_of_map(db),
    )


def _to_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _assert_pessoa_tenant(
    db: Session, pessoa_uuid: uuid.UUID | None, campo: str
) -> None:
    """Garante que a pessoa referenciada existe NO TENANT atual (via RLS).

    A FK do Postgres não é RLS-scoped, então um UUID de pessoa de outra igreja
    passaria pela integridade referencial. Carregar sob RLS (a sessão já está no
    contexto do tenant) e rejeitar 422 fecha esse vazamento cross-tenant.
    """
    if pessoa_uuid is None:
        return
    found = db.execute(
        select(Pessoa.id).where(Pessoa.id == pessoa_uuid)
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{campo}: pessoa não encontrada nesta igreja",
        )


def _validate_pessoa_refs(db: Session, payload: UpsertCellRequest) -> None:
    """Valida o tenant de todas as pessoas referenciadas pela célula."""
    _assert_pessoa_tenant(db, _to_uuid(payload.liderId), "liderId")
    _assert_pessoa_tenant(db, _to_uuid(payload.anfitriaoId), "anfitriaoId")
    _assert_pessoa_tenant(db, _to_uuid(payload.auxiliarId), "auxiliarId")


def _assert_referenced_pessoas_nao_arquivadas(
    db: Session, current_user: CurrentUser, payload: UpsertCellRequest
) -> None:
    """Líder/anfitrião/auxiliar não podem estar arquivados (revisão externa
    PR#163). Guarda canônica (``assert_pessoas_nao_arquivadas`` de
    ``celula_membro.py`` — mesma usada por ``add_cell_member``/
    ``create_cell_request``/``approve``, sem duplicar a checagem de
    ``arquivada_em``). ``for_update=True`` trava as Pessoas referenciadas
    (ordem determinística por id) para serializar contra ``archive_pessoa``,
    que trava a própria Pessoa com o mesmo padrão SEC-4B — só um dos dois
    estados pode vencer (ver docstring de ``assert_pessoas_nao_arquivadas``).
    """
    assert_pessoas_nao_arquivadas(
        db,
        igreja_id=uuid.UUID(current_user.igreja_id),
        pessoa_ids=[payload.liderId, payload.anfitriaoId, payload.auxiliarId],
        for_update=True,
    )


def _validate_lider_elegivel(
    db: Session,
    lider_id: uuid.UUID | None,
    *,
    exclude_celula_id: uuid.UUID | str | None = None,
    celula_ativa: bool = True,
) -> None:
    """Guards de elegibilidade do líder (regra 2026-07-06).

    Para ASSUMIR uma célula a pessoa precisa ser apta (Reencontro), não-CSIM e
    não liderar OUTRA célula ativa (a própria célula, em edição, é excluída).
    Editar mantendo o mesmo líder NÃO passa por aqui (grandfather — o call-site
    só valida troca/atribuição). Tenant já garantido por _assert_pessoa_tenant.
    """
    if lider_id is None:
        return
    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == lider_id)
    ).scalar_one_or_none()
    if pessoa is None:  # fail-closed (RLS já barrou outro tenant)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="liderId: pessoa não encontrada nesta igreja",
        )
    if bool(pessoa.sem_interesse):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="liderId: pessoa sem interesse (CSIM) não pode liderar célula",
        )
    if not bool(pessoa.apto_lider):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="liderId: pessoa ainda não fez o Reencontro (não apta a liderar)",
        )
    if not celula_ativa:
        # Célula inativa não torna ninguém "líder de célula" — sem conflito.
        return
    lideradas = db.execute(
        select(Celula).where(
            Celula.lider_id == lider_id, Celula.ativo.is_(True)
        )
    ).scalars().all()
    # Exclusão da própria célula em Python (não no SQL) — comparação por str
    # cobre UUID×str e mantém os fakes de teste (predicados eq) fiéis.
    conflito = any(
        exclude_celula_id is None or str(c.id) != str(exclude_celula_id)
        for c in lideradas
    )
    if conflito:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="liderId: pessoa já lidera uma célula ativa",
        )


def _sensitive_payload(payload: UpsertCellRequest) -> dict[str, object | None]:
    """Campos sensíveis (3.2) do payload, mapeados para os atributos do modelo."""
    return {
        "dia_reuniao": payload.diaReuniao,
        "horario": payload.horario,
        "endereco": payload.endereco,
        "anfitriao_id": _to_uuid(payload.anfitriaoId),
        "auxiliar_id": _to_uuid(payload.auxiliarId),
    }


def _sensitive_changed(payload: UpsertCellRequest, cell: Celula) -> bool:
    """True se o payload muda algum campo sensível em relação ao valor atual."""
    return any(
        getattr(cell, attr) != value
        for attr, value in _sensitive_payload(payload).items()
    )


def _has_sensitive(payload: UpsertCellRequest) -> bool:
    """True se o payload traz QUALQUER campo sensível preenchido (não-None)."""
    return any(value is not None for value in _sensitive_payload(payload).values())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/cells", response_model=Page[CellOut])
def list_cells(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[CellOut]:
    """List the tenant's cells, paginated."""
    total = db.execute(select(func.count()).select_from(Celula)).scalar_one()
    rows = db.execute(
        select(Celula)
        .order_by(Celula.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()
    return Page[CellOut](
        items=[CellOut.from_model(c) for c in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.get("/cells/{cell_id}", response_model=CellDetailOut)
def get_cell(
    cell_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellDetailOut:
    """Return a cell with its open alerts."""
    cell = _get_cell_or_404(db, cell_id)

    alerts = db.execute(
        select(CellAlert)
        .where(CellAlert.celula_id == cell.id, CellAlert.tratado.is_(False))
        .order_by(CellAlert.created_at.desc())
    ).scalars().all()

    detail = CellDetailOut.from_model(cell)
    detail.alerts = [AlertOut.from_model(a) for a in alerts]
    return detail


@router.post("/cells", response_model=CellOut)
def upsert_cell(
    payload: UpsertCellRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CellOut:
    """Create a new cell or edit an existing one.

    cobertura_espiritual is mandatory (validated at the edge). Editing requires
    leader-or-superior authorization (delta-007); creating requires a pastoral
    leadership role.
    """

    if payload.id is None:
        if not current_user.has_any_role(CELL_CREATE_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para criar células",
            )
        # Decisão 3.2 (fechada pelo dono): campos sensíveis são da Central. Um
        # criador não-Central (ex.: lider_g12) só cria com dados leves; enviar
        # sensível na criação = 403 (não pode burlar o guard pela criação).
        if not current_user.has_any_role(CENTRAL_ROLES) and _has_sensitive(payload):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Apenas a Central de Células pode definir campos sensíveis "
                    "(dia, horário, endereço, anfitrião, auxiliar) ao criar a célula."
                ),
            )
        _validate_pessoa_refs(db, payload)
        _assert_referenced_pessoas_nao_arquivadas(db, current_user, payload)
        _validate_lider_elegivel(
            db, _to_uuid(payload.liderId), celula_ativa=payload.ativo
        )
        cell = Celula(
            igreja_id=uuid.UUID(current_user.igreja_id),
            nome=payload.nome,
            lider_id=_to_uuid(payload.liderId),
            cobertura_espiritual=payload.coberturaEspiritual,
            dia_reuniao=payload.diaReuniao,
            horario=payload.horario,
            endereco=payload.endereco,
            anfitriao_id=_to_uuid(payload.anfitriaoId),
            auxiliar_id=_to_uuid(payload.auxiliarId),
            link_grupo=payload.linkGrupo,
            link_localizacao=payload.linkLocalizacao,
            mensagem_convite=payload.mensagemConvite,
            ativo=payload.ativo,
        )
        db.add(cell)
        db.flush()
        db.refresh(cell)
        db.commit()
        return CellOut.from_model(cell)

    # Edit path.
    cell = _get_cell_or_404(db, payload.id)
    if not _can_edit_cell(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o líder da célula ou um superior pode editá-la",
        )
    _validate_pessoa_refs(db, payload)
    _assert_referenced_pessoas_nao_arquivadas(db, current_user, payload)
    # Elegibilidade (2026-07-06) só na TROCA/atribuição de líder: reenviar o
    # mesmo líder passa (grandfather); remover líder (None) também.
    novo_lider = _to_uuid(payload.liderId)
    if novo_lider is not None and str(novo_lider) != str(cell.lider_id):
        _validate_lider_elegivel(
            db, novo_lider, exclude_celula_id=cell.id, celula_ativa=payload.ativo
        )
    # Decisão 3.2: campos sensíveis só a Central altera direto; o líder solicita
    # (Solicitação chega no PR5). Um editor não-Central que tenta mudar sensível
    # é barrado (403); reenviar os mesmos valores (edição só de leves) passa.
    if not current_user.has_any_role(CENTRAL_ROLES) and _sensitive_changed(
        payload, cell
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Campos sensíveis (dia, horário, endereço, anfitrião, auxiliar) "
                "só a Central de Células altera. Solicite a alteração."
            ),
        )
    # Leves — sempre aplicados por quem pode editar.
    cell.nome = payload.nome
    cell.lider_id = _to_uuid(payload.liderId)
    cell.cobertura_espiritual = payload.coberturaEspiritual
    cell.link_grupo = payload.linkGrupo
    cell.link_localizacao = payload.linkLocalizacao
    cell.mensagem_convite = payload.mensagemConvite
    cell.ativo = payload.ativo
    # Sensíveis — aplicação incondicional: um não-Central só chegou aqui se os
    # valores são idênticos aos atuais (no-op); a Central aplica a mudança.
    cell.dia_reuniao = payload.diaReuniao
    cell.horario = payload.horario
    cell.endereco = payload.endereco
    cell.anfitriao_id = _to_uuid(payload.anfitriaoId)
    cell.auxiliar_id = _to_uuid(payload.auxiliarId)
    db.flush()
    db.refresh(cell)
    db.commit()
    return CellOut.from_model(cell)


@router.post("/cells/{cell_id}/alerts/{alert_id}/baixar", response_model=AlertOut)
def baixar_alert(
    cell_id: str,
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AlertOut:
    """Mark a cell alert as handled (tratado=true)."""
    cell = _get_cell_or_404(db, cell_id)
    if not _can_edit_cell(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissão para tratar alertas desta célula",
        )

    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado"
        ) from exc

    alert = db.execute(
        select(CellAlert).where(
            CellAlert.id == alert_uuid, CellAlert.celula_id == cell.id
        )
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado"
        )

    alert.tratado = True
    db.flush()
    db.refresh(alert)
    db.commit()
    return AlertOut.from_model(alert)


@router.get("/cells/{cell_id}/membros", response_model=list[MemberOut])
def list_cell_members(
    cell_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> list[MemberOut]:
    """Membros ativos da célula (vínculo canônico `celula_membro`, Q1).

    Superfície ADMINISTRATIVA da Central: só pastor + admin (require_central).
    Um membro/discípulo comum do mesmo tenant recebe 403 — não pode enumerar os
    vínculos de uma célula arbitrária pelo UUID. A leitura pelo LÍDER da própria
    célula permanece no endpoint distinto GET /cells/{id}/members (inalterado).
    """
    cell = _get_cell_or_404(db, cell_id)
    # igreja_id explícito (defesa em profundidade além da RLS; e torna o
    # isolamento por tenant testável no harness fake).
    rows = db.execute(
        select(CelulaMembro)
        .where(
            CelulaMembro.celula_id == cell.id,
            CelulaMembro.igreja_id == uuid.UUID(current_user.igreja_id),
            CelulaMembro.ativo.is_(True),
        )
        .order_by(CelulaMembro.created_at.asc())
    ).scalars().all()
    return [MemberOut.from_model(m) for m in rows]


@router.post(
    "/cells/{cell_id}/membros",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_cell_member(
    cell_id: str,
    payload: AddMemberRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> MemberOut:
    """Entrada direta de membro (decisão 3.2 — sem Solicitação).

    Autorização = poder editar a célula (líder-ou-superior/pastor/admin). Regra
    "1 pessoa → 1 célula ativa": 409 se a pessoa já tem vínculo ativo. Mantém
    `pessoas.celula_id` como espelho legado (Q1); a saída de membro é PR5.
    """
    cell = _get_cell_or_404(db, cell_id)
    # Paridade com POST /contacts/{id}/cell: célula precisa estar ativa e ter
    # líder (achado C-03), verificado antes da permissão de edição.
    if not cell.ativo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Célula inativa não pode receber membros",
        )
    if cell.lider_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Célula sem líder não pode receber membros",
        )
    if not _can_edit_cell(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissão para adicionar membros a esta célula",
        )

    pessoa_uuid = uuid.UUID(payload.pessoaId)
    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_uuid)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    # Líder de célula ativa não é candidato a MEMBRO (achado C-01).
    if _leads_active_cell(db, pessoa_uuid, uuid.UUID(current_user.igreja_id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Esta pessoa já lidera uma célula ativa e não pode ser "
                "adicionada como membro."
            ),
        )

    # Missão M7B-W1.2: guarda COMPARTILHADA de elegibilidade — recusa pastor,
    # líder da própria célula e o número conectado ao WhatsApp. Este endpoint
    # escreve celula_membro direto (não pelo seam ensure_active_membro), então
    # chama a MESMA função-guarda; MembroInelegivelError vira 409 no handler
    # global (app.main). Concentra a regra num único ponto, não espalhada.
    assert_membro_elegivel(
        db,
        igreja_id=uuid.UUID(current_user.igreja_id),
        celula=cell,
        pessoa=pessoa,
    )

    # D2: espelho legado (pessoas.celula_id) apontando pra OUTRA célula = a
    # pessoa já pertence àquela célula, mesmo sem linha canônica ativa (dado
    # pré-C-02). A entrada direta NÃO é transferência — nem para admin, que
    # deve usar o fluxo explícito — então recusa com o MESMO 409 antes de
    # qualquer escrita. Espelho apontando pra ESTA célula segue adiante: o
    # vínculo canônico ausente é reparado (201).
    if pessoa.celula_id is not None and str(pessoa.celula_id) != str(cell.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "member_already_active",
                "message": "Pessoa já está em uma célula ativa",
            },
        )

    # Regra "1 pessoa → 1 célula ativa" escopada por igreja (igual ao índice
    # único parcial da migration). igreja_id explícito também torna testável.
    existing = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.pessoa_id == pessoa_uuid,
            CelulaMembro.igreja_id == uuid.UUID(current_user.igreja_id),
            CelulaMembro.ativo.is_(True),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "member_already_active",
                "message": "Pessoa já está em uma célula ativa",
            },
        )

    membro = CelulaMembro(
        igreja_id=uuid.UUID(current_user.igreja_id),
        celula_id=cell.id,
        pessoa_id=pessoa_uuid,
        papel=payload.papel,
        ativo=True,
    )
    db.add(membro)
    pessoa.celula_id = cell.id  # espelho legado (Q1)
    promote_tipo_para_membro(pessoa)  # invariante: vínculo ativo ⇒ tipo ≥ membro
    try:
        db.flush()
        db.refresh(membro)
        db.commit()
    except IntegrityError as exc:
        # Corrida com o índice único parcial (igreja_id, pessoa_id) WHERE ativo:
        # o pré-check passou, mas outra requisição inseriu antes. Mapeia para o
        # mesmo 409 em vez de vazar 500.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "member_already_active",
                "message": "Pessoa já está em uma célula ativa",
            },
        ) from exc
    return MemberOut.from_model(membro)


@router.get("/descendencias", response_model=list[TreeNode])
def descendencias(
    root_id: str | None = Query(default=None, alias="rootId"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[TreeNode]:
    """Return the leadership tree built from pessoas.lider_id.

    By default the tree is rooted at the acting user's linked person (their
    downline). An explicit ?rootId= overrides it. When no root can be resolved,
    the full forest (people with no leader) is returned.
    """

    rows = db.execute(
        select(Pessoa.id, Pessoa.nome, Pessoa.tipo, Pessoa.lider_id)
    ).all()

    # node lookup and parent -> children adjacency.
    info: dict[str, tuple[str, str | None]] = {}
    children: dict[str | None, list[str]] = {}
    for pid, nome, tipo, lider_id in rows:
        spid = str(pid)
        info[spid] = (nome, tipo)
        key = str(lider_id) if lider_id else None
        children.setdefault(key, []).append(spid)

    def build(node_id: str) -> TreeNode:
        nome, tipo = info[node_id]
        return TreeNode(
            id=node_id,
            nome=nome,
            tipo=tipo,
            children=[build(cid) for cid in children.get(node_id, [])],
        )

    resolved_root = root_id or _actor_pessoa_id(db, current_user)
    if resolved_root:
        return [build(resolved_root)] if resolved_root in info else []

    # No root: return the forest of top-level people (lider_id is null).
    return [build(pid) for pid in children.get(None, [])]


def _get_cell_or_404(db: Session, cell_id: str) -> Celula:
    try:
        cell_uuid = uuid.UUID(cell_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        ) from exc
    cell = db.execute(
        select(Celula).where(Celula.id == cell_uuid)
    ).scalar_one_or_none()
    if cell is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        )
    return cell

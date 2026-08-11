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
from sqlalchemy import false, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, CelulaMembro, CellAlert, Pessoa
from app.db.session import get_db
from app.deps import CENTRAL_ROLES, CurrentUser, get_current_user, require_central
from app.domain.hierarchy import is_leader_or_superior
from app.routers._common import Page, PaginationParams
from app.services.celula_membro import (
    assert_pessoas_nao_arquivadas,
    ensure_active_membro,
)
from app.services.cell_leadership import set_cell_leadership

logger = logging.getLogger("pastorai.cells")

router = APIRouter(tags=["cells"])

# Roles with tenant-wide read access (admin passes implicitly).
CELL_TENANT_WIDE_READ_ROLES = [
    "pastor",
    "lider_g12",
]
# Roles with tenant-wide access to the G12 leadership forest (admin implicit).
DESCENDENCIAS_TENANT_WIDE_ROLES = ["pastor", "lider_g12"]
# Roles treated as superior to any cell leader for edit authorization.
CELL_EDIT_SUPERIOR_ROLES = ["pastor"]
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


def _cell_read_scope_filters(
    db: Session, current_user: CurrentUser
) -> list:
    """Predicates shared by cell list/count/detail reads.

    Wide accumulated roles retain the tenant-wide RLS view. Restricted roles
    fail closed and carry explicit tenant predicates as defense in depth.
    """

    if current_user.has_any_role(CELL_TENANT_WIDE_READ_ROLES):
        return []

    actor_pessoa_id = _actor_pessoa_id(db, current_user)
    if actor_pessoa_id is None:
        return [false()]

    igreja_id = uuid.UUID(current_user.igreja_id)
    actor_id = uuid.UUID(actor_pessoa_id)

    if "lider_celula" in current_user.roles:
        return [
            Celula.igreja_id == igreja_id,
            Celula.lider_id == actor_id,
        ]

    celulas_do_membro = select(CelulaMembro.celula_id).where(
        CelulaMembro.igreja_id == igreja_id,
        CelulaMembro.pessoa_id == actor_id,
        CelulaMembro.ativo.is_(True),
    )
    return [
        Celula.igreja_id == igreja_id,
        Celula.ativo.is_(True),
        Celula.id.in_(celulas_do_membro),
    ]


def _can_view_cell_alerts(
    db: Session, current_user: CurrentUser, cell: Celula
) -> bool:
    """Allow pastoral alert details only to pastors/admins or the cell leader."""
    if current_user.has_any_role(["pastor"]):
        return True

    actor_pessoa_id = _actor_pessoa_id(db, current_user)
    return (
        actor_pessoa_id is not None
        and cell.lider_id is not None
        and str(cell.lider_id) == actor_pessoa_id
    )


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


def _sensitive_payload(payload: UpsertCellRequest) -> dict[str, object | None]:
    """Campos sensíveis explicitamente enviados, mapeados para o modelo.

    O endpoint histórico é um upsert, mas a tela de resumo não possui todos os
    campos ricos. No caminho de edição, ausência significa preservar; ``null``
    explícito continua significando limpar.
    """

    values = {
        "diaReuniao": ("dia_reuniao", payload.diaReuniao),
        "horario": ("horario", payload.horario),
        "endereco": ("endereco", payload.endereco),
        "anfitriaoId": ("anfitriao_id", _to_uuid(payload.anfitriaoId)),
        "auxiliarId": ("auxiliar_id", _to_uuid(payload.auxiliarId)),
    }
    return {
        attribute: value
        for field, (attribute, value) in values.items()
        if field in payload.model_fields_set
    }


def _sensitive_changed(payload: UpsertCellRequest, cell: Celula) -> bool:
    """True se o payload muda algum campo sensível em relação ao valor atual."""
    return any(
        getattr(cell, attr) != value
        for attr, value in _sensitive_payload(payload).items()
    )


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
    scope_filters = _cell_read_scope_filters(db, current_user)
    total = db.execute(
        select(func.count()).select_from(Celula).where(*scope_filters)
    ).scalar_one()
    rows = db.execute(
        select(Celula)
        .where(*scope_filters)
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
    cell = _get_cell_or_404(
        db,
        cell_id,
        scope_filters=_cell_read_scope_filters(db, current_user),
    )

    detail = CellDetailOut.from_model(cell)
    if not _can_view_cell_alerts(db, current_user, cell):
        return detail

    alerts = db.execute(
        select(CellAlert)
        .where(CellAlert.celula_id == cell.id, CellAlert.tratado.is_(False))
        .order_by(CellAlert.created_at.desc())
    ).scalars().all()

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
        if not current_user.has_any_role(CENTRAL_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas a Central de Células pode cadastrar células",
            )
        _validate_pessoa_refs(db, payload)
        _assert_referenced_pessoas_nao_arquivadas(db, current_user, payload)
        cell = Celula(
            igreja_id=uuid.UUID(current_user.igreja_id),
            nome=payload.nome,
            # Liderança/estado são aplicados pelo serviço derivado abaixo.
            lider_id=None,
            cobertura_espiritual=payload.coberturaEspiritual,
            dia_reuniao=payload.diaReuniao,
            horario=payload.horario,
            endereco=payload.endereco,
            anfitriao_id=_to_uuid(payload.anfitriaoId),
            auxiliar_id=_to_uuid(payload.auxiliarId),
            link_grupo=payload.linkGrupo,
            link_localizacao=payload.linkLocalizacao,
            mensagem_convite=payload.mensagemConvite,
            ativo=False,
        )
        try:
            set_cell_leadership(
                db,
                igreja_id=uuid.UUID(current_user.igreja_id),
                cell=cell,
                new_leader_id=_to_uuid(payload.liderId),
                new_active=payload.ativo,
            )
            db.add(cell)
            db.flush()
            db.refresh(cell)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return CellOut.from_model(cell)

    # Edit path.
    # Serializa trocas/desativação da MESMA célula antes de observar o líder
    # anterior. Sem esta trava, A->B e A->C concorrentes poderiam deixar o papel
    # de B órfão mesmo que C fosse a última gravação.
    cell = _get_cell_or_404(db, payload.id, for_update=True)
    if not _can_edit_cell(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o líder da célula ou um superior pode editá-la",
        )
    # O endpoint é upsert e aceita payload parcial em integrações legadas. Campo
    # omitido não significa remover líder/ativar; a Central precisa enviá-lo
    # explicitamente para mudar o estado.
    novo_lider = (
        _to_uuid(payload.liderId)
        if "liderId" in payload.model_fields_set
        else cell.lider_id
    )
    novo_ativo = (
        payload.ativo if "ativo" in payload.model_fields_set else bool(cell.ativo)
    )
    leadership_changed = str(novo_lider) != str(cell.lider_id)
    active_changed = bool(novo_ativo) != bool(cell.ativo)
    if not current_user.has_any_role(CENTRAL_ROLES) and (
        leadership_changed or active_changed
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas a Central de Células altera liderança ou ativação",
        )
    _validate_pessoa_refs(db, payload)
    _assert_referenced_pessoas_nao_arquivadas(db, current_user, payload)
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
    try:
        set_cell_leadership(
            db,
            igreja_id=uuid.UUID(current_user.igreja_id),
            cell=cell,
            new_leader_id=novo_lider,
            new_active=novo_ativo,
        )
        # Obrigatórios — sempre presentes por contrato.
        cell.nome = payload.nome
        cell.cobertura_espiritual = payload.coberturaEspiritual
        # Opcionais seguem semântica PATCH no caminho edit: omitir preserva e
        # enviar null limpa. Isso evita apagar dados ricos quando uma superfície
        # resumida envia apenas os campos que conhece.
        if "linkGrupo" in payload.model_fields_set:
            cell.link_grupo = payload.linkGrupo
        if "linkLocalizacao" in payload.model_fields_set:
            cell.link_localizacao = payload.linkLocalizacao
        if "mensagemConvite" in payload.model_fields_set:
            cell.mensagem_convite = payload.mensagemConvite
        for attribute, value in _sensitive_payload(payload).items():
            setattr(cell, attribute, value)
        db.flush()
        db.refresh(cell)
        db.commit()
    except Exception:
        db.rollback()
        raise
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
    current_user: CurrentUser = Depends(require_central),
) -> MemberOut:
    """Entrada direta de membro (decisão 3.2 — sem Solicitação).

    Autorização = Central (pastor/admin). Regra
    "1 pessoa → 1 célula ativa": 409 se a pessoa já tem vínculo ativo. Mantém
    `pessoas.celula_id` como espelho legado (Q1); a saída de membro é PR5.
    """
    cell = _get_cell_or_404(db, cell_id)
    # Resposta rápida preservada; o seam canônico relê e trava célula + pessoa
    # antes de qualquer escrita, fechando desativação/troca concorrente.
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
    pessoa_uuid = uuid.UUID(payload.pessoaId)
    pessoa = db.execute(
        select(Pessoa).where(
            Pessoa.id == pessoa_uuid,
            Pessoa.igreja_id == uuid.UUID(current_user.igreja_id),
        )
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada"
        )

    membro = ensure_active_membro(
        db,
        igreja_id=uuid.UUID(current_user.igreja_id),
        celula_id=uuid.UUID(str(cell.id)),
        pessoa_id=pessoa_uuid,
        papel=payload.papel,
        reject_existing_active=True,
    )
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
    """Return the tenant-scoped leadership tree built from pessoas.lider_id."""

    wide_scope = current_user.has_any_role(DESCENDENCIAS_TENANT_WIDE_ROLES)
    actor_pessoa_id: str | None = None
    normalized_root: str | None = None

    if root_id is not None:
        try:
            normalized_root = str(uuid.UUID(root_id))
        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Raiz não encontrada",
            ) from exc

    if not wide_scope:
        actor_pessoa_id = _actor_pessoa_id(db, current_user)
        if actor_pessoa_id is None:
            if root_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Raiz não encontrada",
                )
            return []

        actor_pessoa_id = str(uuid.UUID(actor_pessoa_id))
        if normalized_root is not None and normalized_root != actor_pessoa_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Raiz não encontrada",
            )
        normalized_root = actor_pessoa_id

    igreja_id = uuid.UUID(current_user.igreja_id)
    rows = db.execute(
        select(Pessoa.id, Pessoa.nome, Pessoa.tipo, Pessoa.lider_id).where(
            Pessoa.igreja_id == igreja_id
        )
    ).all()

    # node lookup and parent -> children adjacency.
    info: dict[str, tuple[str, str | None]] = {}
    children: dict[str | None, list[str]] = {}
    for pid, nome, tipo, lider_id in rows:
        spid = str(pid)
        info[spid] = (nome, tipo)
        key = str(lider_id) if lider_id else None
        children.setdefault(key, []).append(spid)

    allow_descendants = wide_scope or bool(
        current_user.roles & {"lider_mult", "lider_celula"}
    )

    def build(node_id: str) -> TreeNode:
        nome, tipo = info[node_id]
        return TreeNode(
            id=node_id,
            nome=nome,
            tipo=tipo,
            children=(
                [build(cid) for cid in children.get(node_id, [])]
                if allow_descendants
                else []
            ),
        )

    if normalized_root is not None:
        if normalized_root not in info:
            if root_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Raiz não encontrada",
                )
            return []
        return [build(normalized_root)]

    # Only broad roles reach this branch: tenant-wide forest roots.
    return [build(pid) for pid in children.get(None, [])]


def _get_cell_or_404(
    db: Session,
    cell_id: str,
    *,
    scope_filters: list | None = None,
    for_update: bool = False,
) -> Celula:
    try:
        cell_uuid = uuid.UUID(cell_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        ) from exc
    statement = (
        select(Celula)
        .where(Celula.id == cell_uuid, *(scope_filters or []))
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    cell = db.execute(statement).scalar_one_or_none()
    if cell is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
        )
    return cell

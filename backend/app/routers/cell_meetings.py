"""Cell meetings router — reuniões de célula (Células PR2 / Domínio A).

Router PRÓPRIO (BK-DEC-01) que REUSA os helpers de `cells.py` — não duplica a
lógica de lookup/hierarquia nem engorda aquele arquivo. Contrato externo em
camelCase.

Endpoints:
  - GET  /cells/{cellId}/reunioes        lista reuniões do tenant (sem paginação)
  - POST /cells/{cellId}/reunioes/next   materializa a próxima reunião (idempotente)

A materialização é determinista: parte de `celulas.dia_reuniao` + `celulas.horario`
(422 se qualquer um faltar), calcula a próxima data em ``America/Sao_Paulo`` e
cria a reunião em status ``planejada`` — ou devolve a existente do mesmo slot
(UNIQUE ``igreja_id, celula_id, data, coalesce(hora,'')``). No PR2 não há
transição de status: a reunião nasce ``planejada`` e fica.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import nulls_last, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Celula,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
    CelulaReuniaoRegistro,
    CelulaVisitante,
    Pessoa,
)
from app.db.session import get_db
from app.deps import (
    CENTRAL_ROLES,
    CurrentUser,
    get_current_cell_for_leader,
    get_current_user,
    resolve_actor_pessoa_id,
)
from app.domain.cell_meetings_schedule import InvalidDiaReuniao, next_meeting_date
from app.domain.hierarchy import is_leader_or_superior

# Reuso dos helpers de cells.py (BK-DEC-01) — não reimplementar aqui.
from app.routers.cells import (
    _actor_pessoa_id,
    _assert_pessoa_tenant,
    _get_cell_or_404,
    _lider_of_map,
)

logger = logging.getLogger("pastorai.cell_meetings")

router = APIRouter(tags=["cell-meetings"])

# Constantes de estado no estilo de events.py (strings do enum/CHECK do DB).
# STATUS_* pertence a celula_reuniao; ESTADO_/ORIGEM_ a celula_presenca (Domínio
# B). Centralizados aqui para o módulo inteiro de reuniões/presença do PR2.
STATUS_PLANEJADA = "planejada"
ESTADO_CONFIRMADA = "confirmada"
ORIGEM_AUTO = "auto"
ORIGEM_LIDER = "lider"

# pastor/admin (admin implícito em has_any_role) OU Central materializam sempre.
# CENTRAL_ROLES já é ["pastor"]; mantido explícito para espelhar a regra da SPEC.
_MATERIALIZE_ROLES = ["pastor"]

# ---------------------------------------------------------------------------
# Domínio Líder (Minha Célula) + ciclo do relatório (Células PR3-PR9)
# ---------------------------------------------------------------------------
# Ciclo do relatório: nasce 'pendente' e vira 'enviado' no submit (E10/E11).
RELATORIO_PENDENTE = "pendente"
RELATORIO_ENVIADO = "enviado"
# Presença real marcada pelo líder (celula_presenca.estado). 'confirmada' é do PR2
# (auto-serviço do discípulo); a presença real do líder é compareceu/ausente.
ESTADO_COMPARECEU = "compareceu"
ESTADO_AUSENTE = "ausente"
# Tipos válidos de registro pastoral (celula_reuniao_registro.tipo).
RECORD_TIPOS = ("decisao", "oracao", "observacao")
# Limites de campos textuais (SPEC §6.1 / E1).
_TEMA_MAX = 120
_NOME_VISITANTE_MAX = 120
_CONTEUDO_MAX = 2000
_OBSERVACOES_MAX = 2000
# Valor da oferta (SPEC §6.2 / E2): 0 <= oferta_valor <= 999999.99.
_OFERTA_MIN = 0
_OFERTA_MAX = 999999.99
# HH:MM (24h) — espelha o CHECK de celula_reuniao/celulas.horario.
_HORA_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


# ---------------------------------------------------------------------------
# Validadores reutilizáveis de borda (E1/E2) — chamados dos field_validator.
# ---------------------------------------------------------------------------
def _validate_uuid_str(value: str, field: str) -> str:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} inválido") from exc
    return value


def _norm_optional_hora(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _HORA_RE.match(value):
        raise ValueError("hora deve estar no formato HH:MM")
    return value


def _norm_optional_text(value: str | None, max_len: int, field: str) -> str | None:
    """Opcional: trim; vazio/só-espaços → None; excede max → 422."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > max_len:
        raise ValueError(f"{field} deve ter no máximo {max_len} caracteres")
    return value


def _require_text(value: str, max_len: int, field: str) -> str:
    """Obrigatório: trim; vazio/só-espaços → 422; excede max → 422."""
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError(f"{field} é obrigatório")
    if len(trimmed) > max_len:
        raise ValueError(f"{field} deve ter no máximo {max_len} caracteres")
    return trimmed


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ReuniaoOut(BaseModel):
    """Contrato externo camelCase de uma reunião de célula."""

    id: str
    celulaId: str  # noqa: N815
    data: str  # YYYY-MM-DD
    hora: str | None = None  # HH:MM
    tema: str | None = None
    status: str

    @classmethod
    def from_model(cls, r: CelulaReuniao) -> "ReuniaoOut":
        return cls(
            id=str(r.id),
            celulaId=str(r.celula_id),
            data=r.data.isoformat(),
            hora=r.hora,
            tema=r.tema,
            status=r.status,
        )


class PresencaOut(BaseModel):
    """Contrato externo camelCase de uma presença em reunião de célula."""

    id: str
    reuniaoId: str  # noqa: N815
    pessoaId: str  # noqa: N815
    estado: str
    origem: str | None = None

    @classmethod
    def from_model(cls, p: CelulaPresenca) -> "PresencaOut":
        return cls(
            id=str(p.id),
            reuniaoId=str(p.reuniao_id),
            pessoaId=str(p.pessoa_id),
            estado=p.estado,
            origem=p.origem,
        )


class MarkPresencaRequest(BaseModel):
    """Marcar presença: sem `pessoaId` = auto-confirmação; com = terceiro."""

    pessoaId: str | None = None  # noqa: N815

    @field_validator("pessoaId")
    @classmethod
    def _pessoa_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("pessoaId inválido") from exc
        return value


class RegisterExpectativaRequest(BaseModel):
    """Registrar expectativa nominal de visitante (Domínio C).

    Validação de borda no Pydantic (RF-17/E13): `nomeVisitante` é obrigatório e,
    após trim, precisa ter 1..200 chars — string vazia ou só-espaços é rejeitada
    (422). `observacaoOracao` é opcional e, após trim, no máximo 500 chars;
    vazio/só-espaços vira None.
    """

    nomeVisitante: str  # noqa: N815
    observacaoOracao: str | None = None  # noqa: N815

    @field_validator("nomeVisitante")
    @classmethod
    def _validate_nome(cls, value: str) -> str:
        trimmed = (value or "").strip()
        if not trimmed:
            raise ValueError("nomeVisitante é obrigatório")
        if len(trimmed) > 200:
            raise ValueError("nomeVisitante deve ter no máximo 200 caracteres")
        return trimmed

    @field_validator("observacaoOracao")
    @classmethod
    def _validate_observacao(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if len(trimmed) > 500:
            raise ValueError("observacaoOracao deve ter no máximo 500 caracteres")
        return trimmed


class ExpectativaVisitanteOut(BaseModel):
    """Contrato externo camelCase de uma expectativa de visitante."""

    id: str
    reuniaoId: str  # noqa: N815
    pessoaId: str  # noqa: N815
    nomeVisitante: str  # noqa: N815
    observacaoOracao: str | None = None  # noqa: N815

    @classmethod
    def from_model(
        cls, e: CelulaExpectativaVisitante
    ) -> "ExpectativaVisitanteOut":
        return cls(
            id=str(e.id),
            reuniaoId=str(e.reuniao_id),
            pessoaId=str(e.pessoa_id),
            nomeVisitante=e.nome_visitante,
            observacaoOracao=e.observacao_oracao,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _can_materialize(db: Session, current_user: CurrentUser, cell: Celula) -> bool:
    """pastor/admin OU Central OU líder-da-célula-ou-superior (SPEC Domínio A)."""
    if current_user.has_any_role(_MATERIALIZE_ROLES) or current_user.has_any_role(
        CENTRAL_ROLES
    ):
        return True
    actor = _actor_pessoa_id(db, current_user)
    return is_leader_or_superior(
        actor_pessoa_id=actor,
        cell_leader_id=str(cell.lider_id) if cell.lider_id else None,
        lider_of=_lider_of_map(db),
    )


def _find_slot(
    db: Session, igreja_id: uuid.UUID, celula_id: uuid.UUID, data, hora: str | None
) -> CelulaReuniao | None:
    """Reunião existente do mesmo slot (igreja, célula, data, hora) ou None."""
    return db.execute(
        select(CelulaReuniao).where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.celula_id == celula_id,
            CelulaReuniao.data == data,
            CelulaReuniao.hora == hora,
        )
    ).scalar_one_or_none()


def _get_reuniao_or_404(
    db: Session, reuniao_id: str, igreja_id: uuid.UUID
) -> CelulaReuniao:
    """Resolve a reunião por id escopada ao tenant (análogo a `_get_cell_or_404`).

    Não exige `cellId` no path (RF-07b): a reunião carrega `celula_id`/`igreja_id`.
    Filtro por `igreja_id` explícito além da RLS (defesa em profundidade) — uma
    reunião de outro tenant, ou um id malformado, resulta em 404.
    """
    try:
        reuniao_uuid = uuid.UUID(reuniao_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reunião não encontrada"
        ) from exc
    reuniao = db.execute(
        select(CelulaReuniao).where(
            CelulaReuniao.id == reuniao_uuid,
            CelulaReuniao.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()
    if reuniao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reunião não encontrada"
        )
    return reuniao


def _find_presenca(
    db: Session, igreja_id: uuid.UUID, reuniao_id: uuid.UUID, pessoa_id: uuid.UUID
) -> CelulaPresenca | None:
    """Presença existente de (igreja, reunião, pessoa) ou None (espelha o UNIQUE)."""
    return db.execute(
        select(CelulaPresenca).where(
            CelulaPresenca.igreja_id == igreja_id,
            CelulaPresenca.reuniao_id == reuniao_id,
            CelulaPresenca.pessoa_id == pessoa_id,
        )
    ).scalar_one_or_none()


def _has_active_membership(
    db: Session, igreja_id: uuid.UUID, celula_id: uuid.UUID, pessoa_id: uuid.UUID
) -> bool:
    """True se a pessoa tem vínculo ATIVO na célula DA REUNIÃO (E11).

    O índice único parcial `celula_membro_pessoa_ativa_uq` garante 1 pessoa → 1
    célula ativa; logo, uma pessoa ativa em OUTRA célula não tem vínculo válido
    aqui (o filtro por `celula_id` a exclui).
    """
    membro = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.celula_id == celula_id,
            CelulaMembro.ativo.is_(True),
        )
    ).scalar_one_or_none()
    return membro is not None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/cells/{cell_id}/reunioes", response_model=list[ReuniaoOut])
def list_reunioes(
    cell_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ReuniaoOut]:
    """Lista as reuniões da célula, escopadas ao tenant (sem paginação, BK-DEC-02).

    Aberto a qualquer autenticado do tenant (sem guard de vínculo/liderança).
    Filtro por `igreja_id` explícito além da RLS (defesa em profundidade).
    """
    cell = _get_cell_or_404(db, cell_id)
    rows = db.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.celula_id == cell.id,
            CelulaReuniao.igreja_id == uuid.UUID(current_user.igreja_id),
        )
        .order_by(
            CelulaReuniao.data.desc(),
            nulls_last(CelulaReuniao.hora.desc()),
            CelulaReuniao.id.desc(),
        )
    ).scalars().all()
    return [ReuniaoOut.from_model(r) for r in rows]


@router.post("/cells/{cell_id}/reunioes/next", response_model=ReuniaoOut)
def materialize_next_reuniao(
    cell_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ReuniaoOut:
    """Materializa a próxima reunião a partir de `dia_reuniao`/`horario` da célula.

    Idempotente: cria em ``planejada`` se não existir, ou devolve a existente do
    mesmo slot — sempre 200. Autorização = pastor/admin OU Central OU
    líder-da-célula-ou-superior; membro comum recebe 403. Retorna 422 se
    `dia_reuniao` faltar/for irreconhecível ou se `horario` for NULL, sem criar
    nenhuma linha.
    """
    cell = _get_cell_or_404(db, cell_id)

    if not _can_materialize(db, current_user, cell):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissão para materializar reuniões desta célula",
        )

    # Validação determinista antes de qualquer escrita.
    try:
        data = next_meeting_date(dia_reuniao=cell.dia_reuniao, hora=cell.horario)
    except InvalidDiaReuniao as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="dia_reuniao ausente ou não reconhecido; defina o dia da célula",
        ) from exc

    hora = (cell.horario or "").strip() or None
    if hora is None:
        # A materialização SEMPRE nasce com hora preenchida (nunca cria sem hora).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="horario da célula não definido; defina o horário para materializar",
        )

    igreja_id = uuid.UUID(current_user.igreja_id)

    # Pré-check: slot já materializado? (idempotência no caminho feliz.)
    existing = _find_slot(db, igreja_id, cell.id, data, hora)
    if existing is not None:
        return ReuniaoOut.from_model(existing)

    reuniao = CelulaReuniao(
        igreja_id=igreja_id,
        celula_id=cell.id,
        data=data,
        hora=hora,
        status=STATUS_PLANEJADA,
    )
    db.add(reuniao)
    try:
        db.flush()
        db.refresh(reuniao)
        db.commit()
    except IntegrityError as exc:
        # Corrida no UNIQUE (igreja_id, celula_id, data, coalesce(hora,'')): outra
        # requisição materializou o mesmo slot entre o pré-check e o INSERT.
        # Recupera a linha existente e devolve 200 — nunca 409/500 nem duplicata.
        db.rollback()
        recovered = _find_slot(db, igreja_id, cell.id, data, hora)
        if recovered is None:
            logger.error(
                "IntegrityError ao materializar reunião sem linha recuperável "
                "(celula=%s data=%s)",
                cell.id,
                data,
            )
            raise
        return ReuniaoOut.from_model(recovered)

    return ReuniaoOut.from_model(reuniao)


@router.post(
    "/cell-reunioes/{reuniao_id}/presenca", response_model=PresencaOut
)
def mark_presenca(
    reuniao_id: str,
    payload: MarkPresencaRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> PresencaOut:
    """Confirma presença numa reunião — própria (auto) ou de terceiro (por líder).

    Regras (Domínio B):
      - Sem `pessoaId` (ou igual à própria pessoa): auto-confirmação do app_user;
        `estado='confirmada'`, `origem='auto'`. app_user sem pessoa → 403
        (SEC-DEC-04).
      - Com `pessoaId` de outra pessoa: exige líder-da-célula-ou-superior /
        pastor / admin / Central; `origem='lider'`. Membro comum → 403. A pessoa
        alvo tem de existir no tenant (senão 422).
      - A pessoa alvo precisa de vínculo ATIVO na célula DA REUNIÃO (E11); sem
        vínculo válido → 403.
      - O status da reunião NÃO é validado (E12): presença é permitida em
        qualquer status.
      - Idempotência last-write-wins (BK-DEC-04 opção A): pré-check SELECT →
        INSERT ou UPDATE; corrida contra o UNIQUE → IntegrityError → rollback →
        recupera. SEMPRE 200 (nunca 409/500).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)

    actor_pessoa = _actor_pessoa_id(db, current_user)
    is_auto = payload.pessoaId is None or (
        actor_pessoa is not None and payload.pessoaId == actor_pessoa
    )

    if is_auto:
        # Auto-confirmação: o app_user precisa ter uma pessoa vinculada (SEC-DEC-04).
        if actor_pessoa is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu usuário não está vinculado a uma pessoa",
            )
        target_uuid = uuid.UUID(actor_pessoa)
        origem = ORIGEM_AUTO
    else:
        # Marcar terceiro exige liderança da célula-ou-superior / pastor / admin /
        # Central (mesma regra da materialização). Membro comum → 403.
        cell = _get_cell_or_404(db, str(reuniao.celula_id))
        if not _can_materialize(db, current_user, cell):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sem permissão para marcar a presença de outra pessoa",
            )
        target_uuid = uuid.UUID(payload.pessoaId)  # type: ignore[arg-type]
        # Isolamento por tenant: pessoa de outra igreja → 422 (a FK não é RLS).
        _assert_pessoa_tenant(db, target_uuid, "pessoaId")
        origem = ORIGEM_LIDER

    # E11: vínculo ativo obrigatório na célula DA REUNIÃO (não vale outra célula).
    if not _has_active_membership(db, igreja_id, reuniao.celula_id, target_uuid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pessoa sem vínculo ativo na célula desta reunião",
        )

    # Upsert idempotente (last-write-wins). No PR2 o estado gravado é SEMPRE
    # 'confirmada'.
    existing = _find_presenca(db, igreja_id, reuniao.id, target_uuid)
    if existing is not None:
        existing.estado = ESTADO_CONFIRMADA
        existing.origem = origem
        existing.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        db.refresh(existing)
        db.commit()
        return PresencaOut.from_model(existing)

    presenca = CelulaPresenca(
        igreja_id=igreja_id,
        reuniao_id=reuniao.id,
        pessoa_id=target_uuid,
        estado=ESTADO_CONFIRMADA,
        origem=origem,
    )
    db.add(presenca)
    try:
        db.flush()
        db.refresh(presenca)
        db.commit()
    except IntegrityError:
        # Corrida no UNIQUE (igreja_id, reuniao_id, pessoa_id): outra requisição
        # gravou entre o pré-check e o INSERT. Recupera e aplica last-write-wins;
        # devolve 200 — NUNCA 409/500 (409 é reservado a add_cell_member).
        db.rollback()
        recovered = _find_presenca(db, igreja_id, reuniao.id, target_uuid)
        if recovered is None:
            logger.error(
                "IntegrityError ao marcar presença sem linha recuperável "
                "(reuniao=%s pessoa=%s)",
                reuniao.id,
                target_uuid,
            )
            raise
        recovered.estado = ESTADO_CONFIRMADA
        recovered.origem = origem
        recovered.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        db.refresh(recovered)
        db.commit()
        return PresencaOut.from_model(recovered)

    return PresencaOut.from_model(presenca)


@router.post(
    "/cell-reunioes/{reuniao_id}/expectativas-visitantes",
    response_model=ExpectativaVisitanteOut,
    status_code=status.HTTP_201_CREATED,
)
def register_expectativa_visitante(
    reuniao_id: str,
    payload: RegisterExpectativaRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ExpectativaVisitanteOut:
    """Registra a expectativa nominal de um visitante para uma reunião (Domínio C).

    Regras (RF-16/RF-17):
      - Registro SEMPRE da PRÓPRIA pessoa do app_user (nunca por terceiro no
        PR2). app_user sem pessoa vinculada → 403 (SEC-DEC-04).
      - Exige vínculo ATIVO na célula DA REUNIÃO (E11); sem vínculo válido → 403.
        A reunião é resolvida por `_get_reuniao_or_404` (404 fora do tenant).
      - Modelo NOMINAL: `nomeVisitante` obrigatório + `observacaoOracao` opcional;
        a validação de borda (trim/comprimento) já roda no Pydantic (422 antes de
        qualquer escrita).
      - É CRIAÇÃO REAL → sempre 201 CREATED. SEM UNIQUE: permite N registros do
        mesmo membro na mesma reunião (um por visitante).
      - Sem efeito externo: NÃO cria Pessoa/contato e NÃO dispara WhatsApp. O
        status da reunião NÃO é validado (E12).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)

    # SEMPRE da própria pessoa do app_user (nunca terceiro no PR2, SEC-DEC-04).
    actor_pessoa = _actor_pessoa_id(db, current_user)
    if actor_pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu usuário não está vinculado a uma pessoa",
        )
    pessoa_uuid = uuid.UUID(actor_pessoa)

    # E11: vínculo ativo obrigatório na célula DA REUNIÃO (não vale outra célula).
    if not _has_active_membership(db, igreja_id, reuniao.celula_id, pessoa_uuid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem vínculo ativo na célula desta reunião",
        )

    expectativa = CelulaExpectativaVisitante(
        igreja_id=igreja_id,
        reuniao_id=reuniao.id,
        pessoa_id=pessoa_uuid,
        nome_visitante=payload.nomeVisitante,
        observacao_oracao=payload.observacaoOracao,
    )
    db.add(expectativa)
    db.flush()
    db.refresh(expectativa)
    db.commit()

    return ExpectativaVisitanteOut.from_model(expectativa)


# ===========================================================================
# DOMÍNIO LÍDER (Minha Célula) + CICLO DO RELATÓRIO — Células PR3-PR9
# ===========================================================================
# Contrato externo em snake_case (espelha a SPEC §5 e o router do Discípulo).
# Toda autorização deriva do contexto Clerk (igreja_id + ownership de célula por
# celulas.lider_id, E9/6.6) — nunca do payload. Endpoints de escrita ficam
# bloqueados após o relatório ser enviado (E10/E11), sem hard-delete.


# ---------------------------------------------------------------------------
# Schemas — reunião (planejar/editar)
# ---------------------------------------------------------------------------
class PlanMeetingRequest(BaseModel):
    """Planejar reunião pontual: cria a ocorrência SEM tocar no padrão da célula."""

    celula_id: str
    data: dt.date
    hora: str | None = None
    tema: str | None = None

    @field_validator("celula_id")
    @classmethod
    def _celula_uuid(cls, value: str) -> str:
        return _validate_uuid_str(value, "celula_id")

    @field_validator("hora")
    @classmethod
    def _hora_fmt(cls, value: str | None) -> str | None:
        return _norm_optional_hora(value)

    @field_validator("tema")
    @classmethod
    def _tema_fmt(cls, value: str | None) -> str | None:
        return _norm_optional_text(value, _TEMA_MAX, "tema")


class EditMeetingRequest(BaseModel):
    """Editar reunião pontual: SOMENTE data/hora/tema.

    Campos sensíveis da célula (anfitrião, auxiliar, endereço, dia/horário padrão)
    são IGNORADOS aqui — não há como alterá-los por esta borda (RF-14). A alteração
    de sensíveis é fluxo de Solicitação (PR5), fora deste endpoint.
    """

    data: dt.date
    hora: str | None = None
    tema: str | None = None

    @field_validator("hora")
    @classmethod
    def _hora_fmt(cls, value: str | None) -> str | None:
        return _norm_optional_hora(value)

    @field_validator("tema")
    @classmethod
    def _tema_fmt(cls, value: str | None) -> str | None:
        return _norm_optional_text(value, _TEMA_MAX, "tema")


class LeaderMeetingOut(BaseModel):
    """Contrato snake_case da reunião do Líder (inclui relatorio_status)."""

    id: str
    celula_id: str
    data: str
    hora: str | None = None
    tema: str | None = None
    status: str
    relatorio_status: str

    @classmethod
    def from_model(cls, r: CelulaReuniao) -> "LeaderMeetingOut":
        return cls(
            id=str(r.id),
            celula_id=str(r.celula_id),
            data=r.data.isoformat(),
            hora=r.hora,
            tema=r.tema,
            status=r.status,
            relatorio_status=r.relatorio_status,
        )


# ---------------------------------------------------------------------------
# Schemas — presença real
# ---------------------------------------------------------------------------
class AttendanceEntry(BaseModel):
    pessoa_id: str
    compareceu: bool

    @field_validator("pessoa_id")
    @classmethod
    def _pessoa_uuid(cls, value: str) -> str:
        return _validate_uuid_str(value, "pessoa_id")


class SetAttendanceRequest(BaseModel):
    presencas: list[AttendanceEntry]


class AttendanceEntryOut(BaseModel):
    pessoa_id: str
    compareceu: bool


class SetAttendanceOut(BaseModel):
    meeting_id: str
    presencas: list[AttendanceEntryOut]


# ---------------------------------------------------------------------------
# Schemas — visitantes presentes / expectativas
# ---------------------------------------------------------------------------
class RegisterVisitorRequest(BaseModel):
    nome_visitante: str
    expectativa_id: str | None = None
    observacao: str | None = None

    @field_validator("nome_visitante")
    @classmethod
    def _nome(cls, value: str) -> str:
        return _require_text(value, _NOME_VISITANTE_MAX, "nome_visitante")

    @field_validator("expectativa_id")
    @classmethod
    def _exp_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_uuid_str(value, "expectativa_id")

    @field_validator("observacao")
    @classmethod
    def _obs(cls, value: str | None) -> str | None:
        return _norm_optional_text(value, _OBSERVACOES_MAX, "observacao")


class VisitorOut(BaseModel):
    id: str
    reuniao_id: str
    nome_visitante: str
    expectativa_id: str | None = None


class VisitorExpectationItem(BaseModel):
    id: str
    nome_visitante: str
    indicado_por: str
    compareceu: bool


class VisitorExpectationsOut(BaseModel):
    expectations: list[VisitorExpectationItem]


# ---------------------------------------------------------------------------
# Schemas — registros pastorais
# ---------------------------------------------------------------------------
class AddRecordRequest(BaseModel):
    tipo: str
    conteudo: str
    pessoa_id: str | None = None

    @field_validator("tipo")
    @classmethod
    def _tipo_valido(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if value not in RECORD_TIPOS:
            raise ValueError(f"tipo inválido: {value}")
        return value

    @field_validator("conteudo")
    @classmethod
    def _conteudo(cls, value: str) -> str:
        return _require_text(value, _CONTEUDO_MAX, "conteudo")

    @field_validator("pessoa_id")
    @classmethod
    def _pessoa_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_uuid_str(value, "pessoa_id")


class RecordOut(BaseModel):
    id: str
    reuniao_id: str
    tipo: str
    conteudo: str
    pessoa_id: str | None = None
    autor_id: str | None = None


class RecordItem(BaseModel):
    id: str
    tipo: str
    conteudo: str
    pessoa_id: str | None = None


class RecordsOut(BaseModel):
    records: list[RecordItem]


# ---------------------------------------------------------------------------
# Schemas — ciclo do relatório
# ---------------------------------------------------------------------------
class SaveReportRequest(BaseModel):
    oferta_valor: float | None = None
    observacoes: str | None = None

    @field_validator("oferta_valor")
    @classmethod
    def _oferta(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < _OFERTA_MIN or value > _OFERTA_MAX:
            raise ValueError("oferta_valor deve estar entre 0 e 999999.99")
        return value

    @field_validator("observacoes")
    @classmethod
    def _obs(cls, value: str | None) -> str | None:
        return _norm_optional_text(value, _OBSERVACOES_MAX, "observacoes")


class SaveReportOut(BaseModel):
    meeting_id: str
    oferta_valor: float | None = None
    observacoes: str | None = None
    relatorio_status: str


class SubmitReportOut(BaseModel):
    meeting_id: str
    relatorio_status: str
    relatorio_enviado_em: str | None = None
    relatorio_enviado_por: str | None = None


class ReportPresenca(BaseModel):
    pessoa_id: str
    estado: str
    origem: str | None = None


class ReportVisitante(BaseModel):
    id: str
    nome_visitante: str
    expectativa_id: str | None = None
    observacao: str | None = None


class ReportRecord(BaseModel):
    id: str
    tipo: str
    conteudo: str
    pessoa_id: str | None = None


class ReportOut(BaseModel):
    meeting_id: str
    data: str
    tema: str | None = None
    relatorio_status: str
    oferta_valor: float | None = None
    observacoes: str | None = None
    presencas: list[ReportPresenca]
    visitantes: list[ReportVisitante]
    records: list[ReportRecord]


# ---------------------------------------------------------------------------
# Schemas — members (gerenciar discípulos da própria célula)
# ---------------------------------------------------------------------------
class MemberItem(BaseModel):
    pessoa_id: str
    nome: str
    ativo: bool


class MembersOut(BaseModel):
    members: list[MemberItem]


# ---------------------------------------------------------------------------
# Helpers de autorização/estado do domínio Líder
# ---------------------------------------------------------------------------
def _cell_led_by_or_403(
    db: Session, current_user: CurrentUser, cell_id: str
) -> Celula:
    """Resolve a célula no tenant (404) e exige que o ator seja seu LÍDER (403).

    Usado no POST /cell-meetings, onde a célula vem do payload: célula inexistente
    no tenant / id malformado → 404 (não vaza existência de outro tenant); célula
    do tenant mas não liderada pelo ator → 403 (papel sem permissão sobre ela).
    Ownership deriva de celulas.lider_id ligado à Pessoa do app_user (E9/6.6).
    """
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada"
    )
    try:
        cell_uuid = uuid.UUID(cell_id)
    except (ValueError, AttributeError) as exc:
        raise not_found from exc
    cell = db.execute(
        select(Celula).where(
            Celula.id == cell_uuid,
            Celula.igreja_id == uuid.UUID(current_user.igreja_id),
        )
    ).scalar_one_or_none()
    if cell is None:
        raise not_found
    actor = _actor_pessoa_id(db, current_user)
    if cell.lider_id is None or actor is None or str(cell.lider_id) != actor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o líder da célula pode planejar reuniões nela",
        )
    return cell


def _leader_meeting_or_404(
    db: Session, current_user: CurrentUser, reuniao_id: str
) -> CelulaReuniao:
    """Reunião do tenant cuja célula é liderada pelo ator (E9); 404 caso contrário.

    Resolve a reunião (404 fora do tenant) e enforce a liderança da célula da
    reunião via ``get_current_cell_for_leader`` (404 sem vazar existência). Base
    das escritas do Líder (editar, presença, visitantes, registros, relatório).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)
    get_current_cell_for_leader(db, current_user, str(reuniao.celula_id))
    return reuniao


def _reader_meeting_or_404(
    db: Session, current_user: CurrentUser, reuniao_id: str
) -> CelulaReuniao:
    """Reunião legível por LÍDER da célula OU Central (pastor/admin).

    GET de registros/relatório: a Central lê qualquer célula do tenant; o líder
    só a própria (404). Discípulo/membro comum não passa (404) — a projeção
    pastoral fica oculta dele (RF-05/RF-30).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)
    if not current_user.has_any_role(CENTRAL_ROLES):
        get_current_cell_for_leader(db, current_user, str(reuniao.celula_id))
    return reuniao


def _assert_report_open(reuniao: CelulaReuniao) -> None:
    """Bloqueia escrita quando o relatório já foi enviado (E10/E11) — 409."""
    if reuniao.relatorio_status == RELATORIO_ENVIADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Relatório já enviado; edição bloqueada (sem reabertura no MVP)",
        )


# ---------------------------------------------------------------------------
# POST /cell-meetings — planejar reunião pontual (US-06/RF-06)
# ---------------------------------------------------------------------------
@router.post(
    "/cell-meetings",
    response_model=LeaderMeetingOut,
    status_code=status.HTTP_201_CREATED,
)
def plan_meeting(
    payload: PlanMeetingRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> LeaderMeetingOut:
    """Cria uma reunião materializada da própria célula (relatorio_status pendente).

    Não altera o dia/horário PADRÃO da célula — só cria a ocorrência (data/hora/tema
    daquela reunião). 403 se o ator não lidera a célula do payload; 404 se a célula
    não é do tenant. 409 se já existir reunião no mesmo slot (idempotência de slot,
    UNIQUE igreja_id/celula_id/data/hora).
    """
    cell = _cell_led_by_or_403(db, current_user, payload.celula_id)
    igreja_id = uuid.UUID(current_user.igreja_id)

    existing = _find_slot(db, igreja_id, cell.id, payload.data, payload.hora)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma reunião planejada para esta data/horário",
        )

    reuniao = CelulaReuniao(
        igreja_id=igreja_id,
        celula_id=cell.id,
        data=payload.data,
        hora=payload.hora,
        tema=payload.tema,
        status=STATUS_PLANEJADA,
        relatorio_status=RELATORIO_PENDENTE,
    )
    db.add(reuniao)
    try:
        db.flush()
        db.refresh(reuniao)
        db.commit()
    except IntegrityError as exc:
        # Corrida no UNIQUE de slot: outra requisição criou entre o pré-check e o
        # INSERT. Mapeia para 409 (nunca 500) — conflito de estado.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma reunião planejada para esta data/horário",
        ) from exc
    return LeaderMeetingOut.from_model(reuniao)


# ---------------------------------------------------------------------------
# PUT /cell-meetings/{id} — editar planejamento (US-06/RF-06/RF-14)
# ---------------------------------------------------------------------------
@router.put("/cell-meetings/{reuniao_id}", response_model=LeaderMeetingOut)
def edit_meeting(
    reuniao_id: str,
    payload: EditMeetingRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> LeaderMeetingOut:
    """Edita data/hora/tema da reunião pontual da própria célula.

    Campos sensíveis da célula (anfitrião/auxiliar/endereço/dia/horário padrão)
    NÃO são aplicáveis por aqui: o schema só aceita data/hora/tema e qualquer
    campo sensível enviado é ignorado (RF-14). 404 se a reunião não é do
    líder/tenant. 409 se o novo slot colidir com outra reunião.
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    # E10/E11: após o relatório enviado, data/hora/tema da reunião ficam
    # congelados (editar aqui alteraria o relatório já consolidado — get_report
    # expõe data/tema). Mesmo gate dos demais endpoints de escrita do relatório.
    _assert_report_open(reuniao)

    reuniao.data = payload.data
    reuniao.hora = payload.hora
    reuniao.tema = payload.tema
    reuniao.updated_at = dt.datetime.now(dt.timezone.utc)
    try:
        db.flush()
        db.refresh(reuniao)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma reunião nesta data/horário",
        ) from exc
    return LeaderMeetingOut.from_model(reuniao)


# ---------------------------------------------------------------------------
# PUT /cell-meetings/{id}/attendance — presença real (US-07/RF-07)
# ---------------------------------------------------------------------------
@router.put(
    "/cell-meetings/{reuniao_id}/attendance", response_model=SetAttendanceOut
)
def set_real_attendance(
    reuniao_id: str,
    payload: SetAttendanceRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SetAttendanceOut:
    """Marca comparecimento real por participante da própria célula (celula_presenca).

    Upsert idempotente por pessoa: compareceu=True → estado 'compareceu';
    compareceu=False → 'ausente'; origem='lider'. Cada pessoa precisa existir no
    tenant (422) e ter vínculo ATIVO na célula da reunião (422, E11). Bloqueado
    após o relatório enviado (409, E10/E11). 404 se a reunião não é do líder/tenant.
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    _assert_report_open(reuniao)
    igreja_id = uuid.UUID(current_user.igreja_id)
    now = dt.datetime.now(dt.timezone.utc)

    out: list[AttendanceEntryOut] = []
    for entry in payload.presencas:
        pessoa_uuid = uuid.UUID(entry.pessoa_id)
        _assert_pessoa_tenant(db, pessoa_uuid, "pessoa_id")
        if not _has_active_membership(db, igreja_id, reuniao.celula_id, pessoa_uuid):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"pessoa_id {entry.pessoa_id}: sem vínculo ativo na célula",
            )
        estado = ESTADO_COMPARECEU if entry.compareceu else ESTADO_AUSENTE
        existing = _find_presenca(db, igreja_id, reuniao.id, pessoa_uuid)
        if existing is not None:
            existing.estado = estado
            existing.origem = ORIGEM_LIDER
            existing.updated_at = now
        else:
            db.add(
                CelulaPresenca(
                    igreja_id=igreja_id,
                    reuniao_id=reuniao.id,
                    pessoa_id=pessoa_uuid,
                    estado=estado,
                    origem=ORIGEM_LIDER,
                )
            )
        out.append(
            AttendanceEntryOut(pessoa_id=entry.pessoa_id, compareceu=entry.compareceu)
        )

    try:
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflito ao gravar presença; tente novamente",
        ) from exc
    return SetAttendanceOut(meeting_id=str(reuniao.id), presencas=out)


# ---------------------------------------------------------------------------
# POST /cell-meetings/{id}/visitors — visitante presente (US-08/RF-08)
# ---------------------------------------------------------------------------
@router.post(
    "/cell-meetings/{reuniao_id}/visitors",
    response_model=VisitorOut,
    status_code=status.HTTP_201_CREATED,
)
def register_visitor(
    reuniao_id: str,
    payload: RegisterVisitorRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> VisitorOut:
    """Registra visitante que compareceu (celula_visitante), com link opcional a
    uma expectativa indicada por discípulo (`expectativa_id`).

    A expectativa vinculada precisa ser da MESMA reunião no tenant (422 caso
    contrário). Bloqueado após o relatório enviado (409). 404 fora do líder/tenant.
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    _assert_report_open(reuniao)
    igreja_id = uuid.UUID(current_user.igreja_id)

    expectativa_uuid: uuid.UUID | None = None
    if payload.expectativa_id is not None:
        expectativa_uuid = uuid.UUID(payload.expectativa_id)
        exp = db.execute(
            select(CelulaExpectativaVisitante).where(
                CelulaExpectativaVisitante.id == expectativa_uuid,
                CelulaExpectativaVisitante.igreja_id == igreja_id,
                CelulaExpectativaVisitante.reuniao_id == reuniao.id,
            )
        ).scalar_one_or_none()
        if exp is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expectativa_id não encontrada para esta reunião",
            )

    visitante = CelulaVisitante(
        igreja_id=igreja_id,
        reuniao_id=reuniao.id,
        expectativa_id=expectativa_uuid,
        nome_visitante=payload.nome_visitante,
        observacao=payload.observacao,
    )
    db.add(visitante)
    db.flush()
    db.refresh(visitante)
    db.commit()
    return VisitorOut(
        id=str(visitante.id),
        reuniao_id=str(visitante.reuniao_id),
        nome_visitante=visitante.nome_visitante,
        expectativa_id=(
            str(visitante.expectativa_id) if visitante.expectativa_id else None
        ),
    )


# ---------------------------------------------------------------------------
# GET /cell-meetings/{id}/visitor-expectations — esperados (US-08/RF-08)
# ---------------------------------------------------------------------------
@router.get(
    "/cell-meetings/{reuniao_id}/visitor-expectations",
    response_model=VisitorExpectationsOut,
)
def list_visitor_expectations(
    reuniao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> VisitorExpectationsOut:
    """Lista as expectativas de visitante (indicadas por discípulos) para o líder.

    `compareceu` deriva da existência de um `celula_visitante` vinculado àquela
    expectativa (o líder confirmou o comparecimento). 404 fora do líder/tenant.
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    igreja_id = uuid.UUID(current_user.igreja_id)

    exps = db.execute(
        select(CelulaExpectativaVisitante)
        .where(
            CelulaExpectativaVisitante.igreja_id == igreja_id,
            CelulaExpectativaVisitante.reuniao_id == reuniao.id,
        )
        .order_by(CelulaExpectativaVisitante.created_at.asc())
    ).scalars().all()

    visitantes = db.execute(
        select(CelulaVisitante).where(
            CelulaVisitante.igreja_id == igreja_id,
            CelulaVisitante.reuniao_id == reuniao.id,
        )
    ).scalars().all()
    attended = {
        str(v.expectativa_id) for v in visitantes if v.expectativa_id is not None
    }

    return VisitorExpectationsOut(
        expectations=[
            VisitorExpectationItem(
                id=str(e.id),
                nome_visitante=e.nome_visitante,
                indicado_por=str(e.pessoa_id),
                compareceu=str(e.id) in attended,
            )
            for e in exps
        ]
    )


# ---------------------------------------------------------------------------
# POST /cell-meetings/{id}/records — registros pastorais (US-09/RF-09)
# ---------------------------------------------------------------------------
@router.post(
    "/cell-meetings/{reuniao_id}/records",
    response_model=RecordOut,
    status_code=status.HTTP_201_CREATED,
)
def add_record(
    reuniao_id: str,
    payload: AddRecordRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> RecordOut:
    """Registra decisão/oração/observação da reunião (celula_reuniao_registro).

    `autor_id` vem do contexto (Pessoa do líder autenticado), nunca do payload.
    `pessoa_id` (alvo) é opcional e, se presente, precisa existir no tenant (422).
    Só o líder da célula escreve (404 caso contrário). Bloqueado após enviado (409).
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    _assert_report_open(reuniao)
    igreja_id = uuid.UUID(current_user.igreja_id)

    actor = resolve_actor_pessoa_id(db, current_user)
    autor_uuid = uuid.UUID(actor) if actor else None

    pessoa_uuid: uuid.UUID | None = None
    if payload.pessoa_id is not None:
        pessoa_uuid = uuid.UUID(payload.pessoa_id)
        _assert_pessoa_tenant(db, pessoa_uuid, "pessoa_id")

    registro = CelulaReuniaoRegistro(
        igreja_id=igreja_id,
        reuniao_id=reuniao.id,
        tipo=payload.tipo,
        conteudo=payload.conteudo,
        pessoa_id=pessoa_uuid,
        autor_id=autor_uuid,
    )
    db.add(registro)
    db.flush()
    db.refresh(registro)
    db.commit()
    return RecordOut(
        id=str(registro.id),
        reuniao_id=str(registro.reuniao_id),
        tipo=registro.tipo,
        conteudo=registro.conteudo,
        pessoa_id=str(registro.pessoa_id) if registro.pessoa_id else None,
        autor_id=str(registro.autor_id) if registro.autor_id else None,
    )


# ---------------------------------------------------------------------------
# GET /cell-meetings/{id}/records — listar registros (US-09) — líder/Central
# ---------------------------------------------------------------------------
@router.get("/cell-meetings/{reuniao_id}/records", response_model=RecordsOut)
def list_records(
    reuniao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> RecordsOut:
    """Lista os registros pastorais da reunião — visível a líder/Central.

    Oculto do discípulo por projeção server-side (RF-05/RF-30): membro comum não
    passa pela autorização (404). A Central (pastor/admin) lê qualquer célula do
    tenant.
    """
    reuniao = _reader_meeting_or_404(db, current_user, reuniao_id)
    igreja_id = uuid.UUID(current_user.igreja_id)

    rows = db.execute(
        select(CelulaReuniaoRegistro)
        .where(
            CelulaReuniaoRegistro.igreja_id == igreja_id,
            CelulaReuniaoRegistro.reuniao_id == reuniao.id,
        )
        .order_by(CelulaReuniaoRegistro.created_at.asc())
    ).scalars().all()

    return RecordsOut(
        records=[
            RecordItem(
                id=str(r.id),
                tipo=r.tipo,
                conteudo=r.conteudo,
                pessoa_id=str(r.pessoa_id) if r.pessoa_id else None,
            )
            for r in rows
        ]
    )


# ---------------------------------------------------------------------------
# PUT /cell-meetings/{id}/report — draft de oferta/observações (US-10/RF-10)
# ---------------------------------------------------------------------------
@router.put("/cell-meetings/{reuniao_id}/report", response_model=SaveReportOut)
def save_report(
    reuniao_id: str,
    payload: SaveReportRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SaveReportOut:
    """Grava oferta_valor/observacoes do relatório SEM enviar (mantém 'pendente').

    Validação E1/E2 no schema: 0 <= oferta_valor <= 999999.99 e observacoes <=
    2000 (422 fora do intervalo). Bloqueado após enviado (409, E10/E11). 404 fora
    do líder/tenant.
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    _assert_report_open(reuniao)

    reuniao.oferta_valor = payload.oferta_valor
    reuniao.observacoes = payload.observacoes
    reuniao.updated_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.refresh(reuniao)
    db.commit()
    return SaveReportOut(
        meeting_id=str(reuniao.id),
        oferta_valor=(
            float(reuniao.oferta_valor) if reuniao.oferta_valor is not None else None
        ),
        observacoes=reuniao.observacoes,
        relatorio_status=reuniao.relatorio_status,
    )


# ---------------------------------------------------------------------------
# Relatório consolidado — montagem ao vivo (reusada pelo submit p/ o snapshot)
# ---------------------------------------------------------------------------
def _build_report_out(
    db: Session, igreja_id: uuid.UUID, reuniao: CelulaReuniao
) -> ReportOut:
    """Monta o relatório consolidado AO VIVO a partir das tabelas-fato."""
    presencas = db.execute(
        select(CelulaPresenca)
        .where(
            CelulaPresenca.igreja_id == igreja_id,
            CelulaPresenca.reuniao_id == reuniao.id,
        )
        .order_by(CelulaPresenca.created_at.asc())
    ).scalars().all()
    visitantes = db.execute(
        select(CelulaVisitante)
        .where(
            CelulaVisitante.igreja_id == igreja_id,
            CelulaVisitante.reuniao_id == reuniao.id,
        )
        .order_by(CelulaVisitante.created_at.asc())
    ).scalars().all()
    records = db.execute(
        select(CelulaReuniaoRegistro)
        .where(
            CelulaReuniaoRegistro.igreja_id == igreja_id,
            CelulaReuniaoRegistro.reuniao_id == reuniao.id,
        )
        .order_by(CelulaReuniaoRegistro.created_at.asc())
    ).scalars().all()

    return ReportOut(
        meeting_id=str(reuniao.id),
        data=reuniao.data.isoformat(),
        tema=reuniao.tema,
        relatorio_status=reuniao.relatorio_status,
        oferta_valor=(
            float(reuniao.oferta_valor) if reuniao.oferta_valor is not None else None
        ),
        observacoes=reuniao.observacoes,
        presencas=[
            ReportPresenca(pessoa_id=str(p.pessoa_id), estado=p.estado, origem=p.origem)
            for p in presencas
        ],
        visitantes=[
            ReportVisitante(
                id=str(v.id),
                nome_visitante=v.nome_visitante,
                expectativa_id=str(v.expectativa_id) if v.expectativa_id else None,
                observacao=v.observacao,
            )
            for v in visitantes
        ],
        records=[
            ReportRecord(
                id=str(r.id),
                tipo=r.tipo,
                conteudo=r.conteudo,
                pessoa_id=str(r.pessoa_id) if r.pessoa_id else None,
            )
            for r in records
        ],
    )


# ---------------------------------------------------------------------------
# POST /cell-meetings/{id}/report/submit — enviar relatório (US-11/RF-11/RF-12)
# ---------------------------------------------------------------------------
@router.post(
    "/cell-meetings/{reuniao_id}/report/submit", response_model=SubmitReportOut
)
def submit_report(
    reuniao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SubmitReportOut:
    """Consolida o relatório e muda relatorio_status para 'enviado' (E10/E11).

    Grava relatorio_enviado_em (UTC) e relatorio_enviado_por (Pessoa do líder).
    409 se já enviado (sem reabertura no MVP). 404 fora do líder/tenant.
    """
    reuniao = _leader_meeting_or_404(db, current_user, reuniao_id)
    if reuniao.relatorio_status == RELATORIO_ENVIADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Relatório já enviado",
        )

    actor = resolve_actor_pessoa_id(db, current_user)
    now = dt.datetime.now(dt.timezone.utc)
    reuniao.relatorio_status = RELATORIO_ENVIADO
    reuniao.relatorio_enviado_em = now
    reuniao.relatorio_enviado_por = uuid.UUID(actor) if actor else None
    reuniao.updated_at = now
    # Congela o consolidado (E10/E11): materializa presenças/visitantes/registros/
    # oferta/observações num snapshot imutável. get_report passa a ler o snapshot,
    # de modo que escritas posteriores em celula_presenca (endpoint PR2, upsert
    # sempre-200) não alterem o relatório já enviado.
    reuniao.relatorio_snapshot = _build_report_out(
        db, uuid.UUID(current_user.igreja_id), reuniao
    ).model_dump()
    db.flush()
    db.refresh(reuniao)
    db.commit()
    return SubmitReportOut(
        meeting_id=str(reuniao.id),
        relatorio_status=reuniao.relatorio_status,
        relatorio_enviado_em=(
            reuniao.relatorio_enviado_em.isoformat()
            if reuniao.relatorio_enviado_em
            else None
        ),
        relatorio_enviado_por=(
            str(reuniao.relatorio_enviado_por)
            if reuniao.relatorio_enviado_por
            else None
        ),
    )


# ---------------------------------------------------------------------------
# GET /cell-meetings/{id}/report — relatório consolidado (US-11) — líder/Central
# ---------------------------------------------------------------------------
@router.get("/cell-meetings/{reuniao_id}/report", response_model=ReportOut)
def get_report(
    reuniao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ReportOut:
    """Relatório consolidado: presenças, visitantes, registros, oferta, observações
    e status. Visível a líder/Central (404 caso contrário)."""
    reuniao = _reader_meeting_or_404(db, current_user, reuniao_id)
    igreja_id = uuid.UUID(current_user.igreja_id)

    # Pós-envio (E10/E11): devolve o snapshot congelado no submit — não relê
    # celula_presenca ao vivo, que o endpoint PR2 pode ter mudado depois.
    if reuniao.relatorio_status == RELATORIO_ENVIADO and reuniao.relatorio_snapshot:
        return ReportOut(**reuniao.relatorio_snapshot)

    return _build_report_out(db, igreja_id, reuniao)


# ---------------------------------------------------------------------------
# GET /cells/me/leading — células que o ator LIDERA (fonte do painel do Líder)
# ---------------------------------------------------------------------------
class LedCellOut(BaseModel):
    id: str
    nome: str


@router.get("/cells/me/leading", response_model=list[LedCellOut])
def list_my_led_cells(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[LedCellOut]:
    """Células cujo `lider_id` é a Pessoa do app_user autenticado (E9/6.6).

    Fonte AUTORITATIVA da(s) célula(s) que o usuário LIDERA — distinta da célula
    onde ele é MEMBRO (`celula_membro`). O painel "Minha Célula" do Líder resolve
    seu `celula_id` por aqui; sem isso um líder que também é membro da célula do
    seu próprio líder resolveria a célula errada. igreja_id/pessoa do contexto
    autenticado; lista vazia se o app_user não tem Pessoa.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    actor = _actor_pessoa_id(db, current_user)
    if actor is None:
        return []
    rows = db.execute(
        select(Celula)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.lider_id == uuid.UUID(actor),
        )
        .order_by(Celula.nome.asc())
    ).scalars().all()
    return [LedCellOut(id=str(c.id), nome=c.nome) for c in rows]


# ---------------------------------------------------------------------------
# GET /cells/{cell_id}/members — gerenciar discípulos da própria célula (US-12)
# ---------------------------------------------------------------------------
@router.get("/cells/{cell_id}/members", response_model=MembersOut)
def list_leader_cell_members(
    cell_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> MembersOut:
    """Lista os discípulos (membros ativos) da célula do líder (celula_membro).

    Restrito à própria célula: 404 se a célula é de outro líder/tenant (ownership
    por celulas.lider_id, E9). `nome` deriva de `pessoas.nome`.
    """
    cell = get_current_cell_for_leader(db, current_user, cell_id)
    igreja_id = uuid.UUID(current_user.igreja_id)

    rows = db.execute(
        select(CelulaMembro)
        .where(
            CelulaMembro.celula_id == cell.id,
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.ativo.is_(True),
        )
        .order_by(CelulaMembro.created_at.asc())
    ).scalars().all()

    # Resolve nomes só das pessoas destes membros, filtrando por tenant (defesa
    # em profundidade além da RLS) e sem varrer a tabela `pessoas` inteira.
    member_pessoa_ids = [m.pessoa_id for m in rows]
    nome_by_id: dict[str, str] = {}
    if member_pessoa_ids:
        nome_by_id = {
            str(pid): nome
            for pid, nome in db.execute(
                select(Pessoa.id, Pessoa.nome).where(
                    Pessoa.igreja_id == igreja_id,
                    Pessoa.id.in_(member_pessoa_ids),
                )
            ).all()
        }

    return MembersOut(
        members=[
            MemberItem(
                pessoa_id=str(m.pessoa_id),
                nome=nome_by_id.get(str(m.pessoa_id), ""),
                ativo=m.ativo,
            )
            for m in rows
        ]
    )

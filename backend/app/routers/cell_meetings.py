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
)
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.cell_meetings_schedule import InvalidDiaReuniao, next_meeting_date
from app.domain.hierarchy import is_leader_or_superior
from app.routers._common import ensure_tenant_context

# Reuso dos helpers de cells.py (BK-DEC-01) — não reimplementar aqui.
from app.routers.cells import (
    CENTRAL_ROLES,
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
    ensure_tenant_context(db, current_user)
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
    ensure_tenant_context(db, current_user)
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
        ensure_tenant_context(db, current_user)
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
    ensure_tenant_context(db, current_user)
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
        ensure_tenant_context(db, current_user)
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
    ensure_tenant_context(db, current_user)
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

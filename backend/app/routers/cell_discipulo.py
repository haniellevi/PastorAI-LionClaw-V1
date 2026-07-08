"""Minha Célula — visão Discípulo (Células PR3).

Router próprio da visão Discípulo (o membro de uma célula). Reusa o modelo de
dados de PR2 (``celula_reuniao``/``celula_presenca``/``celula_expectativa_visitante``)
e os helpers de ``cell_meetings.py``/``cells.py`` — sem duplicar lógica de lookup.

Invariantes de segurança (RF-05/RF-30):
  - Toda projeção é MINIMIZADA server-side: o discípulo NUNCA recebe no JSON
    decisões/oração/relatório da reunião nem presença/expectativa de TERCEIROS.
    Só enxerga a própria célula, a própria presença e os próprios visitantes.
  - ``igreja_id`` e papel derivam SEMPRE do contexto autenticado (Clerk), nunca
    do payload/query/header do cliente.
  - "Passada"/"futura" usa o fuso ``America/Sao_Paulo`` (E4).

Endpoints:
  - GET    /cells/me/next-meeting                       próxima reunião futura
  - GET    /cells/me/notices                            avisos (leitura)
  - GET    /cells/me/history                            histórico paginado (mín.)
  - POST   /cell-meetings/{id}/attendance/confirm       confirmar presença (1 toque)
  - DELETE /cell-meetings/{id}/attendance/confirm        reverter confirmação
  - POST   /cell-meetings/{id}/visitor-expectations     indicar visitante (nominal)
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Celula,
    CelulaAviso,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
)
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user, resolve_actor_pessoa_id
from app.domain.cell_meetings_schedule import meeting_has_passed

# Reuso dos helpers/constantes de cell_meetings.py (PR2) — não reimplementar.
from app.routers.cell_meetings import (
    ESTADO_CONFIRMADA,
    RegisterExpectativaRequest,
    _find_presenca,
    _get_reuniao_or_404,
    _has_active_membership,
)

logger = logging.getLogger("pastorai.cell_discipulo")

router = APIRouter(tags=["cell-discipulo"])

# Origem gravada quando o próprio membro confirma sua presença (auto-serviço).
ORIGEM_AUTO = "auto"

# Paginação do histórico (contrato do Discípulo, snake_case): padrão 20, máx 100.
DEFAULT_HISTORY_PAGE_SIZE = 20
MAX_HISTORY_PAGE_SIZE = 100

# E5 — mapeamento estado da presença (celula_presenca) → rótulo do Discípulo.
# "sem linha" (None) → 'nao_confirmou': NUNCA inferir falta sem 'ausente' explícito.
_PRESENCE_LABEL: dict[str, str] = {
    "compareceu": "participou",
    "ausente": "faltou",
    "confirmada": "confirmou",
}
_PRESENCE_NONE = "nao_confirmou"


def _map_minha_presenca(estado: str | None) -> str:
    """Aplica o mapeamento E5; ausência de linha vira 'nao_confirmou'."""
    if estado is None:
        return _PRESENCE_NONE
    return _PRESENCE_LABEL.get(estado, _PRESENCE_NONE)


# ---------------------------------------------------------------------------
# Schemas (contrato do Discípulo em snake_case, conforme critérios da sprint)
# ---------------------------------------------------------------------------
class NextMeetingBody(BaseModel):
    id: str
    celula_id: str
    data: str  # YYYY-MM-DD
    hora: str | None = None  # HH:MM
    local: str | None = None
    tema: str | None = None
    # Estado da presença do PRÓPRIO membro nesta reunião (E5), p/ a UI inicializar
    # o botão de confirmação sem um segundo request: confirmou|participou|faltou|
    # nao_confirmou.
    minha_presenca: str = _PRESENCE_NONE


class NextMeetingResponse(BaseModel):
    """Envelope da próxima reunião: ``meeting`` é null quando não houver."""

    meeting: NextMeetingBody | None = None


class NoticeOut(BaseModel):
    id: str
    origem: str  # igreja | celula
    escopo: str  # igreja | celula
    titulo: str
    conteudo: str
    publicado_em: str


class HistoryItem(BaseModel):
    """Projeção MINIMIZADA de uma reunião passada (só dados do próprio membro)."""

    data: str
    tema: str | None = None
    minha_presenca: str
    meus_visitantes_indicados: list[str] = []


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    page: int
    page_size: int
    total: int


class AttendanceOut(BaseModel):
    reuniao_id: str
    minha_presenca: str


class VisitorExpectationOut(BaseModel):
    """Contrato de saída da expectativa criada (dados do próprio membro)."""

    id: str
    reuniao_id: str
    nome_visitante: str
    observacao_oracao: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_pessoa(db: Session, current_user: CurrentUser) -> uuid.UUID | None:
    """UUID da Pessoa do app_user, ou None quando não vinculado (SEC-DEC-04)."""
    actor = resolve_actor_pessoa_id(db, current_user)
    return uuid.UUID(actor) if actor else None


def _active_cell_id(
    db: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> uuid.UUID | None:
    """Célula ATIVA do membro (1 pessoa → 1 célula ativa), ou None."""
    membro = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.ativo.is_(True),
        )
    ).scalar_one_or_none()
    return membro.celula_id if membro is not None else None


def _my_visitor_names(
    db: Session, igreja_id: uuid.UUID, reuniao_id: uuid.UUID, pessoa_id: uuid.UUID
) -> list[str]:
    """Nomes dos visitantes que O PRÓPRIO membro indicou para a reunião.

    Escopado a ``pessoa_id`` = nunca expõe expectativa de terceiros (RF-30).
    """
    rows = db.execute(
        select(CelulaExpectativaVisitante)
        .where(
            CelulaExpectativaVisitante.igreja_id == igreja_id,
            CelulaExpectativaVisitante.reuniao_id == reuniao_id,
            CelulaExpectativaVisitante.pessoa_id == pessoa_id,
        )
        .order_by(CelulaExpectativaVisitante.created_at.asc())
    ).scalars().all()
    return [r.nome_visitante for r in rows]


# ---------------------------------------------------------------------------
# GET /cells/me/next-meeting
# ---------------------------------------------------------------------------
@router.get("/cells/me/next-meeting", response_model=NextMeetingResponse)
def get_my_next_meeting(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> NextMeetingResponse:
    """Próxima reunião FUTURA da célula do discípulo, ou ``meeting: null``.

    "Sem célula" ou "sem ocorrência futura" são estados válidos do discípulo
    (4.1/4.3b) e retornam ``meeting: null`` (não erro). "Futura" segue E4
    (``America/Sao_Paulo``): a mais próxima ocorrência ainda não ocorrida.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    pessoa_id = _require_pessoa(db, current_user)
    if pessoa_id is None:
        return NextMeetingResponse(meeting=None)

    cell_id = _active_cell_id(db, igreja_id, pessoa_id)
    if cell_id is None:
        return NextMeetingResponse(meeting=None)

    # Ordena ascendente e pega a 1ª ocorrência que ainda não passou (E4).
    rows = db.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.celula_id == cell_id,
            CelulaReuniao.igreja_id == igreja_id,
        )
        .order_by(CelulaReuniao.data.asc(), CelulaReuniao.hora.asc())
    ).scalars().all()

    next_reuniao = next(
        (r for r in rows if not meeting_has_passed(data=r.data, hora=r.hora)),
        None,
    )
    if next_reuniao is None:
        return NextMeetingResponse(meeting=None)

    # `local` deriva do endereço da célula (leitura permitida ao discípulo, CA-9);
    # a reunião não tem local próprio no modelo.
    cell = db.execute(
        select(Celula).where(
            Celula.id == cell_id, Celula.igreja_id == igreja_id
        )
    ).scalar_one_or_none()
    local = cell.endereco if cell is not None else None

    # Presença do próprio membro nesta reunião (E5) — inicializa o botão na UI.
    presenca = _find_presenca(db, igreja_id, next_reuniao.id, pessoa_id)
    minha_presenca = _map_minha_presenca(
        presenca.estado if presenca is not None else None
    )

    return NextMeetingResponse(
        meeting=NextMeetingBody(
            id=str(next_reuniao.id),
            celula_id=str(next_reuniao.celula_id),
            data=next_reuniao.data.isoformat(),
            hora=next_reuniao.hora,
            local=local,
            tema=next_reuniao.tema,
            minha_presenca=minha_presenca,
        )
    )


# ---------------------------------------------------------------------------
# GET /cells/me/notices
# ---------------------------------------------------------------------------
@router.get("/cells/me/notices", response_model=list[NoticeOut])
def get_my_notices(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[NoticeOut]:
    """Avisos ativos que o discípulo pode ler: da igreja + da SUA célula.

    Escopo 'igreja' (broadcast) sempre; escopo 'celula' só da célula ativa do
    membro. Apenas ``ativo=true``. Sem dados de gestão/terceiros.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    cell_id: uuid.UUID | None = None
    pessoa_id = _require_pessoa(db, current_user)
    if pessoa_id is not None:
        cell_id = _active_cell_id(db, igreja_id, pessoa_id)

    rows = db.execute(
        select(CelulaAviso)
        .where(
            CelulaAviso.igreja_id == igreja_id,
            CelulaAviso.ativo.is_(True),
        )
        .order_by(CelulaAviso.publicado_em.desc())
    ).scalars().all()

    visible: list[NoticeOut] = []
    for a in rows:
        # Igreja: todos veem. Célula: só a própria célula ativa do membro.
        if a.escopo == "igreja":
            pass
        elif a.escopo == "celula" and cell_id is not None and a.celula_id == cell_id:
            pass
        else:
            continue
        visible.append(
            NoticeOut(
                id=str(a.id),
                origem=a.origem,
                escopo=a.escopo,
                titulo=a.titulo,
                conteudo=a.conteudo,
                publicado_em=a.publicado_em.isoformat(),
            )
        )
    return visible


# ---------------------------------------------------------------------------
# GET /cells/me/history
# ---------------------------------------------------------------------------
@router.get("/cells/me/history", response_model=HistoryPage)
def get_my_history(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(
        default=DEFAULT_HISTORY_PAGE_SIZE,
        ge=1,
        le=MAX_HISTORY_PAGE_SIZE,
        description="Items per page (max 100)",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> HistoryPage:
    """Histórico paginado das reuniões PASSADAS do membro (projeção mínima).

    Por reunião devolve APENAS ``data``, ``tema``, ``minha_presenca`` (E5) e
    ``meus_visitantes_indicados`` (só os do próprio membro). NUNCA expõe
    decisões/oração/relatório da reunião nem presença de terceiros (RF-05/RF-30).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    empty = HistoryPage(items=[], page=page, page_size=page_size, total=0)
    pessoa_id = _require_pessoa(db, current_user)
    if pessoa_id is None:
        return empty
    cell_id = _active_cell_id(db, igreja_id, pessoa_id)
    if cell_id is None:
        return empty

    rows = db.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.celula_id == cell_id,
            CelulaReuniao.igreja_id == igreja_id,
        )
        .order_by(CelulaReuniao.data.desc(), CelulaReuniao.hora.desc())
    ).scalars().all()

    # "Passada" no fuso America/Sao_Paulo (E4). Mais recentes primeiro.
    past = [r for r in rows if meeting_has_passed(data=r.data, hora=r.hora)]
    total = len(past)
    start = (page - 1) * page_size
    window = past[start : start + page_size]

    items: list[HistoryItem] = []
    for r in window:
        presenca = _find_presenca(db, igreja_id, r.id, pessoa_id)
        estado = presenca.estado if presenca is not None else None
        items.append(
            HistoryItem(
                data=r.data.isoformat(),
                tema=r.tema,
                minha_presenca=_map_minha_presenca(estado),
                meus_visitantes_indicados=_my_visitor_names(
                    db, igreja_id, r.id, pessoa_id
                ),
            )
        )
    return HistoryPage(items=items, page=page, page_size=page_size, total=total)


# ---------------------------------------------------------------------------
# POST /cell-meetings/{id}/attendance/confirm
# ---------------------------------------------------------------------------
@router.post(
    "/cell-meetings/{reuniao_id}/attendance/confirm",
    response_model=AttendanceOut,
)
def confirm_my_attendance(
    reuniao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AttendanceOut:
    """Confirma a PRÓPRIA presença na reunião (1 toque, idempotente).

    - 404 se a reunião não existe no tenant (não há reunião futura materializada);
    - 403 se o app_user não tem Pessoa ou não tem vínculo ativo na célula (E11);
    - 409 se a reunião JÁ ocorreu no fuso America/Sao_Paulo (E4);
    - senão grava ``estado='confirmada'``/``origem='auto'`` (upsert) e responde 200.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)

    pessoa_id = _require_pessoa(db, current_user)
    if pessoa_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu usuário não está vinculado a uma pessoa",
        )
    if not _has_active_membership(db, igreja_id, reuniao.celula_id, pessoa_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem vínculo ativo na célula desta reunião",
        )
    if meeting_has_passed(data=reuniao.data, hora=reuniao.hora):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A reunião já ocorreu; não é possível confirmar presença",
        )

    existing = _find_presenca(db, igreja_id, reuniao.id, pessoa_id)
    if existing is not None:
        existing.estado = ESTADO_CONFIRMADA
        existing.origem = ORIGEM_AUTO
        existing.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        db.refresh(existing)
        db.commit()
        return AttendanceOut(
            reuniao_id=str(reuniao.id),
            minha_presenca=_map_minha_presenca(existing.estado),
        )

    presenca = CelulaPresenca(
        igreja_id=igreja_id,
        reuniao_id=reuniao.id,
        pessoa_id=pessoa_id,
        estado=ESTADO_CONFIRMADA,
        origem=ORIGEM_AUTO,
    )
    db.add(presenca)
    try:
        db.flush()
        db.refresh(presenca)
        db.commit()
    except IntegrityError:
        # Corrida no UNIQUE (igreja_id, reuniao_id, pessoa_id): recupera e aplica
        # last-write-wins; presença é SEMPRE 200 (nunca 409 por duplicidade).
        db.rollback()
        recovered = _find_presenca(db, igreja_id, reuniao.id, pessoa_id)
        if recovered is None:
            logger.error(
                "IntegrityError ao confirmar presença sem linha recuperável "
                "(reuniao=%s pessoa=%s)",
                reuniao.id,
                pessoa_id,
            )
            raise
        recovered.estado = ESTADO_CONFIRMADA
        recovered.origem = ORIGEM_AUTO
        recovered.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        db.refresh(recovered)
        db.commit()
        return AttendanceOut(
            reuniao_id=str(reuniao.id),
            minha_presenca=_map_minha_presenca(recovered.estado),
        )

    return AttendanceOut(
        reuniao_id=str(reuniao.id),
        minha_presenca=_map_minha_presenca(presenca.estado),
    )


# ---------------------------------------------------------------------------
# DELETE /cell-meetings/{id}/attendance/confirm
# ---------------------------------------------------------------------------
@router.delete(
    "/cell-meetings/{reuniao_id}/attendance/confirm",
    response_model=AttendanceOut,
)
def revert_my_attendance(
    reuniao_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AttendanceOut:
    """Reverte a confirmação da própria presença — enquanto a reunião não ocorreu.

    - 404 se a reunião não existe no tenant;
    - 403 se o app_user não tem Pessoa;
    - 409 se a reunião JÁ ocorreu (E4) — não se reverte presença de reunião passada;
    - senão remove a linha de presença do membro (idempotente) e responde 200 com
      ``minha_presenca='nao_confirmou'``.
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)

    pessoa_id = _require_pessoa(db, current_user)
    if pessoa_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu usuário não está vinculado a uma pessoa",
        )
    if meeting_has_passed(data=reuniao.data, hora=reuniao.hora):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A reunião já ocorreu; não é possível reverter a presença",
        )

    existing = _find_presenca(db, igreja_id, reuniao.id, pessoa_id)
    if existing is not None:
        db.delete(existing)
        db.flush()
        db.commit()

    return AttendanceOut(
        reuniao_id=str(reuniao.id),
        minha_presenca=_PRESENCE_NONE,
    )


# ---------------------------------------------------------------------------
# POST /cell-meetings/{id}/visitor-expectations
# ---------------------------------------------------------------------------
@router.post(
    "/cell-meetings/{reuniao_id}/visitor-expectations",
    response_model=VisitorExpectationOut,
    status_code=status.HTTP_201_CREATED,
)
def indicate_my_visitor(
    reuniao_id: str,
    payload: RegisterExpectativaRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> VisitorExpectationOut:
    """Registra a expectativa nominal de um visitante do PRÓPRIO membro (201).

    Reusa a tabela ``celula_expectativa_visitante`` (PR2). Sempre da própria
    pessoa; permite N registros por reunião.

    - 404 se a reunião não existe no tenant (sem reunião futura);
    - 422 para nome inválido (validação de borda no Pydantic);
    - 403 sem Pessoa vinculada ou sem vínculo ativo na célula da reunião (E11).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)
    reuniao = _get_reuniao_or_404(db, reuniao_id, igreja_id)

    pessoa_id = _require_pessoa(db, current_user)
    if pessoa_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu usuário não está vinculado a uma pessoa",
        )
    if not _has_active_membership(db, igreja_id, reuniao.celula_id, pessoa_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem vínculo ativo na célula desta reunião",
        )

    expectativa = CelulaExpectativaVisitante(
        igreja_id=igreja_id,
        reuniao_id=reuniao.id,
        pessoa_id=pessoa_id,
        nome_visitante=payload.nomeVisitante,
        observacao_oracao=payload.observacaoOracao,
    )
    db.add(expectativa)
    db.flush()
    db.refresh(expectativa)
    db.commit()

    return VisitorExpectationOut(
        id=str(expectativa.id),
        reuniao_id=str(expectativa.reuniao_id),
        nome_visitante=expectativa.nome_visitante,
        observacao_oracao=expectativa.observacao_oracao,
    )

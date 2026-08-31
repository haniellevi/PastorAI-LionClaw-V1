"""Cálculo ON-READ da saúde das células (Células PR3-PR9, US-18/RF-22, E6).

Sem materialização: a saúde é recalculada a cada leitura sobre as ÚLTIMAS 10
reuniões materializadas (linhas em ``celula_reuniao``) de cada célula, aplicando
três sinais e as definições operacionais E6:

  1. vermelho  — reunião PASSADA com relatório não enviado (pendente/ausente);
  2. alerta    — reunião REALIZADA (passada + relatório enviado) com presença
                 < 50% dos membros ativos (não se aplica se membros ativos = 0);
  3. alerta de evangelismo — 3 reuniões passadas CONSECUTIVAS sem visitante
                 esperado nem registrado.

Definições E6:
  - *reunião passada* = ``data < hoje`` (America/Sao_Paulo) OU ``data = hoje`` com
    ``hora`` preenchida e já vencida (reuso de ``meeting_has_passed``);
  - *reunião realizada* = passada com ``relatorio_status='enviado'``;
  - reuniões ``status='cancelada'`` são EXCLUÍDAS do cálculo;
  - *membros ativos* = ``celula_membro.ativo=true`` no momento da consulta;
  - < 10 reuniões → calcula sobre as disponíveis; 0 reuniões → ``status='sem_dados'``.

Ordenação das células: ``vermelhos DESC``, ``alertas DESC``, ``celula_nome ASC``.
Módulo puro de leitura: não escreve nada; ``now`` injetável para testes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Celula,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
    CelulaVisitante,
)
from app.domain.cell_report_snapshot import (
    has_cell_report_snapshot_schema_marker,
    validate_cell_report_snapshot_v2,
)
from app.domain.cell_meetings_schedule import meeting_has_passed

# Cores dos sinais (bolinhas) por reunião.
COR_VERDE = "verde"
COR_VERMELHO = "vermelho"
COR_ALERTA = "alerta"

# Status agregado da célula.
STATUS_OK = "ok"
STATUS_SEM_DADOS = "sem_dados"

# Estados/constantes de domínio reusados (espelham cell_meetings.py).
STATUS_CANCELADA = "cancelada"
RELATORIO_ENVIADO = "enviado"
ESTADO_COMPARECEU = "compareceu"

# Parâmetros do cálculo (E6).
HEALTH_WINDOW = 10
EVANGELISM_STREAK = 3
ATTENDANCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class HealthSignal:
    """Sinal (bolinha) de uma reunião: cor verde|vermelho|alerta."""

    reuniao_id: str
    cor: str


@dataclass
class CellHealth:
    """Saúde agregada de uma célula (até 10 sinais + contadores)."""

    celula_id: str
    celula_nome: str
    status: str
    sinais: list[HealthSignal] = field(default_factory=list)
    vermelhos: int = 0
    alertas: int = 0


# ---------------------------------------------------------------------------
# Pré-carregamento em lote
# ---------------------------------------------------------------------------
def _load_health_data(
    db: Session,
    igreja_id: uuid.UUID,
    cells: list[Celula],
) -> tuple[
    dict[uuid.UUID, list[CelulaReuniao]],
    Counter[uuid.UUID],
    Counter[uuid.UUID],
    set[uuid.UUID],
]:
    """Carrega todos os insumos de saúde em cinco consultas constantes.

    ``row_number`` limita no banco as 10 reuniões não canceladas de cada
    célula. As demais consultas devolvem contagens agrupadas de membros e
    presenças, mais IDs distintos de reuniões com visitante — nunca os ORM rows
    completos dessas tabelas.
    """
    cell_ids = tuple(cell.id for cell in cells)
    if not cell_ids:
        return {}, Counter(), Counter(), set()

    meeting_rank = func.row_number().over(
        partition_by=CelulaReuniao.celula_id,
        order_by=(CelulaReuniao.data.desc(), CelulaReuniao.hora.desc()),
    ).label("health_rank")
    ranked_meetings = (
        select(
            CelulaReuniao.id.label("reuniao_id"),
            meeting_rank,
        )
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.celula_id.in_(cell_ids),
            CelulaReuniao.status != STATUS_CANCELADA,
        )
        .subquery()
    )
    meeting_rows = db.execute(
        select(CelulaReuniao)
        .join(
            ranked_meetings,
            CelulaReuniao.id == ranked_meetings.c.reuniao_id,
        )
        .where(ranked_meetings.c.health_rank <= HEALTH_WINDOW)
        .order_by(
            CelulaReuniao.celula_id.asc(),
            CelulaReuniao.data.desc(),
            CelulaReuniao.hora.desc(),
        )
    ).scalars().all()

    meetings_by_cell: defaultdict[uuid.UUID, list[CelulaReuniao]] = defaultdict(
        list
    )
    for meeting in meeting_rows:
        meetings_by_cell[meeting.celula_id].append(meeting)

    member_count_rows = db.execute(
        select(
            CelulaMembro.celula_id,
            func.count(CelulaMembro.id),
        )
        .where(
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.celula_id.in_(cell_ids),
            CelulaMembro.ativo.is_(True),
        )
        .group_by(CelulaMembro.celula_id)
    ).all()
    active_members_by_cell = Counter(
        {celula_id: count for celula_id, count in member_count_rows}
    )

    meeting_ids = tuple(meeting.id for meeting in meeting_rows)
    attendance_count_rows = db.execute(
        select(
            CelulaPresenca.reuniao_id,
            func.count(CelulaPresenca.id),
        )
        .where(
            CelulaPresenca.igreja_id == igreja_id,
            CelulaPresenca.reuniao_id.in_(meeting_ids),
            CelulaPresenca.estado == ESTADO_COMPARECEU,
        )
        .group_by(CelulaPresenca.reuniao_id)
    ).all()
    attendance_by_meeting = Counter(
        {reuniao_id: count for reuniao_id, count in attendance_count_rows}
    )

    expected_visitor_meeting_ids = db.execute(
        select(CelulaExpectativaVisitante.reuniao_id)
        .where(
            CelulaExpectativaVisitante.igreja_id == igreja_id,
            CelulaExpectativaVisitante.reuniao_id.in_(meeting_ids),
        )
        .distinct()
    ).scalars().all()
    registered_visitor_meeting_ids = db.execute(
        select(CelulaVisitante.reuniao_id)
        .where(
            CelulaVisitante.igreja_id == igreja_id,
            CelulaVisitante.reuniao_id.in_(meeting_ids),
        )
        .distinct()
    ).scalars().all()
    meetings_with_visitor = set(expected_visitor_meeting_ids) | set(
        registered_visitor_meeting_ids
    )

    # Um relatório agregado v2 enviado é a foto canônica da reunião. Ele não
    # materializa pessoas individuais, portanto as contagens ao vivo seriam
    # zero e produziriam alertas falsos. Para v2, os totals validados substituem
    # presença e existência de visitante. Marcador v2 malformado falha fechado;
    # nunca recua silenciosamente para os fatos individuais.
    for meeting in meeting_rows:
        snapshot = getattr(meeting, "relatorio_snapshot", None)
        if (
            meeting.relatorio_status != RELATORIO_ENVIADO
            or not has_cell_report_snapshot_schema_marker(snapshot)
        ):
            continue
        aggregate = validate_cell_report_snapshot_v2(snapshot)
        attendance_by_meeting[meeting.id] = aggregate.totals.presentes
        if aggregate.totals.visitantes > 0:
            meetings_with_visitor.add(meeting.id)
        else:
            meetings_with_visitor.discard(meeting.id)

    return (
        dict(meetings_by_cell),
        active_members_by_cell,
        attendance_by_meeting,
        meetings_with_visitor,
    )


# ---------------------------------------------------------------------------
# Núcleo puro do cálculo por célula
# ---------------------------------------------------------------------------
def _compute_cell_health_from_data(
    cell: Celula,
    meetings: list[CelulaReuniao],
    *,
    members_active: int,
    attendance_by_meeting: Counter[uuid.UUID],
    meetings_with_visitor: set[uuid.UUID],
    now: dt.datetime | None = None,
) -> CellHealth:
    """Aplica as regras E6 a dados já carregados, sem acesso ao banco."""
    # Defesa adicional para manter a semântica mesmo se outro loader reutilizar
    # este núcleo no futuro. O loader atual já filtra e limita no SQL.
    considered = [
        meeting for meeting in meetings if meeting.status != STATUS_CANCELADA
    ][:HEALTH_WINDOW]
    if not considered:
        return CellHealth(
            celula_id=str(cell.id),
            celula_nome=cell.nome,
            status=STATUS_SEM_DADOS,
            sinais=[],
            vermelhos=0,
            alertas=0,
        )

    # Timeline cronológica (mais antiga → mais recente) para bolinhas e streak.
    chrono = list(reversed(considered))

    sinais: list[HealthSignal] = []
    vermelhos = 0
    alertas = 0
    for r in chrono:
        passed = meeting_has_passed(data=r.data, hora=r.hora, now=now)
        cor = COR_VERDE
        if passed and r.relatorio_status != RELATORIO_ENVIADO:
            # Sinal 1 — relatório pendente/ausente em reunião passada.
            cor = COR_VERMELHO
            vermelhos += 1
        elif (
            passed
            and r.relatorio_status == RELATORIO_ENVIADO
            and members_active > 0
        ):
            # Sinal 2 — presença < 50% dos membros ativos em reunião realizada.
            compareceu = attendance_by_meeting[r.id]
            if compareceu < members_active * ATTENDANCE_THRESHOLD:
                cor = COR_ALERTA
                alertas += 1
        sinais.append(HealthSignal(reuniao_id=str(r.id), cor=cor))

    # Sinal 3 — 3 reuniões passadas consecutivas sem visitante (esperado/registrado).
    passadas = [
        r for r in chrono if meeting_has_passed(data=r.data, hora=r.hora, now=now)
    ]
    streak = 0
    evangelism_alert = False
    for r in passadas:
        if r.id in meetings_with_visitor:
            streak = 0
        else:
            streak += 1
            if streak >= EVANGELISM_STREAK:
                evangelism_alert = True
                break
    if evangelism_alert:
        alertas += 1

    return CellHealth(
        celula_id=str(cell.id),
        celula_nome=cell.nome,
        status=STATUS_OK,
        sinais=sinais,
        vermelhos=vermelhos,
        alertas=alertas,
    )


def compute_cell_health(
    db: Session,
    igreja_id: uuid.UUID,
    cell: Celula,
    *,
    now: dt.datetime | None = None,
) -> CellHealth:
    """Saúde de uma célula sobre as últimas 10 reuniões não canceladas (E6)."""
    (
        meetings_by_cell,
        active_members_by_cell,
        attendance_by_meeting,
        meetings_with_visitor,
    ) = _load_health_data(db, igreja_id, [cell])
    return _compute_cell_health_from_data(
        cell,
        meetings_by_cell.get(cell.id, []),
        members_active=active_members_by_cell[cell.id],
        attendance_by_meeting=attendance_by_meeting,
        meetings_with_visitor=meetings_with_visitor,
        now=now,
    )


# ---------------------------------------------------------------------------
# Cálculo para toda a igreja (ordenado menos saudável primeiro)
# ---------------------------------------------------------------------------
def compute_cells_health(
    db: Session,
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime | None = None,
) -> list[CellHealth]:
    """Saúde de todas as células ATIVAS da igreja, menos saudáveis primeiro.

    Ordenação E6: ``vermelhos DESC``, ``alertas DESC``, ``celula_nome ASC``.
    """
    cells = db.execute(
        select(Celula)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.ativo.is_(True),
        )
        .order_by(Celula.nome.asc())
    ).scalars().all()

    (
        meetings_by_cell,
        active_members_by_cell,
        attendance_by_meeting,
        meetings_with_visitor,
    ) = _load_health_data(db, igreja_id, cells)
    healths = [
        _compute_cell_health_from_data(
            cell,
            meetings_by_cell.get(cell.id, []),
            members_active=active_members_by_cell[cell.id],
            attendance_by_meeting=attendance_by_meeting,
            meetings_with_visitor=meetings_with_visitor,
            now=now,
        )
        for cell in cells
    ]
    healths.sort(
        key=lambda h: (-h.vermelhos, -h.alertas, h.celula_nome)
    )
    return healths

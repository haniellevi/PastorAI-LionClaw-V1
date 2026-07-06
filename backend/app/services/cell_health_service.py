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
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Celula,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
    CelulaVisitante,
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
# Consultas auxiliares (contadas em Python p/ compat com o harness de testes)
# ---------------------------------------------------------------------------
def _active_members_count(
    db: Session, igreja_id: uuid.UUID, celula_id: uuid.UUID
) -> int:
    rows = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.celula_id == celula_id,
            CelulaMembro.ativo.is_(True),
        )
    ).scalars().all()
    return len(rows)


def _attendance_count(
    db: Session, igreja_id: uuid.UUID, reuniao_id: uuid.UUID
) -> int:
    rows = db.execute(
        select(CelulaPresenca).where(
            CelulaPresenca.igreja_id == igreja_id,
            CelulaPresenca.reuniao_id == reuniao_id,
            CelulaPresenca.estado == ESTADO_COMPARECEU,
        )
    ).scalars().all()
    return len(rows)


def _has_visitor(
    db: Session, igreja_id: uuid.UUID, reuniao_id: uuid.UUID
) -> bool:
    """True se a reunião teve visitante ESPERADO ou REGISTRADO (sinal 3)."""
    expected = db.execute(
        select(CelulaExpectativaVisitante).where(
            CelulaExpectativaVisitante.igreja_id == igreja_id,
            CelulaExpectativaVisitante.reuniao_id == reuniao_id,
        )
    ).scalars().first()
    if expected is not None:
        return True
    registered = db.execute(
        select(CelulaVisitante).where(
            CelulaVisitante.igreja_id == igreja_id,
            CelulaVisitante.reuniao_id == reuniao_id,
        )
    ).scalars().first()
    return registered is not None


# ---------------------------------------------------------------------------
# Cálculo por célula
# ---------------------------------------------------------------------------
def compute_cell_health(
    db: Session,
    igreja_id: uuid.UUID,
    cell: Celula,
    *,
    now: dt.datetime | None = None,
) -> CellHealth:
    """Saúde de uma célula sobre as últimas 10 reuniões não canceladas (E6)."""
    rows = db.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.celula_id == cell.id,
        )
        .order_by(CelulaReuniao.data.desc(), CelulaReuniao.hora.desc())
    ).scalars().all()

    # Exclui canceladas e limita à janela das 10 mais recentes.
    considered = [r for r in rows if r.status != STATUS_CANCELADA][:HEALTH_WINDOW]
    if not considered:
        return CellHealth(
            celula_id=str(cell.id),
            celula_nome=cell.nome,
            status=STATUS_SEM_DADOS,
            sinais=[],
            vermelhos=0,
            alertas=0,
        )

    members_active = _active_members_count(db, igreja_id, cell.id)

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
            compareceu = _attendance_count(db, igreja_id, r.id)
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
        if _has_visitor(db, igreja_id, r.id):
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

    healths = [
        compute_cell_health(db, igreja_id, c, now=now) for c in cells
    ]
    healths.sort(
        key=lambda h: (-h.vermelhos, -h.alertas, h.celula_nome)
    )
    return healths

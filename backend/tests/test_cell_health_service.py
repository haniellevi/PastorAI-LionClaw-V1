"""Testes unitários do cálculo ON-READ de saúde das células (Células PR3-PR9, E6).

Exercita ``cell_health_service`` diretamente sobre a sessão fake em memória
(``CellSession``), sem HTTP nem Postgres. Datas em extremos (2000 = passada;
2999 = futura) tornam ``meeting_has_passed`` (relógio real) determinista.

Cobre os três sinais E6, o status ``sem_dados``, a janela de 10 reuniões, a
exclusão de canceladas e a ordenação (vermelhos DESC, alertas DESC, nome ASC).
"""

from __future__ import annotations

import uuid

from app.services.cell_health_service import (
    COR_ALERTA,
    COR_VERDE,
    COR_VERMELHO,
    STATUS_OK,
    STATUS_SEM_DADOS,
    compute_cell_health,
    compute_cells_health,
)
from tests.cell_backend_fakes import (
    CELL,
    CELL2,
    FUTURE,
    PAST,
    TENANT,
    CellSession,
    make_app_user,
    make_cell,
    make_expectativa,
    make_member,
    make_presenca,
    make_reuniao,
)

_IGREJA = uuid.UUID(TENANT)


def _session(**kwargs) -> CellSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["pastor"])
    return CellSession(**kwargs)


# ===========================================================================
# sem_dados
# ===========================================================================
def test_no_meetings_is_sem_dados() -> None:
    session = _session(reunioes=[])
    health = compute_cell_health(session, _IGREJA, make_cell())
    assert health.status == STATUS_SEM_DADOS
    assert health.sinais == []
    assert health.vermelhos == 0
    assert health.alertas == 0


def test_only_future_meetings_are_all_green() -> None:
    reu = make_reuniao(reuniao_id="r-fut", data=FUTURE, relatorio_status="pendente")
    session = _session(reunioes=[reu])
    health = compute_cell_health(session, _IGREJA, make_cell())
    assert health.status == STATUS_OK
    assert [s.cor for s in health.sinais] == [COR_VERDE]
    assert health.vermelhos == 0


# ===========================================================================
# Sinal 1 — vermelho (relatório pendente em reunião passada)
# ===========================================================================
def test_past_meeting_without_report_is_red() -> None:
    reu = make_reuniao(
        reuniao_id="r-red", data=PAST, hora="19:30", relatorio_status="pendente"
    )
    session = _session(reunioes=[reu])
    health = compute_cell_health(session, _IGREJA, make_cell())
    assert health.vermelhos == 1
    assert health.sinais[0].cor == COR_VERMELHO


def test_cancelled_meetings_are_excluded() -> None:
    cancelada = make_reuniao(
        reuniao_id="r-cancel",
        data=PAST,
        relatorio_status="pendente",
        status="cancelada",
    )
    session = _session(reunioes=[cancelada])
    health = compute_cell_health(session, _IGREJA, make_cell())
    # Só havia uma reunião e ela é cancelada → sem dados considerados.
    assert health.status == STATUS_SEM_DADOS
    assert health.vermelhos == 0


# ===========================================================================
# Sinal 2 — alerta de presença (< 50% dos membros ativos)
# ===========================================================================
def test_low_attendance_realized_meeting_is_alerta() -> None:
    reu = make_reuniao(
        reuniao_id="r-att", data=PAST, hora="19:30", relatorio_status="enviado"
    )
    membros = [
        make_member(pessoa_id="p1", ativo=True),
        make_member(pessoa_id="p2", ativo=True),
    ]
    # 0 presenças 'compareceu' → 0 < 2 * 0.5 = 1 → alerta.
    session = _session(reunioes=[reu], membros=membros, presencas=[])
    health = compute_cell_health(session, _IGREJA, make_cell())
    assert health.alertas == 1
    assert health.sinais[0].cor == COR_ALERTA
    assert health.vermelhos == 0


def test_good_attendance_realized_meeting_is_green() -> None:
    reu = make_reuniao(
        reuniao_id="r-ok", data=PAST, hora="19:30", relatorio_status="enviado"
    )
    membros = [
        make_member(pessoa_id="p1", ativo=True),
        make_member(pessoa_id="p2", ativo=True),
    ]
    presencas = [
        make_presenca(reuniao_id="r-ok", pessoa_id="p1", estado="compareceu"),
        make_presenca(reuniao_id="r-ok", pessoa_id="p2", estado="compareceu"),
    ]
    session = _session(reunioes=[reu], membros=membros, presencas=presencas)
    health = compute_cell_health(session, _IGREJA, make_cell())
    assert health.alertas == 0
    assert health.sinais[0].cor == COR_VERDE


def test_attendance_signal_skipped_when_no_active_members() -> None:
    reu = make_reuniao(
        reuniao_id="r-nomembers",
        data=PAST,
        hora="19:30",
        relatorio_status="enviado",
    )
    session = _session(reunioes=[reu], membros=[], presencas=[])
    health = compute_cell_health(session, _IGREJA, make_cell())
    # Sem membros ativos o sinal 2 não se aplica → verde, sem alerta.
    assert health.alertas == 0
    assert health.sinais[0].cor == COR_VERDE


# ===========================================================================
# Sinal 3 — alerta de evangelismo (3 passadas consecutivas sem visitante)
# ===========================================================================
def test_three_consecutive_meetings_without_visitor_is_evangelism_alerta() -> None:
    reunioes = [
        make_reuniao(
            reuniao_id=f"r{i}", data=PAST, hora=f"1{i}:00", relatorio_status="enviado"
        )
        for i in range(1, 4)
    ]
    session = _session(reunioes=reunioes, membros=[], expectativas=[], visitantes=[])
    health = compute_cell_health(session, _IGREJA, make_cell())
    # Nenhum vermelho (enviado) e sem membros → sinais verdes; +1 alerta de
    # evangelismo pela sequência de 3 sem visitante.
    assert health.vermelhos == 0
    assert health.alertas == 1
    assert all(s.cor == COR_VERDE for s in health.sinais)


def test_visitor_breaks_evangelism_streak() -> None:
    reunioes = [
        make_reuniao(
            reuniao_id=f"r{i}", data=PAST, hora=f"1{i}:00", relatorio_status="enviado"
        )
        for i in range(1, 4)
    ]
    # Visitante esperado na reunião do meio quebra a sequência.
    expectativas = [make_expectativa(reuniao_id="r2")]
    session = _session(reunioes=reunioes, membros=[], expectativas=expectativas)
    health = compute_cell_health(session, _IGREJA, make_cell())
    assert health.alertas == 0


# ===========================================================================
# compute_cells_health — ordenação menos saudável primeiro
# ===========================================================================
def test_cells_ordered_least_healthy_first() -> None:
    cell_a = make_cell(cell_id=CELL, nome="A")
    cell_b = make_cell(cell_id=CELL2, nome="B")
    # Célula A tem 1 vermelho; célula B está sem dados.
    red = make_reuniao(
        reuniao_id="r-a", celula_id=CELL, data=PAST, relatorio_status="pendente"
    )
    session = _session(cells=[cell_a, cell_b], reunioes=[red])
    healths = compute_cells_health(session, _IGREJA)
    assert [h.celula_id for h in healths] == [CELL, CELL2]
    assert healths[0].vermelhos == 1
    assert healths[1].status == STATUS_SEM_DADOS

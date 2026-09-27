"""Independent paid-extraction boundary using the real worker and fake LLM."""
from __future__ import annotations

import pytest

from app.db.models import (AgentActionProposal, AgentActionReceipt, AppUser,
    CellReportAiReservation, CellReportDraft, Conversation)
from app.services import llm
from tests.test_cell_report_v1a_worker_pg import (  # noqa: F401
    report_turn, _run, _snapshot, _ClassifiedEvolution, _rows, _IGREJA,
    _inbound, msg_engine_fx, rls_database_url, s3_turn, worker_module,
)

pytestmark = pytest.mark.rls_integration
_WORDS = 'Relatório: presentes: dez; visitantes: dois; decisões: uma; oferta: trinta reais'
_PAYLOAD = {'presentes': 10, 'visitantes': 2, 'decisoes': 1, 'oferta_centavos': 3000}


def _fake_extractor(turn, monkeypatch, *, during_call=None, payload=None, mode='ok'):
    calls = []
    monkeypatch.setattr(llm, 'estimate_cost', lambda _m, incoming, outgoing: (incoming + outgoing) / 1_000_000)
    def extract(_self, projection, *, timeout_seconds):
        assert turn.engine.pool.checkedout() == 0
        reservations = _rows(turn, CellReportAiReservation)
        assert sum(r.state == 'reservada' for r in reservations) == 1
        assert all(r.estimated_microusd > 0 for r in reservations)
        assert set(projection) <= {'presentes', 'visitantes', 'decisoes', 'oferta'}
        assert 'Zeta' not in repr(projection) and 'Rua' not in repr(projection)
        assert 0 < timeout_seconds <= 9
        calls.append(dict(projection))
        if during_call is not None:
            during_call()
        if mode == 'timeout':
            raise llm.LLMError('Prazo LLM excedido')
        usage = None if mode == 'missing_usage' else llm.LLMUsage(
            modelo='gpt-5.6-luna', tokens_in=200, tokens_out=100, custo=0.0003)
        return llm.V1aCellReportExtractionResult(
            payload=dict(_PAYLOAD if payload is None else payload(projection) if callable(payload) else payload), usage=usage)
    monkeypatch.setattr(llm.LLMClient, 'extract_v1a_cell_report', extract, raising=False)
    return calls


def test_paid_extraction_commits_reservation_before_http_and_sends_only_aggregates(report_turn, monkeypatch):
    turn = report_turn
    calls = _fake_extractor(turn, monkeypatch)
    evolution = _ClassifiedEvolution()
    request = _run(turn, 'V1A-PAID-REPORT', _WORDS + '; Pessoa Sintética Zeta, Rua Sintética 42', evolution)
    assert calls == [{'presentes': 'dez', 'visitantes': 'dois', 'decisoes': 'uma', 'oferta': 'trinta reais'}]
    reservations = _rows(turn, CellReportAiReservation)
    assert len(reservations) == 1 and reservations[0].state == 'liquidada'
    assert reservations[0].actual_microusd == 300
    assert len(_rows(turn, AgentActionProposal)) == 1
    assert _snapshot(turn)[0] == 'pendente'
    worker_module.run_agent_for_message(turn.factory, request, evolution_client=evolution)
    assert len(calls) == 1
    _run(turn, 'V1A-PAID-SIM', 'SIM', evolution)
    assert _snapshot(turn)[0] == 'enviado'
    assert len(_rows(turn, AgentActionReceipt)) == 1


@pytest.mark.parametrize('mode', ('timeout', 'missing_usage', 'forged_field'))
def test_failed_paid_extraction_keeps_reservation_and_never_prepares_confirmation(report_turn, monkeypatch, mode):
    turn = report_turn
    payload = dict(_PAYLOAD, pessoa_id='synthetic-forbidden') if mode == 'forged_field' else None
    calls = _fake_extractor(turn, monkeypatch, mode=mode, payload=payload)
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-PAID-FAIL-' + mode, _WORDS, evolution)
    assert len(calls) == 1
    reservations = _rows(turn, CellReportAiReservation)
    assert len(reservations) == 1 and reservations[0].state == 'reservada'
    assert reservations[0].actual_microusd is None
    assert _rows(turn, AgentActionProposal) == []
    assert _rows(turn, AgentActionReceipt) == []
    assert _snapshot(turn)[0] == 'pendente'
    with turn.factory() as session:
        assert session.get(Conversation, turn.conversation_id).estado == 'humano'
    assert evolution.calls == []


def test_paid_extraction_discards_result_if_access_is_revoked_during_http(report_turn, monkeypatch):
    turn = report_turn
    def revoke():
        with turn.factory.begin() as session:
            session.get(AppUser, turn.app_user_id).status = 'inativo'
    calls = _fake_extractor(turn, monkeypatch, during_call=revoke)
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-PAID-REVOKED', _WORDS, evolution)
    assert len(calls) == 1
    assert _rows(turn, AgentActionProposal) == []
    assert _rows(turn, AgentActionReceipt) == []
    assert _snapshot(turn)[0] == 'pendente'
    assert evolution.calls == []


def test_spelled_correction_changes_only_the_explicit_aggregate(report_turn, monkeypatch):
    turn = report_turn
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-PAID-CORRECTION-START',
        'Relatório: presentes: 10; visitantes: 2; decisões: 1; oferta: 30,00', evolution)
    calls = _fake_extractor(turn, monkeypatch,
        payload={'presentes': 12, 'visitantes': None, 'decisoes': None, 'oferta_centavos': None})
    _run(turn, 'V1A-PAID-CORRECTION', 'Correção: presentes: doze', evolution)
    assert calls == [{'presentes': 'doze'}]
    pending = [p for p in _rows(turn, AgentActionProposal) if p.state == 'pendente']
    assert len(pending) == 1
    _run(turn, 'V1A-PAID-CORRECTED-SIM', 'SIM', evolution)
    from app.domain.cell_report_snapshot import validate_cell_report_snapshot_v2
    snapshot = validate_cell_report_snapshot_v2(_snapshot(turn)[1])
    assert (snapshot.totals.presentes, snapshot.totals.visitantes, snapshot.totals.decisoes) == (12, 2, 1)
    assert str(snapshot.oferta_valor) == '30.00'


def test_fifth_paid_extraction_is_denied_before_http(report_turn, monkeypatch):
    turn = report_turn
    numbers = {'dez': 10, 'doze': 12, 'treze': 13, 'quatorze': 14, 'quinze': 15}
    calls = _fake_extractor(turn, monkeypatch,
        payload=lambda projection: {'presentes': numbers[projection['presentes']],
            'visitantes': None, 'decisoes': None, 'oferta_centavos': None})
    evolution = _ClassifiedEvolution()
    for index, word in enumerate(numbers):
        prefix = 'Relatório' if index == 0 else 'Correção'
        _run(turn, f'V1A-PAID-CAP-{index}', f'{prefix}: presentes: {word}', evolution)
    assert len(calls) == 4
    assert len(_rows(turn, CellReportAiReservation)) == 4
    assert _rows(turn, AgentActionProposal) == []
    assert _snapshot(turn)[0] == 'pendente'


def test_unknown_cost_denies_paid_call_before_provider(report_turn, monkeypatch):
    turn = report_turn
    calls = _fake_extractor(turn, monkeypatch)
    monkeypatch.setattr(llm, 'estimate_cost', lambda *_: float('nan'))
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-PAID-UNKNOWN-COST', _WORDS, evolution)
    assert calls == []
    assert _rows(turn, CellReportAiReservation) == []
    assert _rows(turn, AgentActionProposal) == []
    assert evolution.calls == []


@pytest.mark.parametrize('correction,money_text,offer', ((False, '30,50', '30.50'), (False, '30 reais', '30.00'), (True, '35,50', '35.50')))
def test_mixed_numeric_and_spelled_values_keep_deterministic_fields_authoritative(report_turn, monkeypatch, correction, money_text, offer):
    turn = report_turn
    evolution = _ClassifiedEvolution()
    if correction:
        _run(turn, 'V1A-MIXED-START',
            'Relatório: presentes: 10; visitantes: 2; decisões: 1; oferta: 30,00', evolution)
        text = f'Correção: presentes: 12; visitantes: três; oferta: {money_text}'
        visitors, count, spelling = 3, 12, 'tres'
    else:
        text = f'Relatório: presentes: 10; visitantes: dois; decisões: 1; oferta: {money_text}'
        visitors, count, spelling = 2, 10, 'dois'
    calls = _fake_extractor(turn, monkeypatch,
        payload={'presentes': None, 'visitantes': visitors, 'decisoes': None, 'oferta_centavos': None})
    _run(turn, 'V1A-MIXED-EXTRACT', text, evolution)
    assert calls == [{'visitantes': spelling}]
    assert len(_rows(turn, CellReportAiReservation)) == 1
    assert len([p for p in _rows(turn, AgentActionProposal) if p.state == 'pendente']) == 1
    _run(turn, 'V1A-MIXED-SIM', 'SIM', evolution)
    from app.domain.cell_report_snapshot import validate_cell_report_snapshot_v2
    snapshot = validate_cell_report_snapshot_v2(_snapshot(turn)[1])
    assert (snapshot.totals.presentes, snapshot.totals.visitantes, snapshot.totals.decisoes) == (count, visitors, 1)
    assert str(snapshot.oferta_valor) == offer


@pytest.mark.parametrize('invalid_text', (
    'Relatório: presentes: 10; visitantes: dois; observação: Pessoa Sintética Zeta, Rua Sintética 42',
    'Relatório: presentes: -2; visitantes: dois',
))
def test_invalid_report_is_clarified_without_paid_extraction_or_partial_proposal(report_turn, monkeypatch, invalid_text):
    turn = report_turn
    calls = _fake_extractor(turn, monkeypatch)
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-PAID-INVALID-TEXT', invalid_text, evolution)
    assert calls == []
    assert _rows(turn, CellReportAiReservation) == []
    assert _rows(turn, AgentActionProposal) == []
    assert len(evolution.calls) == 1
    assert 'Envie apenas presentes, visitantes, decisões e oferta total.' in evolution.calls[0][2]
    assert 'Zeta' not in evolution.calls[0][2] and 'Rua' not in evolution.calls[0][2]


def test_expiry_during_extraction_records_one_paid_call_and_no_domain_effect(report_turn, monkeypatch):
    import datetime as dt
    from sqlalchemy import select
    from app.db.models import AiUsageLog
    turn = report_turn
    def expire():
        with turn.factory.begin() as session:
            draft = session.execute(select(CellReportDraft)).scalar_one()
            current = dt.datetime.now(dt.timezone.utc)
            draft.started_at = current - dt.timedelta(hours=1)
            draft.expires_at = current - dt.timedelta(seconds=1)
    calls = _fake_extractor(turn, monkeypatch, during_call=expire)
    evolution = _ClassifiedEvolution()
    _run(turn, 'V1A-PAID-EXPIRED', _WORDS, evolution)
    assert len(calls) == 1
    usages = _rows(turn, AiUsageLog)
    assert len(usages) == 1
    assert (usages[0].tokens_in, usages[0].tokens_out) == (200, 100)
    assert _rows(turn, AgentActionProposal) == []
    assert _rows(turn, AgentActionReceipt) == []
    assert _snapshot(turn)[0] == 'pendente'
    assert evolution.calls == []

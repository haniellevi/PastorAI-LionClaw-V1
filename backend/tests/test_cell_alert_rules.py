"""RF-26: unidade dos gatilhos de alerta ao líder (funções puras e gate)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.services import cell_alert_rules as svc

UTC = dt.timezone.utc
SP = svc.SAO_PAULO_TZ
CEL = uuid.uuid4()
PES = uuid.uuid4()


def test_five_initial_rules_with_defaults():
    assert set(svc.RULES) == {
        "visitante_novo",
        "liderado_em_consolidacao",
        "relatorio_pendente",
        "prazo_vencendo",
        "meta_atingida",
    }
    spec = svc.RULES["relatorio_pendente"]
    assert svc.default_params(spec) == {"horas_apos_reuniao": 24}


@pytest.mark.parametrize(
    "raw",
    [{"horas_apos_reuniao": 0}, {"horas_apos_reuniao": 169}, {"horas_apos_reuniao": "24"},
     {"horas_apos_reuniao": True}, {"outro": 3}, [1]],
)
def test_strict_params_refuse_invalid_values(raw):
    with pytest.raises(svc.CellAlertRuleError):
        svc.normalize_params(svc.RULES["relatorio_pendente"], raw, strict=True)


def test_lenient_params_fall_back_to_default_for_stored_garbage():
    spec = svc.RULES["meta_atingida"]
    assert svc.normalize_params(spec, {"meta_membros": 9999}, strict=False) == {"meta_membros": 12}
    assert svc.normalize_params(spec, None, strict=False) == {"meta_membros": 12}
    assert svc.normalize_params(spec, {"meta_membros": 20}, strict=True) == {"meta_membros": 20}


def test_rule_without_params_accepts_empty_only():
    spec = svc.RULES["liderado_em_consolidacao"]
    assert svc.normalize_params(spec, {}, strict=True) == {}
    with pytest.raises(svc.CellAlertRuleError):
        svc.normalize_params(spec, {"x": 1}, strict=True)


def test_visitante_inside_window_only():
    today = dt.date(2026, 11, 12)
    novo, velho, futuro = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        (novo, CEL, dt.date(2026, 11, 5)),
        (velho, CEL, dt.date(2026, 11, 4)),
        (futuro, CEL, dt.date(2026, 11, 13)),
    ]
    out = svc.visitante_candidates(rows, today=today, janela_dias=7)
    assert [c.fato_chave for c in out] == [str(novo)]
    assert out[0].pessoa_id is None and "05/11" in out[0].acao


def test_relatorio_pending_only_after_configured_hours():
    reuniao = uuid.uuid4()
    rows = [(reuniao, CEL, dt.date(2026, 11, 10), "20:00")]
    start = dt.datetime(2026, 11, 10, 20, 0, tzinfo=SP)
    before = svc.relatorio_candidates(rows, now=start + dt.timedelta(hours=23, minutes=59), horas_apos_reuniao=24)
    after = svc.relatorio_candidates(rows, now=start + dt.timedelta(hours=24), horas_apos_reuniao=24)
    assert before == []
    assert [c.fato_chave for c in after] == [str(reuniao)]


def test_meeting_without_time_counts_from_end_of_day():
    assert svc.meeting_start(dt.date(2026, 11, 10), None) == dt.datetime(2026, 11, 10, 23, 59, tzinfo=SP)
    assert svc.meeting_start(dt.date(2026, 11, 10), "25:00").hour == 23
    assert svc.meeting_start(dt.date(2026, 11, 10), "19:30").hour == 19


def test_prazo_inside_advance_window_and_overdue():
    now = dt.datetime(2026, 11, 12, 12, tzinfo=UTC)
    perto, vencido, longe = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        (perto, CEL, PES, now + dt.timedelta(hours=47)),
        (vencido, CEL, PES, now - dt.timedelta(hours=1)),
        (longe, CEL, PES, now + dt.timedelta(hours=49)),
    ]
    out = svc.prazo_candidates(rows, now=now, antecedencia_horas=48)
    assert {c.fato_chave.split(":")[0] for c in out} == {str(perto), str(vencido)}
    textos = {c.fato_chave.split(":")[0]: c.acao for c in out}
    assert "venceu" in textos[str(vencido)] and "vence em" in textos[str(perto)]


def test_prazo_rescheduled_is_a_new_fact():
    now = dt.datetime(2026, 11, 12, 12, tzinfo=UTC)
    cid = uuid.uuid4()
    a = svc.prazo_candidates([(cid, CEL, PES, now + dt.timedelta(hours=1))], now=now, antecedencia_horas=48)
    b = svc.prazo_candidates([(cid, CEL, PES, now + dt.timedelta(hours=2))], now=now, antecedencia_horas=48)
    assert a[0].fato_chave != b[0].fato_chave


def test_meta_reached_and_key_carries_goal():
    other = uuid.uuid4()
    out = svc.meta_candidates([(CEL, 12), (other, 11)], meta_membros=12)
    assert [c.celula_id for c in out] == [CEL]
    assert out[0].fato_chave == f"{CEL}:membros:12"
    assert svc.meta_candidates([(CEL, 12)], meta_membros=15) == []


def test_consolidacao_one_fact_per_track_and_cell():
    cid = uuid.uuid4()
    out = svc.consolidacao_candidates([(cid, CEL, PES)])
    assert out[0].fato_chave == f"{cid}:{CEL}" and out[0].pessoa_id == PES


def test_texts_carry_no_personal_data():
    # Gatilhos só formatam datas e números: nada de nome/telefone no alerta.
    now = dt.datetime(2026, 11, 12, 12, tzinfo=UTC)
    out = (
        svc.visitante_candidates([(uuid.uuid4(), CEL, dt.date(2026, 11, 10))], today=now.date(), janela_dias=7)
        + svc.relatorio_candidates([(uuid.uuid4(), CEL, dt.date(2026, 11, 1), "19:00")], now=now, horas_apos_reuniao=1)
    )
    for c in out:
        assert all(ch not in c.acao for ch in "@+") and len(c.fato_chave) <= 200


@pytest.mark.parametrize(
    "raw",
    ["", " ", "nao-uuid", "{a},", "{a},{a}", "00000000-0000-0000-0000-000000000000"],
)
def test_gate_closed_by_default_and_on_malformed_list(monkeypatch, raw):
    a = uuid.uuid4()
    monkeypatch.setenv(svc.ENV_ALLOWLIST, raw.format(a=a))
    assert svc.enabled_igreja_ids() == ()
    assert svc.cell_alert_release_includes(a) is False


def test_gate_opens_only_listed_church(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv(svc.ENV_ALLOWLIST, f"{a}")
    assert svc.cell_alert_release_includes(a) is True
    assert svc.cell_alert_release_includes(b) is False
    assert svc.cell_alert_release_includes(str(a)) is False


def test_cycle_opens_no_session_when_gate_closed(monkeypatch):
    monkeypatch.delenv(svc.ENV_ALLOWLIST, raising=False)

    def factory():  # pragma: no cover - não pode ser chamado
        raise AssertionError("sessão aberta com gate fechado")

    assert svc.run_cell_alert_cycle(factory) == 0


def test_cycle_isolates_failing_church(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv(svc.ENV_ALLOWLIST, f"{a},{b}")
    events = []

    class FakeSession:
        def __init__(self):
            self.igreja = None

        def commit(self):
            events.append(("commit", self.igreja))

        def rollback(self):
            events.append(("rollback", self.igreja))

        def close(self):
            events.append(("close", self.igreja))

    def scope(session, igreja_id):
        session.igreja = igreja_id

    def fake_eval(session, igreja_id, *, now):
        if igreja_id == a:
            raise RuntimeError("falha sintética")
        return 2

    monkeypatch.setattr(svc, "evaluate_igreja", fake_eval)
    assert svc.run_cell_alert_cycle(FakeSession, scope=scope) == 2
    assert ("rollback", a) in events and ("commit", b) in events
    assert ("close", a) in events and ("close", b) in events

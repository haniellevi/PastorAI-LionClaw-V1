"""Tier A Jev stays typed, fail-safe and disabled without a release approval."""

from __future__ import annotations

import asyncio
import json
import datetime as dt
import uuid

import httpx
import pytest

from app.services import semantic_triage as jev_triage


_IGREJA_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OUTRA_IGREJA_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _required(name: str):
    candidate = getattr(jev_triage, name, None)
    assert callable(candidate), f"Tier A exige {name}"
    return candidate


def _body(**answers: object) -> dict[str, object]:
    base: dict[str, object] = {
        "risco_crise": {"type": "noul", "noul": 0.01},
        "pede_humano": {"type": "noul", "noul": 0.01},
        "pede_optout": {"type": "noul", "noul": 0.01},
    }
    base.update(answers)
    return {"model": "jev-sintetico", "answers": base}


def _error_value(decision: object) -> str | None:
    error = getattr(decision, "erro")
    return getattr(error, "value", error)


def _settings(**overrides: object):
    values: dict[str, object] = {
        "typesafe_api_key": "synthetic-key",
        "jev_enabled_igreja_ids": str(_IGREJA_ID),
    }
    values.update(overrides)
    return jev_triage.TriageSettings(_env_file=None, **values)


def _effective(settings=None, *, dpa: dt.date | None = dt.date(2026, 9, 26)):
    return jev_triage.EffectiveTriageSettings(
        settings=settings or _settings(),
        chave_origem="ambiente",
        chave_ilegivel=False,
        chave_atualizada_em=None,
        dpa_assinado_em=dpa,
    )


def test_tier_a_request_has_exactly_three_public_noul_ids() -> None:
    build = _required("build_tier_a_request")

    request = build("mensagem sintética", model="jev-sintetico")

    assert request["model"] == "jev-sintetico"
    assert set(request["questions"]) == {
        "risco_crise",
        "pede_humano",
        "pede_optout",
    }
    assert {
        question["type"] for question in request["questions"].values()
    } == {"noul"}
    assert "intencao" not in request["questions"]
    assert "aceita_termo" not in request["questions"]


def test_tier_a_turns_three_negative_nouls_into_continue() -> None:
    parse = _required("parse_tier_a_response")

    decision = parse(_body(), latencia_ms=17)

    assert decision.risco_crise is False
    assert decision.pede_humano is False
    assert decision.pede_optout is False
    assert decision.handoff is False
    assert decision.erro is None
    assert decision.latencia_ms == 17
    assert decision.to_log_payload() == {
        "risco_crise": False,
        "pede_humano": False,
        "pede_optout": False,
        "handoff": False,
        "erro": None,
        "latencia_ms": 17,
    }


@pytest.mark.parametrize(
    ("answer", "attribute"),
    (
        ({"type": "noul", "noul": 0.99}, "risco_crise"),
        ({"type": "noul", "noul": 0.99}, "pede_humano"),
    ),
)
def test_tier_a_crise_or_humano_positive_forces_handoff(
    answer: dict[str, object],
    attribute: str,
) -> None:
    parse = _required("parse_tier_a_response")

    decision = parse(_body(**{attribute: answer}), latencia_ms=1)

    assert getattr(decision, attribute) is True
    assert decision.handoff is True
    assert decision.erro is None


def test_tier_a_probable_optout_only_requests_confirmation() -> None:
    parse = _required("parse_tier_a_response")

    decision = parse(
        _body(pede_optout={"type": "noul", "noul": 0.99}), latencia_ms=1
    )

    assert decision.pede_optout is True
    assert decision.handoff is False
    assert decision.erro is None


@pytest.mark.parametrize(
    "invalid",
    (True, "0.9", float("nan"), float("inf"), -0.01, 1.01, 10**400),
)
def test_tier_a_rejects_non_strict_noul_probabilities(invalid: object) -> None:
    parse = _required("parse_tier_a_response")

    decision = parse(
        _body(risco_crise={"type": "noul", "noul": invalid}), latencia_ms=1
    )

    assert decision.handoff is True
    assert _error_value(decision) == "schema_invalido"


@pytest.mark.parametrize(
    "body",
    (
        _body(pede_humano=None),
        _body(risco_crise={"type": "choice", "noul": 0.01}),
        _body(extra={"type": "noul", "noul": 0.01}),
    ),
)
def test_tier_a_missing_or_changed_schema_is_handoff(body: dict[str, object]) -> None:
    parse = _required("parse_tier_a_response")

    decision = parse(body, latencia_ms=1)

    assert decision.handoff is True
    assert _error_value(decision) == "schema_invalido"


def test_tier_a_uncertain_probability_is_handoff() -> None:
    parse = _required("parse_tier_a_response")

    decision = parse(
        _body(pede_optout={"type": "noul", "noul": 0.5}), latencia_ms=1
    )

    assert decision.handoff is True
    assert _error_value(decision) == "inconclusivo"


def test_tier_a_duplicate_json_keys_are_rejected_before_dict() -> None:
    parse_json = _required("parse_tier_a_json")
    raw = json.dumps(_body()).replace(
        '"risco_crise": {"type": "noul", "noul": 0.01},',
        '"risco_crise": {"type": "noul", "noul": 0.01}, '
        '"risco_crise": {"type": "noul", "noul": 0.99},',
    )

    decision = parse_json(raw, latencia_ms=1)

    assert decision.handoff is True
    assert _error_value(decision) == "schema_invalido"


def test_tier_a_invalid_utf8_body_is_schema_handoff() -> None:
    parse_json = _required("parse_tier_a_json")

    decision = parse_json(b"\xff", latencia_ms=1)

    assert decision.handoff is True
    assert _error_value(decision) == "schema_invalido"


def test_active_allowlist_is_strict_and_independent_from_shadow() -> None:
    enabled_for = _required("tier_a_listed_for")
    shadow_for = _required("shadow_enabled_for")

    shadow_only = _settings(
        jev_enabled_igreja_ids="",
        jev_shadow_triage_igreja_ids=str(_IGREJA_ID),
    )
    invalid = _settings(
        jev_enabled_igreja_ids=f"{_IGREJA_ID}, not-a-uuid",
    )

    assert shadow_for(shadow_only, _IGREJA_ID) is True
    assert enabled_for(shadow_only, _IGREJA_ID) is False
    assert enabled_for(invalid, _IGREJA_ID) is False
    assert enabled_for(_settings(), _OUTRA_IGREJA_ID) is False


def test_tier_a_optout_confirmation_key_is_per_tenant_and_conversation() -> None:
    key_for = _required("tier_a_optout_confirmation_key")
    conversation_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    first = key_for(_IGREJA_ID, conversation_id)

    assert first.startswith("jev-tier-a-optout-confirmation:v1:")
    assert first == key_for(_IGREJA_ID, conversation_id)
    assert first != key_for(_OUTRA_IGREJA_ID, conversation_id)
    assert first != key_for(_IGREJA_ID, uuid.uuid4())


def test_tier_a_egress_stays_closed_without_a_release_approved_in_code(monkeypatch) -> None:
    allowed = _required("tier_a_egress_allowed")
    monkeypatch.setattr(jev_triage, "external_sends_allowed", lambda: True)
    effective = _effective()

    assert allowed(effective, _IGREJA_ID) is False
    assert allowed(effective, _IGREJA_ID, approved_release_id="future-release") is False


@pytest.mark.parametrize(
    ("effective", "approved_release_id"),
    (
        (_effective(_settings(jev_enabled_igreja_ids="")), "synthetic-release"),
        (_effective(dpa=None), "synthetic-release"),
        (_effective(), None),
    ),
)
def test_tier_a_direct_egress_gate_makes_zero_calls(
    monkeypatch,
    effective: object,
    approved_release_id: str | None,
) -> None:
    run = _required("run_tier_a")
    monkeypatch.setattr(jev_triage, "TIER_A_APPROVED_RELEASE_ID", "synthetic-release")
    monkeypatch.setattr(jev_triage, "external_sends_allowed", lambda: True)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_body())

    decision = asyncio.run(
        run(
            effective,
            _IGREJA_ID,
            "mensagem sintética",
            approved_release_id=approved_release_id,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert decision.handoff is True
    assert _error_value(decision) == "gate_fechado"


def test_tier_a_http_returns_typed_failure_without_retry(monkeypatch) -> None:
    run = _required("run_tier_a")
    monkeypatch.setattr(jev_triage, "TIER_A_APPROVED_RELEASE_ID", "synthetic-release")
    monkeypatch.setattr(jev_triage, "external_sends_allowed", lambda: True)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("synthetic timeout")

    decision = asyncio.run(
        run(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            approved_release_id="synthetic-release",
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 1
    assert decision.handoff is True
    assert _error_value(decision) == "timeout"


def test_tier_a_cancels_a_slow_response_read_at_its_budget(monkeypatch) -> None:
    run = _required("run_tier_a")
    monkeypatch.setattr(jev_triage, "TIER_A_APPROVED_RELEASE_ID", "synthetic-release")
    monkeypatch.setattr(jev_triage, "external_sends_allowed", lambda: True)
    cancelled = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal cancelled
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled = True
            raise
        return httpx.Response(200, json=_body())

    decision = asyncio.run(
        run(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            approved_release_id="synthetic-release",
            transport=httpx.MockTransport(handler),
            timeout_seconds=0.01,
        )
    )

    assert cancelled is True
    assert decision.handoff is True
    assert _error_value(decision) == "timeout"

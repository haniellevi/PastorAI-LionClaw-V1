"""Choice B/C/D é fechado, tipado e sem egress real."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import json
import time
import uuid

import httpx
import pytest

from app.services import semantic_triage


_IGREJA_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OUTRA_IGREJA_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _routing_module():
    try:
        return importlib.import_module("app.services.semantic_routing")
    except ModuleNotFoundError as exc:
        if exc.name == "app.services.semantic_routing":
            return None
        raise


def _routing():
    routing = _routing_module()
    assert routing is not None, "S3 exige o transporte Choice B/C/D"
    return routing


def _settings(**overrides: object):
    values: dict[str, object] = {
        "typesafe_api_key": "synthetic-key",
        "jev_enabled_igreja_ids": str(_IGREJA_ID),
    }
    values.update(overrides)
    return semantic_triage.TriageSettings(_env_file=None, **values)


def _effective(settings=None, *, dpa: dt.date | None = dt.date(2026, 9, 26)):
    return semantic_triage.EffectiveTriageSettings(
        settings=settings or _settings(),
        chave_origem="ambiente",
        chave_ilegivel=False,
        chave_atualizada_em=None,
        dpa_assinado_em=dpa,
    )


def _choice_body(
    question_id: str,
    choice: str,
    options: tuple[str, ...],
    *,
    confidence: object = 0.9,
    probabilities: object | None = None,
) -> dict[str, object]:
    if probabilities is None:
        probabilities = {option: 1.0 if option == choice else 0.0 for option in options}
    return {
        "model": "jev-synthetic",
        "answers": {
            question_id: {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": probabilities,
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _error_value(result: object) -> str | None:
    error = getattr(result, "erro")
    return getattr(error, "value", error)


def _enable_routing_egress(monkeypatch, routing) -> None:
    monkeypatch.setattr(semantic_triage, "TIER_A_APPROVED_RELEASE_ID", "tier-a-ok")
    monkeypatch.setattr(routing, "S3_ROUTING_APPROVED_RELEASE_ID", "s3-ok")
    monkeypatch.setattr(semantic_triage, "external_sends_allowed", lambda: True)


def _run_b(routing, effective, *, transport, timeout_seconds: float | None = 0.5):
    return asyncio.run(
        routing.run_choice_b(
            effective,
            _IGREJA_ID,
            "mensagem sintética",
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
    )


def test_privileged_choice_requests_expose_only_scoped_routes_and_safe_exits() -> None:
    routing = _routing()
    b = routing.build_choice_b_request(
        "mensagem", model="jev-synthetic",
        allowed_routes=("restrita", "handoff", "nenhuma"),
    )
    assert tuple(b["questions"]["rota_s3"]["criteria"]) == (
        "restrita", "handoff", "nenhuma",
    )
    c = routing.build_choice_c_request(
        "mensagem", route=routing.RouteChoice.RESTRITA,
        allowed_tools=("registrar_decisao",), model="jev-synthetic",
        include_handoff=True,
    )
    assert tuple(c["questions"]["ferramenta_s3"]["criteria"]) == (
        "registrar_decisao", "nenhuma", "handoff",
    )
    d = routing.build_choice_d_request(
        "mensagem", route=routing.RouteChoice.RESTRITA,
        tool="registrar_decisao", candidate_summaries={"h1": "Pessoa A"},
        model="jev-synthetic", include_handoff=True,
    )
    assert tuple(d["questions"]["candidato_s3"]["criteria"]) == (
        "h1", "nenhum", "handoff",
    )


def test_choice_b_sends_only_bounded_redacted_message_and_fixed_routes() -> None:
    routing = _routing()

    body = routing.build_choice_b_request("pergunta sintética", model="jev-sintetico")

    assert body["model"] == "jev-sintetico"
    assert body["state"] == {
        "mensagem": "pergunta sintética",
        "canal": "whatsapp_atendimento",
    }
    assert set(body["questions"]) == {"rota_s3"}
    question = body["questions"]["rota_s3"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"publica", "restrita", "pastoral", "outro"}
    serialized = repr(body)
    assert "igreja" not in serialized
    assert "papel" not in serialized
    assert "tenant" not in serialized


def test_choice_b_reuses_the_existing_egress_redaction() -> None:
    routing = _routing()
    synthetic_phone = "+55 00 9" + ("0" * 4) + "-" + ("0" * 4)

    body = routing.build_choice_b_request(
        f"mensagem com telefone {synthetic_phone}",
        model="jev-sintetico",
    )

    assert synthetic_phone not in body["state"]["mensagem"]


def test_choice_c_uses_only_server_catalog_and_none() -> None:
    routing = _routing()

    body = routing.build_choice_c_request(
        "mensagem sintética",
        route=routing.RouteChoice.RESTRITA,
        allowed_tools=("proxima_reuniao", "agenda_igreja"),
        model="jev-sintetico",
    )

    assert body["state"] == {
        "mensagem": "mensagem sintética",
        "canal": "whatsapp_atendimento",
        "rota": "restrita",
    }
    question = body["questions"]["ferramenta_s3"]
    assert set(question["criteria"]) == {
        "proxima_reuniao",
        "agenda_igreja",
        "nenhuma",
    }
    serialized = repr(body)
    assert str(_IGREJA_ID) not in serialized
    assert "papel" not in serialized
    assert "tenant" not in serialized


def test_choice_d_offers_only_sequential_opaque_handles_and_none() -> None:
    routing = _routing()

    body = routing.build_choice_d_request(
        "mensagem sintética",
        route=routing.RouteChoice.RESTRITA,
        tool="proxima_reuniao",
        candidate_summaries={
            "h1": "Encontro no domingo, 19:00.",
            "h2": "Encontro na terça, 20:00.",
        },
        model="jev-sintetico",
    )

    assert body["state"] == {
        "mensagem": "mensagem sintética",
        "canal": "whatsapp_atendimento",
        "rota": "restrita",
        "ferramenta": "proxima_reuniao",
    }
    question = body["questions"]["candidato_s3"]
    assert set(question["criteria"]) == {"h1", "h2", "nenhum"}
    serialized = repr(body)
    assert str(_IGREJA_ID) not in serialized
    assert "papel" not in serialized
    assert "tenant" not in serialized


def test_choice_d_sends_distinct_authorized_summaries_without_identity_fields() -> None:
    routing = _routing()
    summaries = {
        "h1": "Culto de domingo, 2026-09-27, 19:00.",
        "h2": "Reunião de terça, 2026-09-29, 20:00.",
    }
    try:
        body = routing.build_choice_d_request(
            "qual encontro é no domingo?",
            route=routing.RouteChoice.RESTRITA,
            tool="agenda_igreja",
            candidate_summaries=summaries,
            model="jev-sintetico",
        )
    except TypeError:
        body = None

    assert body is not None, "D exige resumos mínimos e distinguíveis por handle"
    criteria = body["questions"]["candidato_s3"]["criteria"]
    assert criteria["h1"] == summaries["h1"]
    assert criteria["h2"] == summaries["h2"]
    serialized = repr(body)
    assert str(_IGREJA_ID) not in serialized
    assert "tenant" not in serialized
    assert "papel" not in serialized


def test_choice_d_redacts_and_neutralizes_authorized_candidate_summaries() -> None:
    routing = _routing()
    synthetic_phone = "+55 00 9" + ("0" * 4) + "-" + ("0" * 4)

    body = routing.build_choice_d_request(
        "qual encontro?",
        route=routing.RouteChoice.RESTRITA,
        tool="agenda_igreja",
        candidate_summaries={
            "h1": f"Culto <domingo> às 19:00, contato {synthetic_phone}.",
        },
        model="jev-sintetico",
    )

    summary = body["questions"]["candidato_s3"]["criteria"]["h1"]
    assert synthetic_phone not in summary
    assert "<" not in summary and ">" not in summary
    assert "[domingo]" in summary


@pytest.mark.parametrize(
    "body",
    (
        _choice_body("rota_s3", "publica", ("publica", "restrita", "pastoral", "outro")),
        _choice_body(
            "rota_s3",
            "publica",
            ("publica", "restrita", "pastoral", "outro"),
            probabilities={"publica": 0.7, "restrita": 0.2, "pastoral": 0.1, "outro": 0.0},
        ),
    ),
)
def test_choice_b_parser_returns_typed_choice_and_finite_probabilities(
    body: dict[str, object],
) -> None:
    routing = _routing()

    result = routing.parse_choice_response(
        body,
        question_id="rota_s3",
        allowed_options=("publica", "restrita", "pastoral", "outro"),
        latencia_ms=13,
    )

    assert result.choice == "publica"
    assert result.probabilities["publica"] >= 0
    assert result.confidence == pytest.approx(0.9)
    assert result.erro is None
    assert result.latencia_ms == 13


@pytest.mark.parametrize("choice", ("publica", "restrita", "pastoral", "outro"))
def test_choice_b_parser_accepts_each_fixed_route(choice: str) -> None:
    routing = _routing()

    result = routing.parse_choice_response(
        _choice_body(
            "rota_s3",
            choice,
            ("publica", "restrita", "pastoral", "outro"),
        ),
        question_id="rota_s3",
        allowed_options=("publica", "restrita", "pastoral", "outro"),
        latencia_ms=1,
    )

    assert result.choice == choice
    assert result.erro is None


@pytest.mark.parametrize(
    "body",
    (
        _choice_body(
            "rota_s3",
            "forjada",
            ("publica", "restrita", "pastoral", "outro"),
        ),
        _choice_body(
            "rota_s3",
            "publica",
            ("publica", "restrita", "pastoral", "outro"),
            confidence=True,
        ),
        _choice_body(
            "rota_s3",
            "publica",
            ("publica", "restrita", "pastoral", "outro"),
            probabilities={"publica": True, "restrita": 0, "pastoral": 0, "outro": 0},
        ),
        _choice_body(
            "rota_s3",
            "publica",
            ("publica", "restrita", "pastoral", "outro"),
            probabilities={"publica": float("nan"), "restrita": 0, "pastoral": 0, "outro": 0},
        ),
        {
            "answers": {
                "rota_s3": {
                    "type": "choice",
                    "choice": "publica",
                    "confidence": 0.9,
                    "probabilities": {"publica": 1, "restrita": 0, "pastoral": 0, "outro": 0},
                    "extra": "forjado",
                }
            }
        },
        {
            "answers": {
                "rota_s3": {
                    "type": "choice",
                    "choice": "publica",
                    "confidence": 0.9,
                    "probabilities": {"publica": 1, "restrita": 0, "pastoral": 0},
                }
            }
        },
    ),
)
def test_choice_parser_rejects_forged_or_non_strict_response(
    body: dict[str, object],
) -> None:
    routing = _routing()

    result = routing.parse_choice_response(
        body,
        question_id="rota_s3",
        allowed_options=("publica", "restrita", "pastoral", "outro"),
        latencia_ms=1,
    )

    assert result.choice is None
    assert dict(result.probabilities) == {}
    assert _error_value(result) == "schema_invalido"


def test_choice_parser_rejects_duplicate_json_keys_before_decoding_to_dict() -> None:
    routing = _routing()
    raw = (
        '{"answers":{"rota_s3":{"type":"choice","choice":"publica",'
        '"choice":"restrita","confidence":0.9,"probabilities":'
        '{"publica":1,"restrita":0,"pastoral":0,"outro":0}}}}'
    )

    result = routing.parse_choice_json(
        raw,
        question_id="rota_s3",
        allowed_options=("publica", "restrita", "pastoral", "outro"),
        latencia_ms=1,
    )

    assert result.choice is None
    assert _error_value(result) == "schema_invalido"


def test_choice_deep_json_fails_closed_through_transport(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    stream = _ChunkedStream((b"[" * 10_000, b"0", b"]" * 10_000))
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=stream)

    result = _run_b(routing, _effective(), transport=httpx.MockTransport(handler))

    assert calls == 1
    assert result.choice is None
    assert _error_value(result) == "schema_invalido"
    assert stream.read_count == 3
    assert stream.closed is True


class _ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def test_choice_oversized_chunked_response_stops_reading_and_closes(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    stream = _ChunkedStream((b" " * 40_000, b" " * 40_000, b" " * 40_000))
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=stream)

    result = _run_b(routing, _effective(), transport=httpx.MockTransport(handler))

    assert calls == 1
    assert result.choice is None
    assert _error_value(result) == "schema_invalido"
    assert stream.read_count == 2
    assert stream.closed is True


def test_choice_stream_timeout_cancels_read_and_closes(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)

    class SlowStream(httpx.AsyncByteStream):
        cancelled = False
        closed = False

        async def __aiter__(self):
            yield b"{"
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        async def aclose(self) -> None:
            self.closed = True

    stream = SlowStream()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    result = _run_b(
        routing, _effective(), transport=httpx.MockTransport(handler), timeout_seconds=0.01,
    )

    assert result.choice is None
    assert _error_value(result) == "timeout"
    assert stream.cancelled is True
    assert stream.closed is True


@pytest.mark.parametrize("bad", (float("nan"), float("inf"), float("-inf"), -1.0, 0.0, True))
@pytest.mark.parametrize("source", ("remaining", "configured"))
def test_choice_invalid_budget_operand_never_calls_transport(monkeypatch, source, bad) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    effective = _effective()
    remaining = bad if source == "remaining" else 0.5
    if source == "configured":
        effective = _effective(effective.settings.model_copy(update={"typesafe_timeout_seconds": bad}))
    result = _run_b(
        routing, effective, transport=httpx.MockTransport(handler), timeout_seconds=remaining,
    )

    assert calls == 0
    assert result.choice is None
    assert _error_value(result) == "orcamento_esgotado"


def test_choice_sync_parse_after_deadline_cannot_succeed(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    original = routing.parse_choice_json

    def slow_parse(*args, **kwargs):
        time.sleep(0.03)
        return original(*args, **kwargs)

    monkeypatch.setattr(routing, "parse_choice_json", slow_parse)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_choice_body("rota_s3", "publica", ("publica", "restrita", "pastoral", "outro")),
        )

    result = _run_b(
        routing, _effective(), transport=httpx.MockTransport(handler), timeout_seconds=0.01,
    )
    assert result.choice is None
    assert _error_value(result) == "timeout"


def test_choice_gate_stays_closed_with_listed_church_when_s3_release_is_absent(
    monkeypatch,
) -> None:
    routing = _routing()
    monkeypatch.setattr(semantic_triage, "TIER_A_APPROVED_RELEASE_ID", "tier-a-ok")
    monkeypatch.setattr(semantic_triage, "external_sends_allowed", lambda: True)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = _run_b(
        routing,
        _effective(),
        transport=httpx.MockTransport(handler),
    )

    assert calls == 0
    assert result.choice is None
    assert _error_value(result) == "gate_fechado"


def test_choice_gate_stays_closed_when_active_tier_a_list_is_empty(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = _run_b(
        routing,
        _effective(_settings(jev_enabled_igreja_ids="")),
        transport=httpx.MockTransport(handler),
    )

    assert calls == 0
    assert _error_value(result) == "gate_fechado"


def test_choice_gate_stays_closed_for_another_tenant(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_b(
            _effective(),
            _OUTRA_IGREJA_ID,
            "mensagem sintética",
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert _error_value(result) == "gate_fechado"


def test_choice_b_executes_one_typed_call_after_both_release_gates(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_choice_body(
                "rota_s3",
                "restrita",
                ("publica", "restrita", "pastoral", "outro"),
            ),
        )

    result = _run_b(
        routing,
        _effective(),
        transport=httpx.MockTransport(handler),
    )

    assert calls == 1
    assert seen["authorization"] == "Bearer synthetic-key"
    assert result.choice == routing.RouteChoice.RESTRITA
    assert result.probabilities["restrita"] == pytest.approx(1.0)
    assert result.erro is None


def test_choice_d_rejects_forged_handle_without_transport(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_d(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            tool="proxima_reuniao",
            candidate_summaries={
                "h1": "Encontro no domingo, 19:00.",
                "00000000-0000-0000-0000-000000000000": "Forjado.",
            },
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert result.choice is None
    assert _error_value(result) == "schema_invalido"


@pytest.mark.parametrize(
    "candidate_summaries",
    (
        {"h1": "x" * 241},
        {"h1": "Culto domingo.", "metadata": "forjado"},
        {"h1": "Evento 00000000-0000-0000-0000-000000000000."},
        {"h1": "tenant=00000000-0000-0000-0000-000000000000"},
    ),
)
def test_choice_d_rejects_oversized_or_identity_shaped_summaries_without_transport(
    monkeypatch,
    candidate_summaries: dict[str, str],
) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_d(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            tool="agenda_igreja",
            candidate_summaries=candidate_summaries,
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert _error_value(result) == "schema_invalido"


def test_choice_d_does_not_egress_candidate_summaries_when_gate_is_closed(monkeypatch) -> None:
    routing = _routing()
    monkeypatch.setattr(semantic_triage, "TIER_A_APPROVED_RELEASE_ID", "tier-a-ok")
    monkeypatch.setattr(semantic_triage, "external_sends_allowed", lambda: True)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_d(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            tool="agenda_igreja",
            candidate_summaries={"h1": "Culto domingo, 19:00."},
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert _error_value(result) == "gate_fechado"


def test_choice_d_transports_only_distinct_minimal_facts_after_gates(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_choice_body("candidato_s3", "h2", ("h1", "h2", "nenhum")),
        )

    result = asyncio.run(
        routing.run_choice_d(
            _effective(),
            _IGREJA_ID,
            "qual encontro é na terça?",
            route=routing.RouteChoice.RESTRITA,
            tool="agenda_igreja",
            candidate_summaries={
                "h1": "Culto de domingo, 2026-09-27, 19:00.",
                "h2": "Reunião de terça, 2026-09-29, 20:00.",
            },
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    payload = seen["payload"]
    criteria = payload["questions"]["candidato_s3"]["criteria"]
    assert criteria["h1"] == "Culto de domingo, 2026-09-27, 19:00."
    assert criteria["h2"] == "Reunião de terça, 2026-09-29, 20:00."
    assert str(_IGREJA_ID) not in repr(payload)
    assert "papel" not in repr(payload)
    assert "tenant" not in repr(payload)
    assert result.choice == "h2"


def test_choice_c_rejects_a_real_id_shaped_catalog_code_without_transport(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_c(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            allowed_tools=("00000000-0000-0000-0000-000000000000",),
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert _error_value(result) == "schema_invalido"


def test_choice_c_rejects_an_unbounded_catalog_without_transport(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_c(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            allowed_tools=tuple(f"ferramenta_{chr(ord('a') + index)}" for index in range(9)),
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert _error_value(result) == "schema_invalido"


def test_choice_rejects_oversized_input_without_silent_truncation(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = asyncio.run(
        routing.run_choice_b(
            _effective(),
            _IGREJA_ID,
            "x" * 2001,
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
    )

    assert calls == 0
    assert _error_value(result) == "limite_entrada"


def test_choice_times_out_once_and_cancels_the_mock_transport(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0
    cancelled = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls, cancelled
        calls += 1
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled = True
            raise
        return httpx.Response(200, json={})

    result = _run_b(
        routing,
        _effective(),
        transport=httpx.MockTransport(handler),
        timeout_seconds=0.01,
    )

    assert calls == 1
    assert cancelled is True
    assert result.choice is None
    assert _error_value(result) == "timeout"


def test_choice_honors_its_point_six_second_cap(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    monkeypatch.setattr(routing, "S3_ROUTING_HTTP_MAX_SECONDS", 0.01)
    cancelled = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal cancelled
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled = True
            raise
        return httpx.Response(200, json={})

    result = _run_b(
        routing,
        _effective(),
        transport=httpx.MockTransport(handler),
        timeout_seconds=0.5,
    )

    assert cancelled is True
    assert _error_value(result) == "timeout"


def test_choice_does_not_spend_reserved_time(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    result = _run_b(
        routing,
        _effective(),
        transport=httpx.MockTransport(handler),
        timeout_seconds=None,
    )

    assert calls == 0
    assert _error_value(result) == "orcamento_esgotado"


def test_choice_c_and_d_return_only_offered_values(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    responses = iter(
        (
            _choice_body(
                "ferramenta_s3",
                "agenda_igreja",
                ("proxima_reuniao", "agenda_igreja", "nenhuma"),
            ),
            _choice_body("candidato_s3", "h2", ("h1", "h2", "nenhum")),
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    async def run() -> tuple[object, object]:
        c = await routing.run_choice_c(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            allowed_tools=("proxima_reuniao", "agenda_igreja"),
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
        d = await routing.run_choice_d(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            tool="agenda_igreja",
            candidate_summaries={
                "h1": "Encontro no domingo, 19:00.",
                "h2": "Encontro na terça, 20:00.",
            },
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
        return c, d

    catalog, candidate = asyncio.run(run())

    assert catalog.choice == "agenda_igreja"
    assert candidate.choice == "h2"
    assert _error_value(catalog) is None
    assert _error_value(candidate) is None


def test_choice_c_and_d_accept_their_explicit_none_values(monkeypatch) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    responses = iter(
        (
            _choice_body("ferramenta_s3", "nenhuma", ("proxima_reuniao", "nenhuma")),
            _choice_body("candidato_s3", "nenhum", ("h1", "nenhum")),
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    async def run() -> tuple[object, object]:
        catalog = await routing.run_choice_c(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            allowed_tools=("proxima_reuniao",),
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
        candidate = await routing.run_choice_d(
            _effective(),
            _IGREJA_ID,
            "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            tool="proxima_reuniao",
            candidate_summaries={"h1": "Encontro no domingo, 19:00."},
            tier_a_release_id="tier-a-ok",
            s3_release_id="s3-ok",
            timeout_seconds=0.5,
            transport=httpx.MockTransport(handler),
        )
        return catalog, candidate

    catalog, candidate = asyncio.run(run())

    assert catalog.choice == "nenhuma"
    assert candidate.choice == "nenhum"


@pytest.mark.parametrize("stage", ("b", "c", "d"))
@pytest.mark.parametrize("failing_gate", ("tier_a", "external_sends"))
def test_choice_gate_exception_fails_closed_without_http(monkeypatch, stage, failing_gate) -> None:
    routing = _routing()
    _enable_routing_egress(monkeypatch, routing)
    calls = 0

    def broken_gate(*_args, **_kwargs):
        raise RuntimeError("configuração inválida sintética")

    if failing_gate == "tier_a":
        monkeypatch.setattr(routing, "tier_a_egress_allowed", broken_gate)
    else:
        monkeypatch.setattr(semantic_triage, "external_sends_allowed", broken_gate)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    common = dict(
        tier_a_release_id="tier-a-ok",
        s3_release_id="s3-ok",
        timeout_seconds=0.5,
        transport=httpx.MockTransport(handler),
    )
    if stage == "b":
        operation = routing.run_choice_b(_effective(), _IGREJA_ID, "mensagem sintética", **common)
    elif stage == "c":
        operation = routing.run_choice_c(
            _effective(), _IGREJA_ID, "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            allowed_tools=("consultar_celulas",), **common,
        )
    else:
        operation = routing.run_choice_d(
            _effective(), _IGREJA_ID, "mensagem sintética",
            route=routing.RouteChoice.RESTRITA,
            tool="consultar_celulas",
            candidate_summaries={"h1": "resumo sintético"}, **common,
        )
    result = asyncio.run(operation)
    assert _error_value(result) == "gate_fechado"
    assert result.choice is None
    assert calls == 0

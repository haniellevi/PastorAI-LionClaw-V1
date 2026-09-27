"""Closed V1a aggregate extraction over synthetic SDK transports only."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import openai
import pytest

from app.services import llm


def _client() -> llm.LLMClient:
    return llm.LLMClient("openai", "synthetic-key", "gpt-5.6-luna")


def _response(
    content: object = (
        '{"presentes":12,"visitantes":null,"decisoes":1,"oferta_centavos":3550}'
    ),
    *,
    usage: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=content,
                    refusal=None,
                    tool_calls=None,
                    function_call=None,
                ),
            )
        ],
        usage=usage or SimpleNamespace(prompt_tokens=12, completion_tokens=8),
    )


def _fake_sdk(monkeypatch: pytest.MonkeyPatch, *, response: object = None) -> dict[str, object]:
    state: dict[str, object] = {"calls": 0, "request": None, "closed": False}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            state["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            state["closed"] = True

        async def create(self, **kwargs: object) -> object:
            state["calls"] = int(state["calls"]) + 1
            state["request"] = kwargs
            return response or _response()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    return state


def test_extracts_only_closed_aggregates_with_bounded_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch)

    result = _client().extract_v1a_cell_report(
        {"presentes": "doze", "oferta": "trinta e cinco reais"},
        timeout_seconds=10,
    )

    assert result.payload == {
        "decisoes": 1,
        "oferta_centavos": 3550,
        "presentes": 12,
        "visitantes": None,
    }
    assert result.usage == llm.LLMUsage(
        "gpt-5.6-luna", 12, 8, llm.estimate_cost("gpt-5.6-luna", 12, 8)
    )
    request = state["request"]
    assert type(request) is dict
    assert request["max_completion_tokens"] == 400
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert request["messages"][1]["content"] == json.dumps(
        {"oferta": "trinta e cinco reais", "presentes": "doze"},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert state["calls"] == 1 and state["closed"] is True
    assert state["client"]["timeout"] == 4.0
    assert state["client"]["max_retries"] == 0


def test_extract_does_not_open_sdk_when_gate_or_projection_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: False)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kwargs: pytest.fail("SDK indevido"))

    with pytest.raises(llm.LLMError, match="desativados"):
        _client().extract_v1a_cell_report({"presentes": "dez"}, timeout_seconds=1)

    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    with pytest.raises(llm.LLMError):
        _client().extract_v1a_cell_report(
            {"presentes": "dez", "texto": "fulano rua 1"}, timeout_seconds=1
        )


@pytest.mark.parametrize(
    "content",
    [
        '{"presentes":12,"visitantes":0,"decisoes":1,"oferta_centavos":3550,"id":"x"}',
        '{"presentes":12,"presentes":99,"visitantes":0,"decisoes":1,"oferta_centavos":3550}',
        '{"presentes":true,"visitantes":0,"decisoes":1,"oferta_centavos":3550}',
        '{"presentes":12,"visitantes":0,"decisoes":1,"oferta_centavos":NaN}',
        '{"presentes":12,"visitantes":0,"decisoes":1}',
    ],
)
def test_extract_rejects_malformed_provider_schema_without_content_leak(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, response=_response(content))

    with pytest.raises(llm.LLMError) as exc:
        _client().extract_v1a_cell_report({"presentes": "doze"}, timeout_seconds=1)

    assert "oferta_centavos" not in str(exc.value)
    assert state["calls"] == 1 and state["closed"] is True


def test_extract_timeout_cancels_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state: dict[str, object] = {"calls": 0, "cancelled": False, "closed": False}

    class FakeAsyncOpenAI:
        def __init__(self, **_kwargs: object) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            state["closed"] = True

        async def create(self, **_kwargs: object) -> object:
            state["calls"] = int(state["calls"]) + 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
            raise AssertionError("unreachable")

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    with pytest.raises(llm.LLMError, match="tempo limite"):
        _client().extract_v1a_cell_report({"presentes": "doze"}, timeout_seconds=0.02)
    assert state == {"calls": 1, "cancelled": True, "closed": True}

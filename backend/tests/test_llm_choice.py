"""Closed-enum LLM transport, using synthetic SDK/HTTP responses only."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import openai._base_client as openai_base
import pytest

from app.services import llm


def _client() -> llm.LLMClient:
    return llm.LLMClient("openai", "synthetic-key", "gpt-5.6-luna")


def _response(content: object, *, finish_reason: str = "stop", refusal: str | None = None,
              tool_calls: object = None, usage: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, refusal=refusal, tool_calls=tool_calls),
        )],
        usage=usage or SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )


def _fake_sdk(monkeypatch, *, response: object = None, blocked: bool = False) -> dict:
    state = {"calls": 0, "closed": False, "cancelled": False, "request": None, "client": None}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            state["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            state["closed"] = True

        async def create(self, **kwargs):
            state["calls"] += 1
            state["request"] = kwargs
            if blocked:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    state["cancelled"] = True
                    raise
            return response or _response('{"choice":"restrita"}')

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    return state


def test_generate_typed_emits_strict_enum_schema_over_local_http(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(openai_base, "get_platform", lambda: "Linux")

    def inline_asyncify(function):
        async def wrapper(*args, **kwargs):
            return function(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(openai_base, "asyncify", inline_asyncify)
    real_client = openai.AsyncOpenAI
    captured: list[dict] = []
    local_clients: list[httpx.AsyncClient] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "chatcmpl-synthetic", "object": "chat.completion", "created": 0,
            "model": "gpt-5.6-luna", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": '{"choice":"restrita"}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })

    def local_client(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        local_clients.append(client)
        assert kwargs["max_retries"] == 0
        assert kwargs["timeout"] == 4
        return real_client(**kwargs, http_client=client)

    monkeypatch.setattr(openai, "AsyncOpenAI", local_client)
    result = _client().generate_typed(
        "sistema", "mensagem", schema_name="s3_route",
        choices=("restrita", "handoff", "nenhuma"), timeout_seconds=10,
    )

    assert result.choice == "restrita"
    assert result.usage.tokens_in == 3 and result.usage.tokens_out == 2
    assert len(captured) == 1
    assert captured[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "s3_route", "strict": True, "schema": {
            "type": "object", "properties": {"choice": {
                "type": "string", "enum": ["restrita", "handoff", "nenhuma"],
            }}, "required": ["choice"], "additionalProperties": False,
        }},
    }
    assert local_clients[0].is_closed is True


@pytest.mark.parametrize("content,finish_reason,refusal,tool_calls", [
    ('{"choice":"forjada"}', "stop", None, None),
    ('{"choice":"restrita","tenant":"outro"}', "stop", None, None),
    ('{"choice":"restrita","choice":"handoff"}', "stop", None, None),
    ('{"choice":false}', "stop", None, None),
    ('{"choice":NaN}', "stop", None, None),
    ('[' * 1100 + '0' + ']' * 1100, "stop", None, None),
    ('{"choice":"restrita"}', "length", None, None),
    ('{"choice":"restrita"}', "content_filter", None, None),
    ('{"choice":"restrita"}', "stop", "segredo raw", None),
    ('{"choice":"restrita"}', "stop", None, [{"id": "tool"}]),
    ('{"choice":"restrita"}', "stop", None, []),
    (None, "stop", None, None),
    ('{"choice":"restrita"}' + ' ' * 65536, "stop", None, None),
])
def test_generate_typed_rejects_untrusted_output(monkeypatch, content, finish_reason, refusal, tool_calls) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, response=_response(
        content, finish_reason=finish_reason, refusal=refusal, tool_calls=tool_calls,
    ))
    with pytest.raises(llm.LLMError) as exc:
        _client().generate_typed("s", "u", schema_name="s3_route", choices=("restrita",), timeout_seconds=1)
    assert "segredo" not in str(exc.value) and "tenant" not in str(exc.value)
    assert state["calls"] == 1 and state["closed"] is True


def test_generate_typed_timeout_cancels_and_closes_without_retry(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, blocked=True)
    with pytest.raises(llm.LLMError, match="tempo limite"):
        _client().generate_typed("s", "u", schema_name="s3_route", choices=("restrita",), timeout_seconds=0.02)
    assert state["calls"] == 1 and state["cancelled"] is True and state["closed"] is True


def test_generate_typed_rejects_unbounded_usage_without_leaking(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, response=_response(
        '{"choice":"restrita"}',
        usage=SimpleNamespace(prompt_tokens=10**400, completion_tokens=1),
    ))
    with pytest.raises(llm.LLMError):
        _client().generate_typed("s", "u", schema_name="s3_route", choices=("restrita",), timeout_seconds=1)
    assert state["calls"] == 1 and state["closed"] is True


@pytest.mark.parametrize("deadline", [0, -1, True, float("nan"), float("inf"), 10**400])
def test_generate_typed_invalid_budget_never_creates_sdk(monkeypatch, deadline) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kw: pytest.fail("SDK indevido"))
    with pytest.raises(llm.LLMError):
        _client().generate_typed("s", "u", schema_name="s3_route", choices=("restrita",), timeout_seconds=deadline)


def test_generate_typed_gate_closed_never_creates_sdk(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: False)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kw: pytest.fail("SDK indevido"))
    with pytest.raises(llm.LLMError):
        _client().generate_typed("s", "u", schema_name="s3_route", choices=("restrita",), timeout_seconds=1)


@pytest.mark.parametrize("choices", [(), ("restrita", "restrita"), ("tenant",), (True,)])
def test_generate_typed_invalid_schema_never_creates_sdk(monkeypatch, choices) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kw: pytest.fail("SDK indevido"))
    with pytest.raises(llm.LLMError):
        _client().generate_typed("s", "u", schema_name="s3_route", choices=choices, timeout_seconds=1)

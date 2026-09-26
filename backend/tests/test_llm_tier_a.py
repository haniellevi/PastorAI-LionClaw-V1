"""Typed LLM call: local transports only, no provider or credential egress."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import openai._base_client as openai_base
import pytest

from app.services import llm


def _response(
    content: object = '{"handoff":false,"resposta":"Olá"}',
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    tool_calls: object = None,
    choices: bool = True,
    usage: object = None,
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, refusal=refusal, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=(
            [SimpleNamespace(message=message, finish_reason=finish_reason)]
            if choices
            else []
        ),
        usage=(
            usage
            if usage is not None
            else SimpleNamespace(prompt_tokens=10, completion_tokens=20)
        ),
    )


def _fake_sdk(monkeypatch, *, response=None, error=None, block=False) -> dict:
    state = {"calls": 0, "closed": False, "cancelled": False, "kwargs": None}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            state["kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            state["closed"] = True

        async def create(self, **_kwargs):
            state["calls"] += 1
            if block:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    state["cancelled"] = True
                    raise
            if error:
                raise error
            return response or _response()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    return state


def _local_sdk(monkeypatch, handler) -> dict:
    """Use pinned AsyncOpenAI with MockTransport; avoid sandbox platform thread."""
    state = {"kwargs": None, "http_client": None}
    real_class = openai.AsyncOpenAI
    monkeypatch.setattr(openai_base, "get_platform", lambda: "Linux")

    def inline_asyncify(function):
        async def wrapper(*args, **kwargs):
            return function(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(openai_base, "asyncify", inline_asyncify)

    def local_client(**kwargs):
        state["kwargs"] = kwargs
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        state["http_client"] = http_client
        return real_class(**kwargs, http_client=http_client)

    monkeypatch.setattr(openai, "AsyncOpenAI", local_client)
    return state


def _client() -> llm.LLMClient:
    return llm.LLMClient("openai", "synthetic-key", "gpt-5.6-luna")


def test_gate_fechado_falha_antes_de_criar_cliente(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: False)
    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **_kwargs: pytest.fail("SDK não deve ser criado"),
    )

    with pytest.raises(llm.LLMError, match="desativados"):
        _client().complete_typed("sistema", "mensagem", timeout_seconds=1)


def test_falha_do_gate_e_sanitizada_sem_criar_cliente(monkeypatch) -> None:
    def broken_gate():
        raise RuntimeError("segredo interno")

    monkeypatch.setattr(llm, "external_sends_allowed", broken_gate)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_k: pytest.fail("HTTP indevido"))

    with pytest.raises(llm.LLMError) as exc:
        _client().complete_typed("s", "u", timeout_seconds=1)

    assert "segredo" not in str(exc.value)


def test_schema_json_real_no_http_mock_transport_sem_retries(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-5.6-luna",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"handoff":false,"resposta":"Olá"}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    state = _local_sdk(monkeypatch, handler)
    result = _client().complete_typed("sistema", "mensagem", timeout_seconds=10)

    assert result == llm.TypedLLMResult(
        handoff=False,
        resposta="Olá",
        usage=llm.LLMUsage("gpt-5.6-luna", 10, 20, llm.estimate_cost("gpt-5.6-luna", 10, 20)),
    )
    assert len(calls) == 1
    body = calls[0]
    assert body["model"] == "gpt-5.6-luna"
    assert body["messages"] == [
        {"role": "system", "content": "sistema"},
        {"role": "user", "content": "mensagem"},
    ]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    schema = fmt["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["required"] == ["handoff", "resposta"]
    assert schema["schema"]["properties"] == {
        "handoff": {"type": "boolean"},
        "resposta": {"type": "string"},
    }
    assert state["kwargs"]["timeout"] == 4.0
    assert state["kwargs"]["max_retries"] == 0
    assert state["http_client"].is_closed is True


def test_handoff_descarta_resposta_e_respeita_saldo(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(
        monkeypatch,
        response=_response('{"handoff":true,"resposta":"não usar"}'),
    )

    result = _client().complete_typed("s", "u", timeout_seconds=0.5)

    assert result.handoff is True and result.resposta is None
    assert state["kwargs"]["timeout"] == 0.5
    assert state["kwargs"]["max_retries"] == 0
    assert state["closed"] is True and state["calls"] == 1


def test_resposta_de_1600_caracteres_e_aceita(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    _fake_sdk(
        monkeypatch,
        response=_response(json.dumps({"handoff": False, "resposta": "x" * 1600})),
    )

    result = _client().complete_typed("s", "u", timeout_seconds=1)

    assert result.resposta == "x" * 1600


def test_timeout_cancela_chamada_fecha_cliente_e_nao_repete(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, block=True)

    with pytest.raises(llm.LLMError, match="tempo limite"):
        _client().complete_typed("s", "u", timeout_seconds=0.02)

    assert state["calls"] == 1
    assert state["cancelled"] is True
    assert state["closed"] is True


@pytest.mark.parametrize(
    "response",
    [
        _response('{"handoff":"false","resposta":"ok"}'),
        _response('{"handoff":1,"resposta":"ok"}'),
        _response('{"handoff":false,"resposta":"ok","tenant":"outro"}'),
        _response('{"handoff":false,"resposta":"ok","model":"outro"}'),
        _response('{"handoff":false,"handoff":true,"resposta":"ok"}'),
        _response('{"handoff":false,"resposta":""}'),
        _response('{"handoff":false,"resposta":"   "}'),
        _response('{"handoff":false,"resposta":"x"'),
        _response('{"handoff":false,"resposta":true}'),
        _response('texto fora de JSON'),
        _response(None),
        _response(b'{"handoff":false,"resposta":"ok"}'),
        _response('{"handoff":false,"resposta":"ok"}', refusal="recusa"),
        _response('{"handoff":false,"resposta":"ok"}', tool_calls=[{"id": "tool"}]),
        _response('{"handoff":false,"resposta":"ok"}', finish_reason="length"),
        _response(choices=False),
        _response('{"handoff":false,"resposta":"ok"}', usage=SimpleNamespace(prompt_tokens=1)),
        _response('{"handoff":false,"resposta":"ok","extra":NaN}'),
        _response("[" * 1100 + "0" + "]" * 1100),
        _response('{"handoff":false,"resposta":"' + "x" * 1601 + '"}'),
        _response('{"handoff":true,"resposta":"' + "x" * 33000 + '"}'),
        _response(usage=SimpleNamespace(prompt_tokens=True, completion_tokens=1)),
        _response(usage=SimpleNamespace(prompt_tokens=10**400, completion_tokens=1)),
    ],
)
def test_resposta_invalida_falha_fechada_sem_expor_conteudo(monkeypatch, response) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, response=response)

    with pytest.raises(llm.LLMError) as exc:
        _client().complete_typed("s", "u", timeout_seconds=1)

    assert "tenant" not in str(exc.value)
    assert "recusa" not in str(exc.value)
    assert state["calls"] == 1 and state["closed"] is True


def test_status_http_erro_unico_e_mensagem_sanitizada(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": {"message": "segredo no provedor"}})

    state = _local_sdk(monkeypatch, handler)
    with pytest.raises(llm.LLMError) as exc:
        _client().complete_typed("s", "u", timeout_seconds=1)
    assert calls == 1
    assert state["http_client"].is_closed is True
    assert "segredo" not in str(exc.value)


def test_erro_do_sdk_nao_expoe_conteudo(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    state = _fake_sdk(monkeypatch, error=RuntimeError("segredo do provedor"))

    with pytest.raises(llm.LLMError) as exc:
        _client().complete_typed("s", "u", timeout_seconds=1)

    assert "segredo" not in str(exc.value)
    assert state["calls"] == 1 and state["closed"] is True


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, 10**400])
def test_saldo_invalido_nao_cria_cliente(monkeypatch, timeout) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_k: pytest.fail("HTTP indevido"))

    with pytest.raises(llm.LLMError):
        _client().complete_typed("s", "u", timeout_seconds=timeout)

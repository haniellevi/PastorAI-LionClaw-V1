"""Model allowlist, access validation, pricing and cheaper-only fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import llm


def test_catalog_has_safe_economic_default_and_monotonic_fallbacks() -> None:
    assert llm.DEFAULT_MODEL == "gpt-5.6-luna"
    assert {item.modelo for item in llm.MODEL_CATALOG} == llm.SUPPORTED_MODELS
    assert llm.MODEL_FALLBACKS == {
        "gpt-5.6-sol": ("gpt-5.6-terra", "gpt-5.6-luna"),
        "gpt-5.6-terra": ("gpt-5.6-luna",),
        "gpt-5.6-luna": (),
    }

    prices = {
        item.modelo: (
            item.input_usd_per_million,
            item.output_usd_per_million,
        )
        for item in llm.MODEL_CATALOG
    }
    for selected, fallbacks in llm.MODEL_FALLBACKS.items():
        for fallback in fallbacks:
            assert prices[fallback][0] < prices[selected][0]
            assert prices[fallback][1] < prices[selected][1]


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-5.6-luna", 1.4),
        ("gpt-5.6-terra", 14.0),
        ("gpt-5.6-sol", 35.0),
    ],
)
def test_estimate_cost_uses_current_per_million_prices(
    model: str, expected: float
) -> None:
    assert llm.estimate_cost(model, 1_000_000, 1_000_000) == expected


def test_unknown_model_is_rejected_before_any_provider_call(monkeypatch) -> None:
    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: pytest.fail("provider must not be called"),
    )

    with pytest.raises(llm.UnsupportedModelError):
        llm.validate_credential("openai", "sk-test", "modelo-inventado")

    with pytest.raises(llm.UnsupportedModelError):
        llm.LLMClient("openai", "sk-test", "modelo-inventado")


def test_validate_credential_retrieves_only_selected_model_without_completion(
    monkeypatch,
) -> None:
    retrieved: list[str] = []
    client_options: list[tuple[str, float, int]] = []

    class _Models:
        def retrieve(self, model: str):
            retrieved.append(model)
            return SimpleNamespace(id=model)

    def build_client(api_key: str, *, timeout: float, max_retries: int):
        client_options.append((api_key, timeout, max_retries))
        return SimpleNamespace(models=_Models())

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        build_client,
    )

    assert llm.validate_credential("openai", "sk-test", "gpt-5.6-terra") is True
    assert retrieved == ["gpt-5.6-terra"]
    assert client_options == [("sk-test", 8.0, 0)]


def test_validate_credential_rejects_model_not_visible_to_key(monkeypatch) -> None:
    class _Models:
        def retrieve(self, _model: str):
            return SimpleNamespace(id="gpt-5.6-luna")

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda _key, **_options: SimpleNamespace(models=_Models()),
    )

    with pytest.raises(llm.ModelAccessError, match="gpt-5.6-sol"):
        llm.validate_credential("openai", "sk-test", "gpt-5.6-sol")


def test_validate_credential_maps_missing_model_to_access_error(monkeypatch) -> None:
    import httpx
    from openai import NotFoundError

    class _Models:
        def retrieve(self, model: str):
            request = httpx.Request(
                "GET", f"https://api.openai.com/v1/models/{model}"
            )
            response = httpx.Response(404, request=request)
            raise NotFoundError("model not found", response=response, body=None)

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda _key, **_options: SimpleNamespace(models=_Models()),
    )

    with pytest.raises(llm.ModelAccessError, match="gpt-5.6-sol"):
        llm.validate_credential("openai", "sk-test", "gpt-5.6-sol")


def test_complete_falls_back_in_order_and_logs_actual_model(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    client = llm.LLMClient("openai", "sk-test", "gpt-5.6-sol")
    attempted: list[str] = []

    def fake_complete(model: str, _system: str, _user: str) -> llm.LLMResult:
        attempted.append(model)
        if model != "gpt-5.6-luna":
            raise llm.LLMModelUnavailableError(model)
        return llm.LLMResult(
            texto="ok",
            usage=llm.LLMUsage(
                modelo=model,
                tokens_in=10,
                tokens_out=20,
                custo=llm.estimate_cost(model, 10, 20),
            ),
        )

    monkeypatch.setattr(client, "_complete_openai_model", fake_complete)

    result = client.complete("system", "user")

    assert attempted == ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
    assert result.usage.modelo == "gpt-5.6-luna"


def test_luna_never_falls_back_to_a_more_expensive_model(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    client = llm.LLMClient("openai", "sk-test", "gpt-5.6-luna")
    attempted: list[str] = []

    def unavailable(model: str, _system: str, _user: str) -> llm.LLMResult:
        attempted.append(model)
        raise llm.LLMModelUnavailableError(model)

    monkeypatch.setattr(client, "_complete_openai_model", unavailable)

    with pytest.raises(llm.LLMModelUnavailableError):
        client.complete("system", "user")
    assert attempted == ["gpt-5.6-luna"]

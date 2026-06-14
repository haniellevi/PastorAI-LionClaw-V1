"""BYO-LLM provider abstraction (US-08/US-27 / RNF-20).

Each igreja brings its own provider credential (encrypted at rest). This module
keeps the provider SDK import lazy so the rest of the app — and the unit tests —
do not require network access or the heavy SDK at import time.

Two responsibilities:
  1. `validate_credential` — cheap auth check used by POST /agent/credential. An
     invalid key returns False (the credential is not activated); a transient
     network/provider error raises `LLMProviderError` so the caller can surface
     a 502 instead of silently disabling the agent.
  2. `LLMClient.complete` — the single call the orchestrator uses to phrase its
     unified reply, returning the text plus token usage for `ai_usage_logs`.
"""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai"})

# Indicative per-1k-token prices (USD) for cost estimation in ai_usage_logs.
# Kept conservative and overridable; cost is informative, not billing-grade.
_PRICE_PER_1K = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.005, 0.015),
}
_DEFAULT_PRICE = (0.0005, 0.0015)


class LLMError(Exception):
    """Base class for LLM service errors."""


class LLMProviderError(LLMError):
    """A transient/unexpected provider error (network, 5xx) — retryable."""


class UnsupportedProviderError(LLMError):
    """The requested provider is not supported."""


@dataclass(frozen=True)
class LLMUsage:
    """Token accounting + estimated cost for one completion."""

    modelo: str
    tokens_in: int
    tokens_out: int
    custo: float


@dataclass(frozen=True)
class LLMResult:
    """A single completion: the reply text plus its usage."""

    texto: str
    usage: LLMUsage


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost from token counts using a small price table."""
    price_in, price_out = _PRICE_PER_1K.get(model, _DEFAULT_PRICE)
    return round((tokens_in / 1000) * price_in + (tokens_out / 1000) * price_out, 6)


def _require_supported(provedor: str) -> str:
    provider = (provedor or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise UnsupportedProviderError(f"Provedor não suportado: {provedor!r}")
    return provider


def _build_openai_client(api_key: str):
    """Lazily construct an OpenAI client (import deferred to call time)."""
    from openai import OpenAI  # noqa: PLC0415 - lazy import by design

    return OpenAI(api_key=api_key, timeout=20.0, max_retries=1)


def validate_credential(provedor: str, api_key: str) -> bool:
    """Return True when the credential authenticates against the provider.

    - Returns False for an authentication failure (invalid/revoked key): the
      credential must NOT be activated.
    - Raises LLMProviderError for network/transient errors so the endpoint can
      answer 502 rather than persist a falsely-invalid credential.
    """
    provider = _require_supported(provedor)
    if not api_key or not api_key.strip():
        return False

    if provider == "openai":
        from openai import (  # noqa: PLC0415 - lazy import by design
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            PermissionDeniedError,
        )

        client = _build_openai_client(api_key.strip())
        try:
            client.models.list()
            return True
        except (AuthenticationError, PermissionDeniedError):
            return False
        except APIStatusError as exc:
            # 401/403 -> invalid; other statuses are provider-side problems.
            if exc.status_code in (401, 403):
                return False
            raise LLMProviderError(f"Erro do provedor LLM: {exc.status_code}") from exc
        except APIConnectionError as exc:
            raise LLMProviderError("Falha de conexão com o provedor LLM") from exc

    return False


class LLMClient:
    """Thin wrapper over a provider chat-completions call (orchestrator reply)."""

    def __init__(self, provedor: str, api_key: str, model: str) -> None:
        self.provedor = _require_supported(provedor)
        self._api_key = api_key
        self.model = model

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """Generate a single assistant reply and return text + usage."""
        if self.provedor == "openai":
            client = _build_openai_client(self._api_key)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            texto = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None)
            tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
            tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
            return LLMResult(
                texto=texto,
                usage=LLMUsage(
                    modelo=self.model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    custo=estimate_cost(self.model, tokens_in, tokens_out),
                ),
            )
        raise UnsupportedProviderError(self.provedor)

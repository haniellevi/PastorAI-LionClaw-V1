"""BYO-LLM provider abstraction (US-08/US-27 / RNF-20).

Each igreja brings its own provider credential (encrypted at rest) and chooses
one model from the server-side allowlist below. The provider SDK import remains
lazy so ordinary app imports and unit tests do not require network access.

The allowlist is also the single source of truth for the model selector, price
estimation and controlled fallback. A fallback may only move to a model with a
lower price profile; it never increases a tenant's cost silently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.outbound_guard import external_sends_allowed, log_suppressed

logger = logging.getLogger("pastorai.llm")

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai"})
DEFAULT_MODEL = "gpt-5.6-luna"
PRICING_UPDATED_AT = "2026-08-08"


@dataclass(frozen=True)
class LLMModelSpec:
    """One selectable model and its indicative public API price snapshot."""

    modelo: str
    nome: str
    perfil: str
    input_usd_per_million: float
    output_usd_per_million: float
    recomendado: bool = False


MODEL_CATALOG: tuple[LLMModelSpec, ...] = (
    LLMModelSpec(
        modelo="gpt-5.6-luna",
        nome="Luna — econômico",
        perfil="Alto volume e tarefas diretas; melhor custo para o atendimento cotidiano.",
        input_usd_per_million=0.20,
        output_usd_per_million=1.20,
        recomendado=True,
    ),
    LLMModelSpec(
        modelo="gpt-5.6-terra",
        nome="Terra — equilibrado",
        perfil="Mais capacidade para conversas e decisões complexas, com custo intermediário.",
        input_usd_per_million=2.00,
        output_usd_per_million=12.00,
    ),
    LLMModelSpec(
        modelo="gpt-5.6-sol",
        nome="Sol — avançado",
        perfil="Maior qualidade para os casos mais difíceis; use quando o ganho justificar o custo.",
        input_usd_per_million=5.00,
        output_usd_per_million=30.00,
    ),
)

_MODEL_BY_ID = {item.modelo: item for item in MODEL_CATALOG}
SUPPORTED_MODELS: frozenset[str] = frozenset(_MODEL_BY_ID)

# The chain is deliberately monotonic in price: Sol -> Terra -> Luna.
MODEL_FALLBACKS: dict[str, tuple[str, ...]] = {
    "gpt-5.6-sol": ("gpt-5.6-terra", "gpt-5.6-luna"),
    "gpt-5.6-terra": ("gpt-5.6-luna",),
    "gpt-5.6-luna": (),
}


class LLMError(Exception):
    """Base class for LLM service errors."""


class LLMProviderError(LLMError):
    """A transient/unexpected provider error (network, auth, 5xx)."""


class UnsupportedProviderError(LLMError):
    """The requested provider is not supported."""


class UnsupportedModelError(LLMError):
    """The requested model is outside the PastorAI allowlist."""


class ModelAccessError(LLMError):
    """The key authenticates, but the selected model is not available to it."""


class LLMModelUnavailableError(LLMError):
    """A selected model is unavailable and may use its cheaper fallback."""


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


def _require_supported_model(model: str) -> str:
    selected = (model or "").strip().lower()
    if selected not in SUPPORTED_MODELS:
        raise UnsupportedModelError(f"Modelo não permitido: {model!r}")
    return selected


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost using the public per-million-token price snapshot."""
    spec = _MODEL_BY_ID[_require_supported_model(model)]
    return round(
        (tokens_in / 1_000_000) * spec.input_usd_per_million
        + (tokens_out / 1_000_000) * spec.output_usd_per_million,
        6,
    )


def _require_supported(provedor: str) -> str:
    provider = (provedor or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise UnsupportedProviderError(f"Provedor não suportado: {provedor!r}")
    return provider


def _build_openai_client(api_key: str):
    """Lazily construct an OpenAI client (import deferred to call time)."""
    from openai import OpenAI  # noqa: PLC0415 - lazy import by design

    return OpenAI(api_key=api_key, timeout=20.0, max_retries=1)


def validate_credential(
    provedor: str, api_key: str, model: str = DEFAULT_MODEL
) -> bool:
    """Validate both the credential and access to the selected model.

    Listing models authenticates without consuming completion tokens. A valid
    key that cannot see the selected model raises ``ModelAccessError``; an
    invalid/revoked key returns ``False``; transient provider failures raise
    ``LLMProviderError`` so callers never persist a false validation result.
    """
    provider = _require_supported(provedor)
    selected = _require_supported_model(model)
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
            page = client.models.list()
            rows = getattr(page, "data", page)
            available = {
                str(getattr(item, "id", "")).strip().lower() for item in rows
            }
            if selected not in available:
                raise ModelAccessError(
                    f"A credencial não possui acesso ao modelo {selected}"
                )
            return True
        except ModelAccessError:
            raise
        except (AuthenticationError, PermissionDeniedError):
            return False
        except APIStatusError as exc:
            if exc.status_code in (401, 403):
                return False
            raise LLMProviderError(
                f"Erro do provedor LLM: {exc.status_code}"
            ) from exc
        except APIConnectionError as exc:
            raise LLMProviderError("Falha de conexão com o provedor LLM") from exc

    return False


class LLMClient:
    """Thin wrapper over provider completions with cheaper-only fallback."""

    def __init__(self, provedor: str, api_key: str, model: str) -> None:
        self.provedor = _require_supported(provedor)
        self._api_key = api_key
        self.model = _require_supported_model(model)

    def _complete_openai_model(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> LLMResult:
        from openai import (  # noqa: PLC0415 - lazy import by design
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
        )

        client = _build_openai_client(self._api_key)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except AuthenticationError as exc:
            raise LLMProviderError("Credencial LLM rejeitada pelo provedor") from exc
        except APIStatusError as exc:
            if exc.status_code in (403, 404, 429):
                raise LLMModelUnavailableError(
                    f"Modelo {model} indisponível: HTTP {exc.status_code}"
                ) from exc
            raise LLMProviderError(
                f"Erro do provedor LLM: {exc.status_code}"
            ) from exc
        except APIConnectionError as exc:
            raise LLMProviderError("Falha de conexão com o provedor LLM") from exc

        texto = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        return LLMResult(
            texto=texto,
            usage=LLMUsage(
                modelo=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                custo=estimate_cost(model, tokens_in, tokens_out),
            ),
        )

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """Generate one reply, falling back only to cheaper allowed models."""
        if not external_sends_allowed():
            log_suppressed("LLM", "complete")
            return LLMResult(
                texto="[Resposta simulada — envios externos desativados neste ambiente.]",
                usage=LLMUsage(
                    modelo=self.model, tokens_in=0, tokens_out=0, custo=0.0
                ),
            )

        if self.provedor != "openai":
            raise UnsupportedProviderError(self.provedor)

        candidates = (self.model, *MODEL_FALLBACKS[self.model])
        for index, candidate in enumerate(candidates):
            try:
                return self._complete_openai_model(
                    candidate, system_prompt, user_prompt
                )
            except LLMModelUnavailableError:
                if index == len(candidates) - 1:
                    raise
                logger.warning(
                    "LLM model %s unavailable; falling back to cheaper model %s",
                    candidate,
                    candidates[index + 1],
                )

        raise LLMProviderError("Nenhum modelo LLM disponível")  # pragma: no cover

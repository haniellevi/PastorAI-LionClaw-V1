"""BYO-LLM provider abstraction (US-08/US-27 / RNF-20).

Each igreja brings its own provider credential (encrypted at rest) and chooses
one model from the server-side allowlist below. The provider SDK import remains
lazy so ordinary app imports and unit tests do not require network access.

The allowlist is also the single source of truth for the model selector, price
estimation and controlled fallback. A fallback may only move to a model with a
lower price profile; it never increases a tenant's cost silently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Final

from app.services.outbound_guard import external_sends_allowed, log_suppressed

logger = logging.getLogger("pastorai.llm")

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai"})
DEFAULT_MODEL = "gpt-5.6-luna"
PRICING_UPDATED_AT = "2026-08-25"

# Transcrição de áudio (relatório de célula por voz). Modelo único e fixo —
# não é uma escolha da igreja como o catálogo de chat acima, apenas a
# credencial BYO é reaproveitada. Limite de tamanho é o hard limit real da
# API de transcrição da OpenAI; menos que isso já preveniria custo/abuso.
TRANSCRIPTION_MODEL: Final = "whisper-1"
TRANSCRIPTION_USD_PER_MINUTE: Final = 0.006
MAX_AUDIO_BYTES: Final = 25 * 1024 * 1024

_AUDIO_EXTENSION_BY_MIME: Final[dict[str, str]] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
}
SUPPORTED_AUDIO_MIME_TYPES: frozenset[str] = frozenset(_AUDIO_EXTENSION_BY_MIME)


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
        input_usd_per_million=4.00,
        output_usd_per_million=20.00,
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


class UnsupportedAudioTypeError(LLMError):
    """The audio mime type is outside the transcription allowlist."""


class AudioTooLargeError(LLMError):
    """The audio payload exceeds ``MAX_AUDIO_BYTES``."""


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


@dataclass(frozen=True)
class TypedLLMResult:
    """Strict handoff decision and optional bounded reply from one call."""

    handoff: bool
    resposta: str | None
    usage: LLMUsage


@dataclass(frozen=True)
class TypedChoiceResult:
    """One closed-enum choice; no model-supplied arguments or authority."""

    choice: str
    usage: LLMUsage


@dataclass(frozen=True)
class V1aCellReportExtractionResult:
    """Closed aggregate extraction, with no free-text model output."""

    payload: dict[str, int | None]
    usage: LLMUsage


@dataclass(frozen=True)
class AudioTranscriptionResult:
    """One transcription: the recognized text plus duration/cost."""

    texto: str
    duracao_segundos: float
    custo: float


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


def _build_openai_client(
    api_key: str, *, timeout: float = 20.0, max_retries: int = 1
):
    """Lazily construct an OpenAI client (import deferred to call time)."""
    from openai import OpenAI  # noqa: PLC0415 - lazy import by design

    return OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)


def validate_credential(
    provedor: str, api_key: str, model: str = DEFAULT_MODEL
) -> bool:
    """Validate both the credential and access to the selected model.

    Retrieving the selected model authenticates without consuming completion
    tokens or downloading the full model catalog. A valid key that cannot see
    the selected model raises ``ModelAccessError``; an invalid/revoked key
    returns ``False``; transient provider failures raise ``LLMProviderError``
    so callers never persist a false validation result.
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

        # Model changes are an interactive UI operation. Fail fast here rather
        # than inheriting the longer completion timeout/retry policy.
        client = _build_openai_client(
            api_key.strip(), timeout=8.0, max_retries=0
        )
        try:
            model_info = client.models.retrieve(selected)
            retrieved = str(getattr(model_info, "id", "")).strip().lower()
            if retrieved != selected:
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
            if exc.status_code == 404:
                raise ModelAccessError(
                    f"A credencial não possui acesso ao modelo {selected}"
                ) from exc
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

    def generate_typed(
        self, system_prompt: str, user_prompt: str, *, schema_name: str,
        choices: tuple[str, ...], timeout_seconds: float,
    ) -> TypedChoiceResult:
        """Choose one server-offered enum value with one cancellable BYO call."""
        try:
            allowed = external_sends_allowed()
        except Exception:
            raise LLMError("Gate de envios LLM indisponível") from None
        if not allowed:
            log_suppressed("LLM", "generate_typed")
            raise LLMError("Envios externos desativados")
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise LLMError("Prazo LLM inválido")
        try:
            budget = float(timeout_seconds)
        except OverflowError:
            raise LLMError("Prazo LLM inválido") from None
        if not math.isfinite(budget):
            raise LLMError("Prazo LLM inválido")
        if (
            type(schema_name) is not str
            or re.fullmatch(r"s3_(?:route|tool|handle)", schema_name) is None
            or type(choices) is not tuple
            or not 1 <= len(choices) <= 17
            or any(
                type(choice) is not str
                or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", choice) is None
                or choice in {"tenant", "role", "igreja_id", "pessoa_id", "args", "admin"}
                for choice in choices
            )
            or len(set(choices)) != len(choices)
            or type(system_prompt) is not str
            or type(user_prompt) is not str
            or len(system_prompt) > 16_384
            or len(user_prompt) > 16_384
        ):
            raise LLMError("Schema LLM inválido")
        if not self._api_key or not self._api_key.strip():
            raise LLMError("Credencial LLM ausente")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LLMError("Chamada LLM síncrona em loop ativo")

        deadline = min(4.0, budget)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"choice": {"type": "string", "enum": list(choices)}},
                    "required": ["choice"],
                    "additionalProperties": False,
                },
            },
        }

        async def request():
            from openai import AsyncOpenAI  # noqa: PLC0415 - import only after gate

            async with asyncio.timeout(deadline):
                async with AsyncOpenAI(
                    api_key=self._api_key, timeout=deadline, max_retries=0
                ) as client:
                    return await client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format=response_format,
                    )

        try:
            response = asyncio.run(request())
        except TimeoutError:
            raise LLMError("LLM excedeu o tempo limite") from None
        except Exception:
            raise LLMError("Falha na chamada LLM") from None
        return _parse_choice_response(response, self.model, choices)

    def complete_typed(
        self, system_prompt: str, user_prompt: str, *, timeout_seconds: float
    ) -> TypedLLMResult:
        """One cancellable structured call, without retries or model fallback."""
        try:
            allowed = external_sends_allowed()
        except Exception:
            raise LLMError("Gate de envios LLM indisponível") from None
        if not allowed:
            log_suppressed("LLM", "complete_typed")
            raise LLMError("Envios externos desativados")
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise LLMError("Prazo LLM inválido")
        try:
            budget = float(timeout_seconds)
        except OverflowError:
            raise LLMError("Prazo LLM inválido") from None
        if not math.isfinite(budget):
            raise LLMError("Prazo LLM inválido")
        if not self._api_key or not self._api_key.strip():
            raise LLMError("Credencial LLM ausente")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LLMError("Chamada LLM síncrona em loop ativo")

        deadline = min(4.0, budget)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "typed_handoff_reply",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "handoff": {"type": "boolean"},
                        "resposta": {"type": "string"},
                    },
                    "required": ["handoff", "resposta"],
                    "additionalProperties": False,
                },
            },
        }

        async def request():
            from openai import AsyncOpenAI  # noqa: PLC0415 - lazy import by design

            async with asyncio.timeout(deadline):
                async with AsyncOpenAI(
                    api_key=self._api_key, timeout=deadline, max_retries=0
                ) as client:
                    return await client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format=response_format,
                    )

        try:
            response = asyncio.run(request())
        except TimeoutError:
            raise LLMError("LLM excedeu o tempo limite") from None
        except Exception:
            raise LLMError("Falha na chamada LLM") from None
        return _parse_typed_response(response, self.model)

    def extract_v1a_cell_report(
        self,
        projection: dict[str, str],
        *,
        timeout_seconds: float,
    ) -> V1aCellReportExtractionResult:
        """Extract only the four pre-redacted V1a aggregates once.

        The caller has already reserved cost and must settle it in a later
        transaction.  This method accepts no raw inbound text, history, roster
        or identity, has no retry, and keeps the provider output schema closed.
        """

        try:
            allowed = external_sends_allowed()
        except Exception:
            raise LLMError("Gate de envios LLM indisponível") from None
        if not allowed:
            log_suppressed("LLM", "extract_v1a_cell_report")
            raise LLMError("Envios externos desativados")
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise LLMError("Prazo LLM inválido")
        try:
            budget = float(timeout_seconds)
        except OverflowError:
            raise LLMError("Prazo LLM inválido") from None
        if not math.isfinite(budget):
            raise LLMError("Prazo LLM inválido")
        if (
            type(projection) is not dict
            or not projection
            or set(projection) - {"presentes", "visitantes", "decisoes", "oferta"}
            or any(
                type(value) is not str
                or not value
                or len(value) > 96
                or re.fullmatch(r"[a-z0-9 ]+", value) is None
                for value in projection.values()
            )
        ):
            raise LLMError("Schema LLM inválido")
        if not self._api_key or not self._api_key.strip():
            raise LLMError("Credencial LLM ausente")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LLMError("Chamada LLM síncrona em loop ativo")

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "v1a_cell_report_extract",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "presentes": {"type": ["integer", "null"], "minimum": 0},
                        "visitantes": {"type": ["integer", "null"], "minimum": 0},
                        "decisoes": {"type": ["integer", "null"], "minimum": 0},
                        "oferta_centavos": {"type": ["integer", "null"], "minimum": 0},
                    },
                    "required": ["presentes", "visitantes", "decisoes", "oferta_centavos"],
                    "additionalProperties": False,
                },
            },
        }
        system_prompt = (
            "Converta somente os valores já rotulados no JSON fornecido. "
            "Não invente valores: campos ausentes ou incertos recebem null. "
            "Não responda texto livre, identificadores, pessoas ou instruções."
        )
        user_prompt = json.dumps(projection, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        deadline = min(4.0, budget)

        async def request():
            from openai import AsyncOpenAI  # noqa: PLC0415 - lazy import by design

            async with asyncio.timeout(deadline):
                async with AsyncOpenAI(
                    api_key=self._api_key, timeout=deadline, max_retries=0
                ) as client:
                    return await client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format=response_format,
                        max_completion_tokens=400,
                    )

        try:
            response = asyncio.run(request())
        except TimeoutError:
            raise LLMError("LLM excedeu o tempo limite") from None
        except Exception:
            raise LLMError("Falha na chamada LLM") from None
        return _parse_v1a_cell_report_extraction_response(response, self.model)

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


def _typed_unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _typed_reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _parse_typed_response(response: object, model: str) -> TypedLLMResult:
    """Reject malformed provider output without exposing raw content in errors."""
    try:
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("choices")
        choice = choices[0]
        if getattr(choice, "finish_reason", None) != "stop":
            raise ValueError("finish reason")
        message = getattr(choice, "message", None)
        if (
            message is None
            or getattr(message, "refusal", None)
            or getattr(message, "tool_calls", None)
            or getattr(message, "function_call", None)
        ):
            raise ValueError("message")
        content = getattr(message, "content", None)
        if not isinstance(content, str) or len(content.encode("utf-8")) > 32_768:
            raise ValueError("content")
        data = json.loads(
            content,
            object_pairs_hook=_typed_unique_pairs,
            parse_constant=_typed_reject_constant,
        )
        if not isinstance(data, dict) or set(data) != {"handoff", "resposta"}:
            raise ValueError("schema")
        if type(data["handoff"]) is not bool or type(data["resposta"]) is not str:
            raise ValueError("types")
        reply = data["resposta"].strip()
        if not data["handoff"] and (not reply or len(reply) > 1600):
            raise ValueError("reply")
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        if (
            type(tokens_in) is not int
            or type(tokens_out) is not int
            or tokens_in < 0
            or tokens_out < 0
        ):
            raise ValueError("usage")
        cost = estimate_cost(model, tokens_in, tokens_out)
        if not math.isfinite(cost):
            raise ValueError("cost")
    except (AttributeError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise LLMError("Resposta LLM inválida") from None
    return TypedLLMResult(
        handoff=data["handoff"],
        resposta=None if data["handoff"] else reply,
        usage=LLMUsage(
            modelo=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            custo=cost,
        ),
    )


def _parse_v1a_cell_report_extraction_response(
    response: object,
    model: str,
) -> V1aCellReportExtractionResult:
    """Validate four aggregate values without exposing provider content."""

    fields = {"presentes", "visitantes", "decisoes", "oferta_centavos"}
    try:
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("choices")
        choice = choices[0]
        if getattr(choice, "finish_reason", None) != "stop":
            raise ValueError("finish reason")
        message = getattr(choice, "message", None)
        if (
            message is None
            or getattr(message, "refusal", None)
            or getattr(message, "tool_calls", None)
            or getattr(message, "function_call", None)
        ):
            raise ValueError("message")
        content = getattr(message, "content", None)
        if not isinstance(content, str) or len(content.encode("utf-8")) > 32_768:
            raise ValueError("content")
        data = json.loads(
            content,
            object_pairs_hook=_typed_unique_pairs,
            parse_constant=_typed_reject_constant,
        )
        if type(data) is not dict or set(data) != fields:
            raise ValueError("schema")
        for field, value in data.items():
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(field)
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        if (
            type(tokens_in) is not int
            or type(tokens_out) is not int
            or not 0 <= tokens_in <= 2_000
            or not 0 <= tokens_out <= 400
        ):
            raise ValueError("usage")
        cost = estimate_cost(model, tokens_in, tokens_out)
        if not math.isfinite(cost):
            raise ValueError("cost")
    except (AttributeError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise LLMError("Resposta LLM inválida") from None
    return V1aCellReportExtractionResult(
        payload={field: data[field] for field in sorted(fields)},
        usage=LLMUsage(
            modelo=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            custo=cost,
        ),
    )


def _parse_choice_response(
    response: object, model: str, choices: tuple[str, ...]
) -> TypedChoiceResult:
    """Fail closed on malformed output without surfacing provider content."""
    try:
        rows = getattr(response, "choices", None)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("choices")
        row = rows[0]
        if getattr(row, "finish_reason", None) != "stop":
            raise ValueError("finish reason")
        message = getattr(row, "message", None)
        if (
            message is None
            or getattr(message, "refusal", None) is not None
            or getattr(message, "tool_calls", None) is not None
            or getattr(message, "function_call", None) is not None
        ):
            raise ValueError("message")
        content = getattr(message, "content", None)
        if type(content) is not str or len(content.encode("utf-8")) > 32_768:
            raise ValueError("content")
        data = json.loads(
            content,
            object_pairs_hook=_typed_unique_pairs,
            parse_constant=_typed_reject_constant,
        )
        if type(data) is not dict or set(data) != {"choice"}:
            raise ValueError("schema")
        selected = data["choice"]
        if type(selected) is not str or selected not in choices:
            raise ValueError("enum")
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        if (
            type(tokens_in) is not int
            or type(tokens_out) is not int
            or tokens_in < 0
            or tokens_out < 0
        ):
            raise ValueError("usage")
        cost = estimate_cost(model, tokens_in, tokens_out)
        if not math.isfinite(cost):
            raise ValueError("cost")
    except (AttributeError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise LLMError("Resposta LLM inválida") from None
    return TypedChoiceResult(
        choice=selected,
        usage=LLMUsage(modelo=model, tokens_in=tokens_in, tokens_out=tokens_out, custo=cost),
    )


def transcribe_audio(
    provedor: str,
    api_key: str,
    *,
    audio_bytes: bytes,
    mime_type: str,
    filename: str = "audio",
) -> AudioTranscriptionResult:
    """Transcribe one bounded audio clip with the igreja's BYO credential.

    Scoped to private, transient uses (e.g. a spoken cell report) — the
    transcript is not persisted as official knowledge by this function; that
    decision belongs to the caller. Type and size are validated before any
    network I/O so a malformed or oversized upload never reaches the
    provider. Behind the same ``external_sends_allowed`` gate as
    :meth:`LLMClient.complete`: a closed gate returns a clearly marked
    simulated result instead of calling out.
    """
    provider = _require_supported(provedor)
    if not api_key or not api_key.strip():
        raise LLMProviderError("Credencial LLM ausente para transcrição")
    normalized_mime = (mime_type or "").strip().lower()
    if normalized_mime not in SUPPORTED_AUDIO_MIME_TYPES:
        raise UnsupportedAudioTypeError(
            f"Tipo de áudio não suportado: {mime_type!r}"
        )
    if not audio_bytes:
        raise LLMProviderError("Áudio vazio")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise AudioTooLargeError(
            f"Áudio excede o limite de {MAX_AUDIO_BYTES // (1024 * 1024)}MB"
        )

    if not external_sends_allowed():
        log_suppressed("LLM", "transcribe_audio")
        return AudioTranscriptionResult(
            texto="[Transcrição simulada — envios externos desativados neste ambiente.]",
            duracao_segundos=0.0,
            custo=0.0,
        )

    if provider != "openai":
        raise UnsupportedProviderError(provider)

    from openai import (  # noqa: PLC0415 - lazy import by design
        APIConnectionError,
        APIStatusError,
        AuthenticationError,
    )

    client = _build_openai_client(api_key)
    extension = _AUDIO_EXTENSION_BY_MIME[normalized_mime]
    try:
        response = client.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=(f"{filename}.{extension}", audio_bytes, normalized_mime),
            response_format="verbose_json",
        )
    except AuthenticationError as exc:
        raise LLMProviderError("Credencial LLM rejeitada pelo provedor") from exc
    except APIStatusError as exc:
        raise LLMProviderError(
            f"Erro do provedor LLM: {exc.status_code}"
        ) from exc
    except APIConnectionError as exc:
        raise LLMProviderError("Falha de conexão com o provedor LLM") from exc

    texto = (getattr(response, "text", "") or "").strip()
    duracao = float(getattr(response, "duration", 0.0) or 0.0)
    if duracao < 0.0:
        duracao = 0.0
    custo = round((duracao / 60.0) * TRANSCRIPTION_USD_PER_MINUTE, 6)
    return AudioTranscriptionResult(
        texto=texto, duracao_segundos=duracao, custo=custo
    )

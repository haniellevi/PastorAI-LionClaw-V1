"""Transporte estrito das decisões Choice B/C/D da S3.

Este módulo só serializa escolhas fechadas e interpreta a resposta do Jev. Ele
não resolve identidade, papel, catálogo, handles reais, banco ou autorização.
O orquestrador futuro deve aplicar B, C e D de modo sequencial e revalidar seus
gates entre chamadas.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

import httpx

from app.services.outbound_guard import log_suppressed
from app.services.semantic_triage import (
    EffectiveTriageSettings,
    redact_for_egress,
    tier_a_egress_allowed,
)


S3_ROUTING_APPROVED_RELEASE_ID: Final[str | None] = None
S3_ROUTING_HTTP_MAX_SECONDS: Final[float] = 0.6
MAX_ROUTING_RESPONSE_BYTES: Final[int] = 64 * 1024
MAX_ROUTING_TEXT_CHARS: Final[int] = 2000
MAX_CATALOG_OPTIONS: Final[int] = 8
MAX_CANDIDATE_HANDLES: Final[int] = 16
MAX_CANDIDATE_SUMMARY_CHARS: Final[int] = 240
_NONE_OPTION: Final[str] = "nenhuma"
_TOOL_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z_]{0,47}$")
_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_LONG_NUMERIC_ID_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{7,}\b")
_CONTEXT_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:tenant(?:_id)?|igreja_id|papel|roles?|app_user_id|pessoa_id|"
    r"conversation_id|clerk_user_id)\b",
    re.IGNORECASE,
)


class RouteChoice(str, Enum):
    """As quatro rotas estáveis que B pode devolver."""

    PUBLICA = "publica"
    RESTRITA = "restrita"
    PASTORAL = "pastoral"
    OUTRO = "outro"


ROUTE_CHOICES: Final[tuple[str, ...]] = tuple(choice.value for choice in RouteChoice)


class RoutingError(str, Enum):
    """Falhas enumeradas e auditáveis, sem eco do conteúdo recebido."""

    GATE_FECHADO = "gate_fechado"
    HTTP = "http"
    LIMITE_ENTRADA = "limite_entrada"
    ORCAMENTO_ESGOTADO = "orcamento_esgotado"
    SCHEMA_INVALIDO = "schema_invalido"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ChoiceDecision:
    """Uma única Choice validada sem transformar probabilidade em autorização."""

    choice: str | None
    probabilities: Mapping[str, float]
    confidence: float | None
    erro: RoutingError | None
    latencia_ms: int


def _failure(error: RoutingError, *, latencia_ms: int = 0) -> ChoiceDecision:
    return ChoiceDecision(
        choice=None,
        probabilities=MappingProxyType({}),
        confidence=None,
        erro=error,
        latencia_ms=max(0, int(latencia_ms)),
    )


def _require_text(texto: object) -> str:
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("texto inválido")
    if len(texto) > MAX_ROUTING_TEXT_CHARS:
        raise OverflowError("texto acima do limite")
    return texto


def _require_route(route: object) -> RouteChoice:
    if not isinstance(route, RouteChoice):
        raise ValueError("rota inválida")
    return route


def _require_tool_code(value: object) -> str:
    if type(value) is not str or not _TOOL_CODE_RE.fullmatch(value):
        raise ValueError("catálogo inválido")
    if value == _NONE_OPTION:
        raise ValueError("catálogo inválido")
    return value


def _require_catalog(allowed_tools: object) -> tuple[str, ...]:
    if not isinstance(allowed_tools, (tuple, list)):
        raise ValueError("catálogo inválido")
    if not 1 <= len(allowed_tools) <= MAX_CATALOG_OPTIONS:
        raise ValueError("catálogo inválido")
    tools = tuple(_require_tool_code(item) for item in allowed_tools)
    if len(set(tools)) != len(tools):
        raise ValueError("catálogo inválido")
    return tools


def _require_candidate_summaries(candidates: object) -> dict[str, str]:
    if not isinstance(candidates, Mapping):
        raise ValueError("candidatos inválidos")
    if not 1 <= len(candidates) <= MAX_CANDIDATE_HANDLES:
        raise ValueError("candidatos inválidos")
    handles = tuple(f"h{index}" for index in range(1, len(candidates) + 1))
    if set(candidates) != set(handles):
        raise ValueError("candidatos inválidos")
    summaries: dict[str, str] = {}
    for handle in handles:
        summary = candidates[handle]
        if type(summary) is not str or not summary.strip():
            raise ValueError("candidatos inválidos")
        if len(summary) > MAX_CANDIDATE_SUMMARY_CHARS:
            raise ValueError("candidatos inválidos")
        if (
            _UUID_RE.search(summary)
            or _LONG_NUMERIC_ID_RE.search(summary)
            or _CONTEXT_FIELD_RE.search(summary)
        ):
            raise ValueError("candidatos inválidos")
        summaries[handle] = redact_for_egress(summary).replace("<", "[").replace(
            ">", "]"
        )
    return summaries


def _base_state(texto: str) -> dict[str, str]:
    return {
        "mensagem": redact_for_egress(texto),
        "canal": "whatsapp_atendimento",
    }


def build_choice_b_request(
    texto: str, *, model: str, allowed_routes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Monta B só com rotas ofertadas; o default preserva o Choice anterior."""

    text = _require_text(texto)
    routes = ROUTE_CHOICES if allowed_routes is None else tuple(allowed_routes)
    criteria_by_route = {
        "publica": "Pede informação explicitamente pública.",
        "restrita": "Pede consulta ou ação que exige autorização e confirmação.",
        "pastoral": "Pede conversa pastoral ou cuidado humano.",
        "outro": "Nenhuma rota anterior é adequada.",
        "handoff": "Crise, risco de autolesão ou pedido de humano prevalece sobre qualquer ação.",
        "nenhuma": "Nenhuma opção ofertada responde à mensagem.",
    }
    if (
        not routes or len(routes) > len(criteria_by_route)
        or len(set(routes)) != len(routes)
        or any(type(route) is not str or route not in criteria_by_route for route in routes)
    ):
        raise ValueError("rotas inválidas")
    return {
        "state": _base_state(text),
        "model": model,
        "questions": {
            "rota_s3": {
                "type": "choice",
                "instructions": "Qual rota melhor descreve a mensagem?",
                "criteria": {route: criteria_by_route[route] for route in routes},
            }
        },
    }


def build_choice_c_request(
    texto: str,
    *,
    route: RouteChoice,
    allowed_tools: Sequence[str],
    model: str,
    include_handoff: bool = False,
) -> dict[str, Any]:
    """Monta C exclusivamente a partir do catálogo já autorizado pelo servidor."""

    text = _require_text(texto)
    route_value = _require_route(route)
    tools = _require_catalog(allowed_tools)
    if type(include_handoff) is not bool:
        raise ValueError("handoff inválido")
    criteria = {
        tool: f"A opção fechada {tool} responde à rota e à mensagem."
        for tool in tools
    }
    criteria[_NONE_OPTION] = "Nenhuma opção ofertada responde à mensagem."
    if include_handoff:
        criteria["handoff"] = "Crise, risco de autolesão ou pedido de humano exige atendimento humano."
    state = _base_state(text)
    state["rota"] = route_value.value
    return {
        "state": state,
        "model": model,
        "questions": {
            "ferramenta_s3": {
                "type": "choice",
                "instructions": "Escolha somente uma opção do catálogo ofertado.",
                "criteria": criteria,
            }
        },
    }


def build_choice_d_request(
    texto: str,
    *,
    route: RouteChoice,
    tool: str,
    candidate_summaries: Mapping[str, str],
    model: str,
    include_handoff: bool = False,
) -> dict[str, Any]:
    """Monta D com fatos mínimos derivados pelo backend autorizado.

    ``candidate_summaries`` vem exclusivamente de uma projeção server-side já
    filtrada. Nunca aceite texto do usuário, ID, tenant ou atributos de papel
    nessa fronteira. Esta função só preserva handles efêmeros e redacta texto.
    """

    text = _require_text(texto)
    route_value = _require_route(route)
    tool_code = _require_tool_code(tool)
    candidates = _require_candidate_summaries(candidate_summaries)
    if type(include_handoff) is not bool:
        raise ValueError("handoff inválido")
    criteria = {
        handle: summary for handle, summary in candidates.items()
    }
    criteria["nenhum"] = "Nenhum candidato ofertado atende à mensagem."
    if include_handoff:
        criteria["handoff"] = "Crise, risco de autolesão ou pedido de humano exige atendimento humano."
    state = _base_state(text)
    state["rota"] = route_value.value
    state["ferramenta"] = tool_code
    return {
        "state": state,
        "model": model,
        "questions": {
            "candidato_s3": {
                "type": "choice",
                "instructions": "Escolha somente um handle ofertado ou nenhum.",
                "criteria": criteria,
            }
        },
    }


def _strict_probability(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("probabilidade inválida")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("probabilidade inválida") from exc
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("probabilidade inválida")
    return number


def _parse_options(allowed_options: object) -> tuple[str, ...]:
    if not isinstance(allowed_options, (tuple, list)):
        raise ValueError("opções inválidas")
    options = tuple(allowed_options)
    if not options or any(type(option) is not str for option in options):
        raise ValueError("opções inválidas")
    if len(set(options)) != len(options):
        raise ValueError("opções inválidas")
    return options


def parse_choice_response(
    body: object,
    *,
    question_id: str,
    allowed_options: Sequence[str],
    latencia_ms: int,
) -> ChoiceDecision:
    """Interpreta uma única resposta Choice com conjunto exato de opções."""

    try:
        options = _parse_options(allowed_options)
        if type(question_id) is not str or not question_id:
            raise ValueError("pergunta inválida")
        if not isinstance(body, dict) or not set(body) <= {"answers", "model", "usage"}:
            raise ValueError("corpo inválido")
        if "model" in body and type(body["model"]) is not str:
            raise ValueError("modelo inválido")
        if "usage" in body and not isinstance(body["usage"], dict):
            raise ValueError("usage inválido")
        answers = body.get("answers")
        if not isinstance(answers, dict) or set(answers) != {question_id}:
            raise ValueError("answers inválidas")
        answer = answers[question_id]
        if not isinstance(answer, dict) or set(answer) != {
            "type",
            "choice",
            "confidence",
            "probabilities",
        }:
            raise ValueError("answer inválida")
        if answer["type"] != "choice":
            raise ValueError("tipo inválido")
        choice = answer["choice"]
        if type(choice) is not str or choice not in options:
            raise ValueError("choice inválida")
        confidence = _strict_probability(answer["confidence"])
        raw_probabilities = answer["probabilities"]
        if not isinstance(raw_probabilities, dict) or set(raw_probabilities) != set(options):
            raise ValueError("probabilities inválidas")
        probabilities = {
            option: _strict_probability(raw_probabilities[option]) for option in options
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return _failure(RoutingError.SCHEMA_INVALIDO, latencia_ms=latencia_ms)
    return ChoiceDecision(
        choice=choice,
        probabilities=MappingProxyType(probabilities),
        confidence=confidence,
        erro=None,
        latencia_ms=max(0, int(latencia_ms)),
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("chave JSON duplicada")
        result[key] = value
    return result


def parse_choice_json(
    raw: bytes | str,
    *,
    question_id: str,
    allowed_options: Sequence[str],
    latencia_ms: int,
) -> ChoiceDecision:
    """Decodifica JSON sem aceitar chave repetida antes de formar dicionário."""

    try:
        body = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except (TypeError, UnicodeDecodeError, ValueError, RecursionError):
        return _failure(RoutingError.SCHEMA_INVALIDO, latencia_ms=latencia_ms)
    return parse_choice_response(
        body,
        question_id=question_id,
        allowed_options=allowed_options,
        latencia_ms=latencia_ms,
    )


def s3_routing_egress_allowed(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    *,
    tier_a_release_id: str | None,
    s3_release_id: str | None,
) -> bool:
    """Exige os gates ativos de Tier A e uma aprovação S3 independente."""

    return bool(
        S3_ROUTING_APPROVED_RELEASE_ID is not None
        and s3_release_id == S3_ROUTING_APPROVED_RELEASE_ID
        and tier_a_egress_allowed(
            effective,
            igreja_id,
            approved_release_id=tier_a_release_id,
        )
    )


def _request_budget(
    effective: EffectiveTriageSettings,
    timeout_seconds: float | None,
) -> float | None:
    configured_value = effective.settings.typesafe_timeout_seconds
    if type(timeout_seconds) not in (int, float) or type(configured_value) not in (int, float):
        return None
    try:
        configured = float(configured_value)
        remaining = float(timeout_seconds)
    except (OverflowError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in (configured, remaining)):
        return None
    budget = min(configured, remaining, S3_ROUTING_HTTP_MAX_SECONDS)
    return budget if math.isfinite(budget) and budget > 0 else None


async def _run_choice(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    *,
    payload: dict[str, Any],
    question_id: str,
    allowed_options: Sequence[str],
    tier_a_release_id: str | None,
    s3_release_id: str | None,
    timeout_seconds: float | None,
    transport: httpx.AsyncBaseTransport | None,
) -> ChoiceDecision:
    try:
        gate_allowed = s3_routing_egress_allowed(
            effective,
            igreja_id,
            tier_a_release_id=tier_a_release_id,
            s3_release_id=s3_release_id,
        )
    except Exception:
        gate_allowed = False
    if not gate_allowed:
        log_suppressed("JEV", "s3_choice")
        return _failure(RoutingError.GATE_FECHADO)
    budget = _request_budget(effective, timeout_seconds)
    if budget is None:
        return _failure(RoutingError.ORCAMENTO_ESGOTADO)
    started = time.monotonic()
    try:
        async with asyncio.timeout(budget):
            async with httpx.AsyncClient(
                timeout=budget,
                transport=transport,
            ) as client:
                async with client.stream(
                    "POST",
                    effective.settings.typesafe_api_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {effective.settings.typesafe_api_key}",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    if response.is_stream_consumed:
                        # MockTransport também pode devolver Response já materializada.
                        if len(response.content) > MAX_ROUTING_RESPONSE_BYTES:
                            return _failure(
                                RoutingError.SCHEMA_INVALIDO,
                                latencia_ms=int((time.monotonic() - started) * 1000),
                            )
                        body.extend(response.content)
                    else:
                        async for chunk in response.aiter_raw():
                            if len(chunk) > MAX_ROUTING_RESPONSE_BYTES - len(body):
                                return _failure(
                                    RoutingError.SCHEMA_INVALIDO,
                                    latencia_ms=int((time.monotonic() - started) * 1000),
                                )
                            body.extend(chunk)
            decision = parse_choice_json(
                bytes(body),
                question_id=question_id,
                allowed_options=allowed_options,
                latencia_ms=0,
            )
            elapsed = time.monotonic() - started
            if elapsed >= budget:
                return _failure(RoutingError.TIMEOUT, latencia_ms=int(elapsed * 1000))
            return replace(decision, latencia_ms=int(elapsed * 1000))
    except TimeoutError:
        return _failure(
            RoutingError.TIMEOUT,
            latencia_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.TimeoutException:
        return _failure(
            RoutingError.TIMEOUT,
            latencia_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError:
        return _failure(
            RoutingError.HTTP,
            latencia_ms=int((time.monotonic() - started) * 1000),
        )
async def run_choice_b(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    texto: str,
    *,
    tier_a_release_id: str | None,
    s3_release_id: str | None,
    timeout_seconds: float | None,
    transport: httpx.AsyncBaseTransport | None = None,
    allowed_routes: Sequence[str] | None = None,
) -> ChoiceDecision:
    """Executa B sem aplicar rota, limiar ou autorização no transporte."""

    try:
        payload = build_choice_b_request(
            texto, model=effective.settings.typesafe_model, allowed_routes=allowed_routes,
        )
        routes = ROUTE_CHOICES if allowed_routes is None else tuple(allowed_routes)
    except OverflowError:
        return _failure(RoutingError.LIMITE_ENTRADA)
    except (TypeError, ValueError):
        return _failure(RoutingError.SCHEMA_INVALIDO)
    decision = await _run_choice(
        effective,
        igreja_id,
        payload=payload,
        question_id="rota_s3",
        allowed_options=routes,
        tier_a_release_id=tier_a_release_id,
        s3_release_id=s3_release_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    if decision.choice is None:
        return decision
    return replace(
        decision,
        choice=(RouteChoice(decision.choice) if decision.choice in ROUTE_CHOICES else decision.choice),
    )


async def run_choice_c(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    texto: str,
    *,
    route: RouteChoice,
    allowed_tools: Sequence[str],
    tier_a_release_id: str | None,
    s3_release_id: str | None,
    timeout_seconds: float | None,
    transport: httpx.AsyncBaseTransport | None = None,
    include_handoff: bool = False,
) -> ChoiceDecision:
    """Executa C com catálogo já limitado pelo chamador autorizado."""

    try:
        tools = _require_catalog(allowed_tools)
        payload = build_choice_c_request(
            texto,
            route=route,
            allowed_tools=tools,
            model=effective.settings.typesafe_model,
            include_handoff=include_handoff,
        )
    except OverflowError:
        return _failure(RoutingError.LIMITE_ENTRADA)
    except (TypeError, ValueError):
        return _failure(RoutingError.SCHEMA_INVALIDO)
    return await _run_choice(
        effective,
        igreja_id,
        payload=payload,
        question_id="ferramenta_s3",
        allowed_options=(*tools, _NONE_OPTION, *(("handoff",) if include_handoff else ())),
        tier_a_release_id=tier_a_release_id,
        s3_release_id=s3_release_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


async def run_choice_d(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    texto: str,
    *,
    route: RouteChoice,
    tool: str,
    candidate_summaries: Mapping[str, str],
    tier_a_release_id: str | None,
    s3_release_id: str | None,
    timeout_seconds: float | None,
    transport: httpx.AsyncBaseTransport | None = None,
    include_handoff: bool = False,
) -> ChoiceDecision:
    """Executa D com handles efêmeros que não carregam identidade real."""

    try:
        candidates = _require_candidate_summaries(candidate_summaries)
        payload = build_choice_d_request(
            texto,
            route=route,
            tool=tool,
            candidate_summaries=candidates,
            model=effective.settings.typesafe_model,
            include_handoff=include_handoff,
        )
    except OverflowError:
        return _failure(RoutingError.LIMITE_ENTRADA)
    except (TypeError, ValueError):
        return _failure(RoutingError.SCHEMA_INVALIDO)
    return await _run_choice(
        effective,
        igreja_id,
        payload=payload,
        question_id="candidato_s3",
        allowed_options=(*candidates, "nenhum", *(("handoff",) if include_handoff else ())),
        tier_a_release_id=tier_a_release_id,
        s3_release_id=s3_release_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )

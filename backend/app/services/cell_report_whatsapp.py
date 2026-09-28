"""Narrow V1a WhatsApp report gates and aggregate-only projections.

This module deliberately starts with deterministic boundaries shared by the
future runtime and reminder worker.  It does not call a provider, mint an
operational-consent permit, or treat ``Pessoa.consentimento`` as authority.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    CellReportAiDailyBudget,
    CellReportAiReservation,
    CellReportDraft,
    CelulaReuniao,
)
from app.db.rls_observability import require_tenant_scope
from app.domain.cell_report_v1a import CellReportV1aError
from app.domain.cell_report_workflow import (
    CellReportCandidate,
    CellReportWorkflowError,
    build_cell_report_candidate,
)
from app.services.whatsapp_privilege import privilege_enabled_from_environment


# A listed tenant remains inert until a reviewed V1a release is explicitly
# identified in code.  The default is intentionally closed.
CELL_REPORT_APPROVED_RELEASE_ID: str | None = None
CELL_REPORT_COST_VERSION = "v1"
CELL_REPORT_MAX_EXTRACTION_CALLS = 4
CELL_REPORT_MAX_INPUT_TOKENS = 2_000
CELL_REPORT_MAX_OUTPUT_TOKENS = 400
CELL_REPORT_REPORT_LIMIT_MICROUSD = 100_000
CELL_REPORT_DAILY_LIMIT_MICROUSD = 2_000_000

_SAFE_NUMBER_WORDS = (
    "zero",
    "um",
    "uma",
    "dois",
    "duas",
    "tres",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "catorze",
    "quatorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
    "cem",
)
_SAFE_NUMBER_WORD = "(?:" + "|".join(_SAFE_NUMBER_WORDS) + ")"
_SAFE_NUMBER_TOKEN = (
    r"(?:[0-9]{1,7}|"
    + _SAFE_NUMBER_WORD
    + r"(?:\s+e\s+"
    + _SAFE_NUMBER_WORD
    + r"){0,2})(?![a-z0-9.,]|\s+(?:mil(?:hoes?)?|centavos?|e)\b)"
)
_LABELED_AGGREGATE = re.compile(
    r"(?<![a-z0-9])"
    r"(?P<label>presentes?|visitantes?|decis(?:ao|oes?)|ofertas?)"
    r"(?![a-z0-9])"
    r"\s*(?:[:=]\s*|\s+)"
    r"(?:r\$\s*)?"
    rf"(?P<value>{_SAFE_NUMBER_TOKEN})"
    r"(?P<reais>\s+reais?)?"
)
_PROJECTION_LABELS = {
    "presente": "presentes",
    "presentes": "presentes",
    "visitante": "visitantes",
    "visitantes": "visitantes",
    "decisao": "decisoes",
    "decisoes": "decisoes",
    "oferta": "oferta",
    "ofertas": "oferta",
}


class CellReportWhatsappError(ValueError):
    """Static rejection at the V1a persistence and cost boundary."""


@dataclass(frozen=True, slots=True)
class LgpdConsentRecord:
    """Minimal persisted consent projection, deliberately without free text."""

    termo_versao: str | None
    aceite_em: dt.datetime | None
    record_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class V1aExtractionBudgetReservation:
    """One committed-before-HTTP upper-bound extraction reservation."""

    reservation_id: uuid.UUID
    call_number: int
    estimated_microusd: int
    budget_day: dt.date


@dataclass(frozen=True, slots=True)
class V1aExtractionBudgetSettlement:
    """Idempotent post-call accounting without prompt or provider payloads."""

    reservation_id: uuid.UUID
    actual_microusd: int
    settled: bool


def _utc(value: object) -> dt.datetime | None:
    if type(value) is not dt.datetime or value.tzinfo is None:
        return None
    try:
        return value.astimezone(dt.timezone.utc)
    except (OverflowError, ValueError):
        return None


def _approved_release() -> bool:
    return (
        type(CELL_REPORT_APPROVED_RELEASE_ID) is str
        and bool(CELL_REPORT_APPROVED_RELEASE_ID.strip())
    )


def cell_report_enabled_from_environment(igreja_id: object) -> bool:
    """Require both reviewed V1a and already-closed S3 activation gates."""

    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    if not _approved_release() or not privilege_enabled_from_environment(igreja_id):
        return False
    raw = os.environ.get("CELL_REPORT_ENABLED_IGREJA_IDS", "")
    if type(raw) is not str or not raw.strip():
        return False
    pieces = raw.split(",")
    if any(not piece.strip() for piece in pieces):
        return False
    try:
        allowlist = tuple(uuid.UUID(piece.strip()) for piece in pieces)
    except (AttributeError, ValueError):
        return False
    return len(allowlist) == len(set(allowlist)) and igreja_id in allowlist


def current_v1a_lgpd_acceptance(
    records: object,
    *,
    current_term: object,
    now: object,
) -> str | None:
    """Return the sole current term only when the terminal ledger event is safe.

    A timestamp tie that contains different versions, a future timestamp, a
    missing timestamp, an opt-out/reopt-in marker, or any malformed terminal
    record fails closed.  Older consent cannot revive after a later withdrawal.
    """

    if type(current_term) is not str or not current_term:
        return None
    current_now = _utc(now)
    if current_now is None or type(records) not in (tuple, list) or not records:
        return None
    normalized: list[LgpdConsentRecord] = []
    for record in records:
        if type(record) is not LgpdConsentRecord:
            return None
        if type(record.record_id) is not uuid.UUID or record.record_id.int == 0:
            return None
        if type(record.termo_versao) is not str or not record.termo_versao:
            return None
        accepted_at = _utc(record.aceite_em)
        if accepted_at is None:
            return None
        normalized.append(
            LgpdConsentRecord(record.termo_versao, accepted_at, record.record_id)
        )
    latest_at = max(record.aceite_em for record in normalized if record.aceite_em is not None)
    if latest_at > current_now:
        return None
    terminal = tuple(record for record in normalized if record.aceite_em == latest_at)
    if len(terminal) != 1:
        return None
    versions = {record.termo_versao for record in terminal}
    if len(versions) != 1:
        return None
    version = next(iter(versions))
    if version.startswith(("optout:", "reoptin:")) or version != current_term:
        return None
    return version


def v1a_extraction_projection(candidate: object) -> dict[str, int | None]:
    """Build the only data projection permitted to any V1a extractor.

    The caller may request deterministic clarification from this projection.
    It never accepts an inbound text string, names, roster entries, addresses,
    observations, UUIDs, or conversation history.
    """

    if type(candidate) is not CellReportCandidate or candidate.observacoes is not None:
        raise CellReportV1aError("relatório de célula inválido")
    oferta = candidate.oferta
    if oferta is None:
        cents = None
    elif type(oferta) is str and oferta.count(".") == 1:
        reais, fractional = oferta.split(".", 1)
        if not reais.isascii() or not reais.isdigit() or len(fractional) != 2:
            raise CellReportV1aError("relatório de célula inválido")
        cents = int(reais) * 100 + int(fractional)
    else:
        raise CellReportV1aError("relatório de célula inválido")
    for value in (candidate.presentes, candidate.visitantes, candidate.decisoes):
        if value is not None and (type(value) is not int or value < 0):
            raise CellReportV1aError("relatório de célula inválido")
    return {
        "presentes": candidate.presentes,
        "visitantes": candidate.visitantes,
        "decisoes": candidate.decisoes,
        "oferta_centavos": cents,
    }


def canonical_v1a_draft_payload(candidate: object) -> dict[str, int | None]:
    """Return the sole JSONB shape retained for a V1a draft.

    This is intentionally the same four-field projection available to an
    optional extractor.  It excludes raw inbound text, observations, names,
    meeting metadata and any server identity.
    """

    try:
        return v1a_extraction_projection(candidate)
    except CellReportV1aError as exc:
        raise CellReportWhatsappError("rascunho de relatório inválido") from exc


def rehydrate_v1a_draft_candidate(payload: object) -> CellReportCandidate:
    """Rebuild one typed candidate from the closed aggregate JSONB shape."""

    if type(payload) is not dict or set(payload) != {
        "presentes",
        "visitantes",
        "decisoes",
        "oferta_centavos",
    }:
        raise CellReportWhatsappError("rascunho de relatório inválido")
    counts: dict[str, int | None] = {}
    for field in ("presentes", "visitantes", "decisoes"):
        value = payload[field]
        if value is not None and (type(value) is not int or value < 0):
            raise CellReportWhatsappError("rascunho de relatório inválido")
        counts[field] = value
    cents = payload["oferta_centavos"]
    if cents is not None and (type(cents) is not int or cents < 0):
        raise CellReportWhatsappError("rascunho de relatório inválido")
    offer = None if cents is None else f"{cents // 100}.{cents % 100:02d}"
    try:
        return build_cell_report_candidate(
            presentes=counts["presentes"],
            visitantes=counts["visitantes"],
            decisoes=counts["decisoes"],
            oferta=offer,
            observacoes=None,
        )
    except (CellReportWorkflowError, TypeError, ValueError) as exc:
        raise CellReportWhatsappError("rascunho de relatório inválido") from exc


def estimate_v1a_extraction_microusd(
    model: object,
    estimate_cost: Callable[[str, int, int], object],
) -> int:
    """Return a ceiling reservation for one bounded extraction call.

    The estimator receives the reviewed input/output bounds, never observed
    prompt text.  Unknown, non-finite, non-positive or report-cap-exceeding
    prices deny the call before any provider boundary.
    """

    if type(model) is not str or not model or not callable(estimate_cost):
        raise CellReportWhatsappError("custo de extração indisponível")
    try:
        estimated_usd = Decimal(str(
            estimate_cost(
                model,
                CELL_REPORT_MAX_INPUT_TOKENS,
                CELL_REPORT_MAX_OUTPUT_TOKENS,
            )
        ))
        if not estimated_usd.is_finite() or estimated_usd <= 0:
            raise InvalidOperation
        micro_usd = int(
            (estimated_usd * Decimal(1_000_000)).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError, OverflowError):
        raise CellReportWhatsappError("custo de extração indisponível") from None
    if micro_usd <= 0 or micro_usd > CELL_REPORT_REPORT_LIMIT_MICROUSD:
        raise CellReportWhatsappError("custo de extração indisponível")
    return micro_usd


def actual_v1a_extraction_microusd(
    usage: object,
    estimate_cost: Callable[[str, int, int], object],
) -> int:
    """Recompute one billable extraction from bounded provider usage.

    Missing, malformed or non-finite provider accounting is not treated as a
    zero-cost call.  The caller must leave its durable reservation held when
    this boundary rejects the result.
    """

    if not callable(estimate_cost):
        raise CellReportWhatsappError("liquidação de custo indisponível")
    model = getattr(usage, "modelo", None)
    tokens_in = getattr(usage, "tokens_in", None)
    tokens_out = getattr(usage, "tokens_out", None)
    observed_cost = getattr(usage, "custo", None)
    if (
        type(model) is not str
        or not model
        or type(tokens_in) is not int
        or type(tokens_out) is not int
        or not 0 <= tokens_in <= CELL_REPORT_MAX_INPUT_TOKENS
        or not 0 <= tokens_out <= CELL_REPORT_MAX_OUTPUT_TOKENS
        or type(observed_cost) not in {int, float, Decimal}
    ):
        raise CellReportWhatsappError("liquidação de custo indisponível")
    try:
        reported = Decimal(str(observed_cost))
        estimated = Decimal(str(estimate_cost(model, tokens_in, tokens_out)))
        if (
            not reported.is_finite()
            or reported < 0
            or not estimated.is_finite()
            or estimated < 0
        ):
            raise InvalidOperation
        actual = int(
            (estimated * Decimal(1_000_000)).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError, OverflowError):
        raise CellReportWhatsappError("liquidação de custo indisponível") from None
    if actual < 0:
        raise CellReportWhatsappError("liquidação de custo indisponível")
    return actual


def _budget_now(value: object) -> dt.datetime:
    current = _utc(value) if value is not None else dt.datetime.now(dt.timezone.utc)
    if current is None:
        raise CellReportWhatsappError("horário de custo indisponível")
    return current


def _budget_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise CellReportWhatsappError("reserva de custo inválida")
    return value


def _locked_daily_budget(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    budget_day: dt.date,
    now: dt.datetime,
) -> CellReportAiDailyBudget:
    """Get one per-tenant daily row under a durable row lock, creating once."""

    budget = session.execute(
        select(CellReportAiDailyBudget)
        .where(
            CellReportAiDailyBudget.igreja_id == igreja_id,
            CellReportAiDailyBudget.budget_day == budget_day,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if budget is not None:
        return budget
    try:
        with session.begin_nested():
            budget = CellReportAiDailyBudget(
                igreja_id=igreja_id,
                budget_day=budget_day,
                cost_version=CELL_REPORT_COST_VERSION,
                reserved_microusd=0,
                settled_microusd=0,
                created_at=now,
                updated_at=now,
            )
            session.add(budget)
            session.flush()
    except IntegrityError:
        budget = session.execute(
            select(CellReportAiDailyBudget)
            .where(
                CellReportAiDailyBudget.igreja_id == igreja_id,
                CellReportAiDailyBudget.budget_day == budget_day,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if budget is None:
            raise
    if budget is None:
        raise CellReportWhatsappError("reserva de custo indisponível")
    return budget


def reserve_v1a_extraction_budget(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    draft_id: uuid.UUID,
    model: object,
    estimate_cost: Callable[[str, int, int], object],
    now: dt.datetime | None = None,
) -> V1aExtractionBudgetReservation:
    """Reserve one bounded V1a extraction without committing or calling HTTP.

    The reservation holds the upper cost bound through provider failure or
    process loss. The official meeting serializes its four-call lifetime even
    when a cancelled draft is replaced; the daily row serializes all reports
    in the tenant.
    """

    tenant = _budget_uuid(igreja_id)
    draft_key = _budget_uuid(draft_id)
    current = _budget_now(now)
    if not cell_report_enabled_from_environment(tenant):
        raise CellReportWhatsappError("reserva de custo indisponível")
    require_tenant_scope(
        session,
        expected_igreja_id=tenant,
        source="cell_report_v1a_budget_reserve",
    )
    estimate = estimate_v1a_extraction_microusd(model, estimate_cost)
    meeting_id = session.execute(
        select(CellReportDraft.reuniao_id).where(
            CellReportDraft.igreja_id == tenant,
            CellReportDraft.id == draft_key,
        )
    ).scalar_one_or_none()
    if type(meeting_id) is not uuid.UUID or meeting_id.int == 0:
        raise CellReportWhatsappError("reserva de custo indisponível")
    meeting = session.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == tenant,
            CelulaReuniao.id == meeting_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if meeting is None:
        raise CellReportWhatsappError("reserva de custo indisponível")
    draft = session.execute(
        select(CellReportDraft)
        .where(
            CellReportDraft.igreja_id == tenant,
            CellReportDraft.id == draft_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        draft is None
        or draft.reuniao_id != meeting_id
        or draft.state != "coletando"
        or draft.candidate_json is None
        or _utc(draft.expires_at) is None
        or _utc(draft.expires_at) <= current
    ):
        raise CellReportWhatsappError("reserva de custo indisponível")
    existing = tuple(
        session.execute(
            select(CellReportAiReservation)
            .join(
                CellReportDraft,
                (
                    CellReportDraft.igreja_id
                    == CellReportAiReservation.igreja_id
                )
                & (CellReportDraft.id == CellReportAiReservation.draft_id),
            )
            .where(
                CellReportAiReservation.igreja_id == tenant,
                CellReportDraft.reuniao_id == meeting_id,
            )
            .order_by(CellReportAiReservation.call_number.asc())
            .with_for_update(of=CellReportAiReservation)
            .execution_options(populate_existing=True)
        ).scalars()
    )
    call_number = max((row.call_number for row in existing), default=0) + 1
    report_reserved = sum(row.estimated_microusd for row in existing)
    if (
        call_number > CELL_REPORT_MAX_EXTRACTION_CALLS
        or report_reserved + estimate > CELL_REPORT_REPORT_LIMIT_MICROUSD
    ):
        raise CellReportWhatsappError("reserva de custo indisponível")
    budget_day = current.date()
    budget = _locked_daily_budget(
        session,
        igreja_id=tenant,
        budget_day=budget_day,
        now=current,
    )
    if (
        budget.cost_version != CELL_REPORT_COST_VERSION
        or type(budget.reserved_microusd) is not int
        or type(budget.settled_microusd) is not int
        or budget.reserved_microusd < 0
        or budget.settled_microusd < 0
        or budget.reserved_microusd + budget.settled_microusd + estimate
        > CELL_REPORT_DAILY_LIMIT_MICROUSD
    ):
        raise CellReportWhatsappError("reserva de custo indisponível")
    reservation = CellReportAiReservation(
        igreja_id=tenant,
        draft_id=draft_key,
        budget_id=budget.id,
        call_number=call_number,
        budget_day=budget_day,
        cost_version=CELL_REPORT_COST_VERSION,
        state="reservada",
        estimated_microusd=estimate,
        actual_microusd=None,
        created_at=current,
        settled_at=None,
    )
    session.add(reservation)
    budget.reserved_microusd += estimate
    budget.updated_at = current
    session.flush()
    reservation_id = getattr(reservation, "id", None)
    if type(reservation_id) is not uuid.UUID or reservation_id.int == 0:
        raise CellReportWhatsappError("reserva de custo indisponível")
    return V1aExtractionBudgetReservation(
        reservation_id=reservation_id,
        call_number=call_number,
        estimated_microusd=estimate,
        budget_day=budget_day,
    )


def settle_v1a_extraction_budget(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    reservation_id: uuid.UUID,
    actual_microusd: int,
    now: dt.datetime | None = None,
) -> V1aExtractionBudgetSettlement:
    """Settle a completed provider call exactly once in the caller transaction."""

    tenant = _budget_uuid(igreja_id)
    reservation_key = _budget_uuid(reservation_id)
    if type(actual_microusd) is not int or actual_microusd < 0:
        raise CellReportWhatsappError("liquidação de custo indisponível")
    current = _budget_now(now)
    require_tenant_scope(
        session,
        expected_igreja_id=tenant,
        source="cell_report_v1a_budget_settle",
    )
    reservation = session.execute(
        select(CellReportAiReservation)
        .where(
            CellReportAiReservation.igreja_id == tenant,
            CellReportAiReservation.id == reservation_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if reservation is None:
        raise CellReportWhatsappError("liquidação de custo indisponível")
    budget = session.execute(
        select(CellReportAiDailyBudget)
        .where(
            CellReportAiDailyBudget.igreja_id == tenant,
            CellReportAiDailyBudget.id == reservation.budget_id,
            CellReportAiDailyBudget.budget_day == reservation.budget_day,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        budget is None
        or budget.cost_version != CELL_REPORT_COST_VERSION
        or reservation.cost_version != CELL_REPORT_COST_VERSION
        or type(reservation.estimated_microusd) is not int
        or reservation.estimated_microusd <= 0
        or actual_microusd > reservation.estimated_microusd
    ):
        raise CellReportWhatsappError("liquidação de custo indisponível")
    if reservation.state == "liquidada":
        if reservation.actual_microusd != actual_microusd:
            raise CellReportWhatsappError("liquidação de custo indisponível")
        return V1aExtractionBudgetSettlement(
            reservation_id=reservation_key,
            actual_microusd=actual_microusd,
            settled=False,
        )
    if (
        reservation.state != "reservada"
        or type(budget.reserved_microusd) is not int
        or type(budget.settled_microusd) is not int
        or budget.reserved_microusd < reservation.estimated_microusd
        or budget.settled_microusd < 0
    ):
        raise CellReportWhatsappError("liquidação de custo indisponível")
    reservation.state = "liquidada"
    reservation.actual_microusd = actual_microusd
    reservation.settled_at = current
    budget.reserved_microusd -= reservation.estimated_microusd
    budget.settled_microusd += actual_microusd
    budget.updated_at = current
    session.flush()
    return V1aExtractionBudgetSettlement(
        reservation_id=reservation_key,
        actual_microusd=actual_microusd,
        settled=True,
    )


def _normalized_whitelist_source(value: object) -> str:
    if type(value) is not str:
        raise CellReportWhatsappError("entrada de extração inválida")
    try:
        normalized = "".join(
            char
            for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        )
        if len(normalized.encode("utf-8", "strict")) > 4_000:
            raise ValueError
    except (UnicodeError, ValueError):
        raise CellReportWhatsappError("entrada de extração inválida") from None
    return normalized


def v1a_whitelisted_extraction_projection(text: object) -> dict[str, str]:
    """Reduce raw text to label-plus-number facts before an optional extractor.

    Each retained value is a fixed number token immediately adjacent to one of
    four approved aggregate labels.  Names, addresses, comments, UUIDs and
    surrounding prose are never part of the returned mapping.
    """

    normalized = _normalized_whitelist_source(text)
    result: dict[str, str] = {}
    for match in _LABELED_AGGREGATE.finditer(normalized):
        field = _PROJECTION_LABELS.get(match.group("label"))
        if field is None:
            continue
        value = match.group("value")
        if field == "oferta" and match.group("reais") is not None:
            value = f"{value} reais"
        prior = result.get(field)
        if prior is not None and prior != value:
            return {}
        result[field] = value
    return result


def complete_v1a_candidate_from_whitelisted_projection(
    text: object,
    current: object,
    *,
    extract: Callable[[dict[str, str]], object],
    allow_explicit_corrections: bool = False,
) -> CellReportCandidate:
    """Fill missing aggregates or one explicit labelled correction.

    The caller is responsible for a previously committed cost reservation and
    for supplying an extractor with a closed JSON schema.  This function never
    passes the original text to that callback. A persisted complete candidate
    stays unchanged unless its caller explicitly opts into this correction
    path; then only labels carried by the closed projection may change.
    """

    if (
        type(current) is not CellReportCandidate
        or current.observacoes is not None
        or not callable(extract)
        or type(allow_explicit_corrections) is not bool
    ):
        raise CellReportWhatsappError("extração de relatório inválida")
    if current.is_complete and not allow_explicit_corrections:
        return current
    projection = v1a_whitelisted_extraction_projection(text)
    if not projection:
        return current
    return complete_v1a_candidate_from_projection(
        current,
        projection=projection,
        extracted=extract(dict(projection)),
        allow_explicit_corrections=allow_explicit_corrections,
    )


def complete_v1a_candidate_from_projection(
    current: object,
    *,
    projection: object,
    extracted: object,
    allow_explicit_corrections: bool = False,
) -> CellReportCandidate:
    """Apply one already-redacted, closed extractor result to a draft.

    This is the post-HTTP counterpart to
    :func:`complete_v1a_candidate_from_whitelisted_projection`: no raw text
    reaches this boundary, so the caller can revalidate and persist after the
    provider session has ended.
    """

    if (
        type(current) is not CellReportCandidate
        or current.observacoes is not None
        or type(projection) is not dict
        or not projection
        or set(projection) - {"presentes", "visitantes", "decisoes", "oferta"}
        or any(
            type(value) is not str
            or not value
            or len(value) > 96
            or re.fullmatch(r"[a-z0-9 ]+", value) is None
            for value in projection.values()
        )
        or type(allow_explicit_corrections) is not bool
    ):
        raise CellReportWhatsappError("extração de relatório inválida")
    fallback = rehydrate_v1a_draft_candidate(extracted)
    values = {
        "presentes": current.presentes,
        "visitantes": current.visitantes,
        "decisoes": current.decisoes,
        "oferta": current.oferta,
    }
    fallback_values = {
        "presentes": fallback.presentes,
        "visitantes": fallback.visitantes,
        "decisoes": fallback.decisoes,
        "oferta": fallback.oferta,
    }
    for field, value in values.items():
        fallback_value = fallback_values[field]
        if fallback_value is not None and field not in projection:
            raise CellReportWhatsappError("extração de relatório inválida")
        if value is not None and fallback_value is not None:
            if not allow_explicit_corrections or field not in projection:
                raise CellReportWhatsappError("extração de relatório inválida")
        if (
            value is not None
            and field in projection
            and fallback_value is None
            and allow_explicit_corrections
        ):
            raise CellReportWhatsappError("extração de relatório inválida")
    try:
        return build_cell_report_candidate(
            presentes=(
                fallback.presentes
                if fallback.presentes is not None and "presentes" in projection
                else fallback.presentes
                if current.presentes is None
                else current.presentes
            ),
            visitantes=(
                fallback.visitantes
                if fallback.visitantes is not None and "visitantes" in projection
                else fallback.visitantes
                if current.visitantes is None
                else current.visitantes
            ),
            decisoes=(
                fallback.decisoes
                if fallback.decisoes is not None and "decisoes" in projection
                else fallback.decisoes
                if current.decisoes is None
                else current.decisoes
            ),
            oferta=(
                fallback.oferta
                if fallback.oferta is not None and "oferta" in projection
                else fallback.oferta
                if current.oferta is None
                else current.oferta
            ),
            observacoes=None,
        )
    except (CellReportWorkflowError, TypeError, ValueError) as exc:
        raise CellReportWhatsappError("extração de relatório inválida") from exc


__all__ = [
    "CELL_REPORT_APPROVED_RELEASE_ID",
    "CELL_REPORT_COST_VERSION",
    "CELL_REPORT_DAILY_LIMIT_MICROUSD",
    "CELL_REPORT_MAX_EXTRACTION_CALLS",
    "CELL_REPORT_MAX_INPUT_TOKENS",
    "CELL_REPORT_MAX_OUTPUT_TOKENS",
    "CELL_REPORT_REPORT_LIMIT_MICROUSD",
    "actual_v1a_extraction_microusd",
    "CellReportWhatsappError",
    "LgpdConsentRecord",
    "V1aExtractionBudgetReservation",
    "V1aExtractionBudgetSettlement",
    "canonical_v1a_draft_payload",
    "cell_report_enabled_from_environment",
    "complete_v1a_candidate_from_projection",
    "complete_v1a_candidate_from_whitelisted_projection",
    "current_v1a_lgpd_acceptance",
    "estimate_v1a_extraction_microusd",
    "rehydrate_v1a_draft_candidate",
    "reserve_v1a_extraction_budget",
    "settle_v1a_extraction_budget",
    "v1a_whitelisted_extraction_projection",
    "v1a_extraction_projection",
]

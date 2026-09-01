"""Closed JSONB contract for one durable pending cell-report proposal.

The envelope persists the pure :class:`CellReportWorkflow`, an immutable UTC
expiry, bounded replay receipts and domain-separated opaque bindings.  Raw tenant,
meeting, conversation and actor UUIDs are never projected.  The candidate may
contain private report observations, so the object and its errors deliberately
use redacted representations and callers must not log the JSON payload.

This module performs no I/O and does not authenticate any binding or effect
identifier.  A trusted application service must derive expected bindings from
its already authenticated context and compare them before every transition.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.domain.cell_report_snapshot import (
    CellReportSnapshotValidationError,
    build_cell_report_snapshot_v2,
)
from app.domain.cell_report_workflow import (
    CellReportWorkflow,
    CellReportWorkflowState,
    cell_report_workflow_payload,
    rehydrate_cell_report_workflow,
    validate_cell_report_workflow,
)


CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1: Final = (
    "cell-report-pending-proposal/v1"
)
CELL_REPORT_PROPOSAL_BINDING_VERSION: Final = "v1"
CELL_REPORT_PROPOSAL_EFFECT_ID_PREFIX: Final = "agent_effect_v1_"
CELL_REPORT_PROPOSAL_PAYLOAD_DIGEST_PREFIX: Final = "agent_payload_v1_"
CELL_REPORT_PROPOSAL_BASE_DIGEST_PREFIX: Final = "cell_report_base_v1_"
MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS: Final = 32

_OPEN_PENDING_STATES: Final = frozenset(
    {
        CellReportWorkflowState.EMPTY,
        CellReportWorkflowState.COLLECTING,
        CellReportWorkflowState.AWAITING_CONFIRMATION,
    }
)
_EFFECT_ID_RE: Final = re.compile(
    rf"{re.escape(CELL_REPORT_PROPOSAL_EFFECT_ID_PREFIX)}[0-9a-f]{{64}}\Z"
)
_PAYLOAD_DIGEST_RE: Final = re.compile(
    rf"{re.escape(CELL_REPORT_PROPOSAL_PAYLOAD_DIGEST_PREFIX)}[0-9a-f]{{64}}\Z"
)
_BASE_DIGEST_RE: Final = re.compile(
    rf"{re.escape(CELL_REPORT_PROPOSAL_BASE_DIGEST_PREFIX)}[0-9a-f]{{64}}\Z"
)
_CANONICAL_UTC_RE: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_ENVELOPE_KEYS: Final = frozenset(
    {
        "schema",
        "bindings",
        "expires_at",
        "operation_receipts",
        "base_state_digest",
        "workflow",
    }
)
_BINDING_KEYS: Final = frozenset(
    {"tenant", "meeting", "conversation", "actor"}
)
_OPERATION_RECEIPT_KEYS: Final = frozenset({"effect_id", "payload_digest"})
_BINDING_SPECS: Final = {
    "tenant": (
        "cell_report_tenant_v1_",
        b"pastorai.cell-report.pending.binding.tenant",
    ),
    "meeting": (
        "cell_report_meeting_v1_",
        b"pastorai.cell-report.pending.binding.meeting",
    ),
    "conversation": (
        "cell_report_conversation_v1_",
        b"pastorai.cell-report.pending.binding.conversation",
    ),
    "actor": (
        "cell_report_actor_v1_",
        b"pastorai.cell-report.pending.binding.actor",
    ),
}


class CellReportPendingProposalErrorCode(str, Enum):
    """Static fail-closed reasons that do not echo private material."""

    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    INVALID_BINDING = "INVALID_BINDING"
    INVALID_EXPIRY = "INVALID_EXPIRY"
    INVALID_EFFECT_ID = "INVALID_EFFECT_ID"
    INVALID_OPERATION_RECEIPTS = "INVALID_OPERATION_RECEIPTS"
    INVALID_BASE_STATE = "INVALID_BASE_STATE"
    INVALID_WORKFLOW = "INVALID_WORKFLOW"
    INVALID_PENDING_STATE = "INVALID_PENDING_STATE"


class CellReportPendingProposalError(ValueError):
    """Sanitized proposal-contract rejection."""

    def __init__(self, code: CellReportPendingProposalErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report pending proposal rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _reject(code: CellReportPendingProposalErrorCode) -> None:
    raise CellReportPendingProposalError(code)


def _binary_frame(*parts: bytes) -> bytes:
    framed = bytearray(len(parts).to_bytes(4, "big"))
    for part in parts:
        if type(part) is not bytes:
            raise TypeError("binary frame requires bytes")
        framed.extend(len(part).to_bytes(4, "big"))
        framed.extend(part)
    return bytes(framed)


def _require_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
    return value


def _derive_binding(kind: str, value: object) -> str:
    identifier = _require_uuid(value)
    try:
        prefix, domain = _BINDING_SPECS[kind]
    except KeyError:
        _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
    material = _binary_frame(
        domain,
        CELL_REPORT_PROPOSAL_BINDING_VERSION.encode("ascii"),
        identifier.bytes,
    )
    return f"{prefix}{hashlib.sha256(material).hexdigest()}"


def _require_binding(kind: str, value: object) -> str:
    try:
        prefix, _domain = _BINDING_SPECS[kind]
    except KeyError:
        _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
    if (
        type(value) is not str
        or len(value) != len(prefix) + 64
        or not value.startswith(prefix)
        or any(
            character not in "0123456789abcdef"
            for character in value[len(prefix) :]
        )
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
    return value


def _require_effect_id(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != len(CELL_REPORT_PROPOSAL_EFFECT_ID_PREFIX) + 64
        or _EFFECT_ID_RE.fullmatch(value) is None
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_EFFECT_ID)
    return value


def _require_payload_digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != len(CELL_REPORT_PROPOSAL_PAYLOAD_DIGEST_PREFIX) + 64
        or _PAYLOAD_DIGEST_RE.fullmatch(value) is None
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
    return value


def _require_base_state_digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != len(CELL_REPORT_PROPOSAL_BASE_DIGEST_PREFIX) + 64
        or _BASE_DIGEST_RE.fullmatch(value) is None
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_BASE_STATE)
    return value


def _canonical_utc_datetime(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError):
        _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)
    if offset is None:
        _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)
    try:
        return value.astimezone(dt.timezone.utc)
    except (OverflowError, TypeError, ValueError):
        _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)


def _render_utc_datetime(value: object) -> str:
    canonical = _canonical_utc_datetime(value)
    return canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc_datetime(value: object) -> dt.datetime:
    if (
        type(value) is not str
        or len(value) != 27
        or _CANONICAL_UTC_RE.fullmatch(value) is None
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)
    return parsed.replace(tzinfo=dt.timezone.utc)


@dataclass(frozen=True, slots=True, repr=False)
class CellReportProposalBindings:
    """Opaque, domain-separated bindings for one pending proposal."""

    tenant: str = field(repr=False)
    meeting: str = field(repr=False)
    conversation: str = field(repr=False)
    actor: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_binding("tenant", self.tenant)
        _require_binding("meeting", self.meeting)
        _require_binding("conversation", self.conversation)
        _require_binding("actor", self.actor)

    def __repr__(self) -> str:
        return "CellReportProposalBindings(<opaque>)"

    def to_jsonb(self) -> dict[str, str]:
        return {
            "tenant": _require_binding("tenant", self.tenant),
            "meeting": _require_binding("meeting", self.meeting),
            "conversation": _require_binding("conversation", self.conversation),
            "actor": _require_binding("actor", self.actor),
        }


def derive_cell_report_proposal_bindings(
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
) -> CellReportProposalBindings:
    """Derive persisted bindings without retaining any raw UUID."""

    return CellReportProposalBindings(
        tenant=_derive_binding("tenant", igreja_id),
        meeting=_derive_binding("meeting", reuniao_id),
        conversation=_derive_binding("conversation", conversa_id),
        actor=_derive_binding("actor", ator_pessoa_id),
    )


def cell_report_proposal_bindings_match(
    persisted: CellReportProposalBindings,
    expected: CellReportProposalBindings,
) -> bool:
    if (
        type(persisted) is not CellReportProposalBindings
        or type(expected) is not CellReportProposalBindings
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
    persisted.to_jsonb()
    expected.to_jsonb()
    return all(
        hmac.compare_digest(left, right)
        for left, right in (
            (persisted.tenant, expected.tenant),
            (persisted.meeting, expected.meeting),
            (persisted.conversation, expected.conversation),
            (persisted.actor, expected.actor),
        )
    )


def derive_cell_report_proposal_base_state_digest(
    *,
    relatorio_status: str,
    oferta_valor: object,
    observacoes: object,
) -> str:
    """Bind a proposal to the report draft observed before its first write.

    Only a pending report can become a proposal.  Money and observations reuse
    the canonical final-snapshot validators, then only their canonical values
    enter a domain-separated digest.  Private observation text is never
    projected as envelope metadata.
    """

    if relatorio_status != "pendente":
        _reject(CellReportPendingProposalErrorCode.INVALID_BASE_STATE)
    try:
        normalized = build_cell_report_snapshot_v2(
            presentes=0,
            visitantes=0,
            decisoes=0,
            oferta_valor=oferta_valor,  # type: ignore[arg-type]
            observacoes=observacoes,  # type: ignore[arg-type]
            submission_effect_id=f"agent_effect_v1_{'0' * 64}",
            submission_payload_digest=f"agent_payload_v1_{'0' * 64}",
        )
        canonical = json.dumps(
            {
                "relatorio_status": relatorio_status,
                "oferta_valor": normalized["oferta_valor"],
                "observacoes": normalized["observacoes"],
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", "strict")
    except (
        CellReportSnapshotValidationError,
        TypeError,
        UnicodeEncodeError,
        ValueError,
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_BASE_STATE)
    material = _binary_frame(
        b"pastorai.cell-report.pending.base-state",
        CELL_REPORT_PROPOSAL_BINDING_VERSION.encode("ascii"),
        canonical,
    )
    return (
        f"{CELL_REPORT_PROPOSAL_BASE_DIGEST_PREFIX}"
        f"{hashlib.sha256(material).hexdigest()}"
    )


@dataclass(frozen=True, slots=True, repr=False)
class CellReportProposalOperationReceipt:
    """One bounded trusted-effect receipt, without its private payload."""

    effect_id: str = field(repr=False)
    payload_digest: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_effect_id(self.effect_id)
        _require_payload_digest(self.payload_digest)

    def __repr__(self) -> str:
        return "CellReportProposalOperationReceipt(<opaque>)"

    def to_jsonb(self) -> dict[str, str]:
        return {
            "effect_id": _require_effect_id(self.effect_id),
            "payload_digest": _require_payload_digest(self.payload_digest),
        }


def _validate_operation_receipts(
    value: object,
) -> tuple[CellReportProposalOperationReceipt, ...]:
    if (
        type(value) is not tuple
        or not value
        or len(value) > MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
    seen: set[str] = set()
    for receipt in value:
        if type(receipt) is not CellReportProposalOperationReceipt:
            _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
        receipt.to_jsonb()
        if receipt.effect_id in seen:
            _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
        seen.add(receipt.effect_id)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class CellReportPendingProposal:
    """Typed view of one validated pending-proposal JSONB object."""

    workflow: CellReportWorkflow = field(repr=False)
    bindings: CellReportProposalBindings = field(repr=False)
    expires_at: dt.datetime = field(repr=False)
    operation_receipts: tuple[CellReportProposalOperationReceipt, ...] = field(
        repr=False
    )
    base_state_digest: str = field(repr=False)

    def __post_init__(self) -> None:
        try:
            workflow = validate_cell_report_workflow(self.workflow)
        except ValueError:
            _reject(CellReportPendingProposalErrorCode.INVALID_WORKFLOW)
        if workflow.state not in _OPEN_PENDING_STATES:
            _reject(CellReportPendingProposalErrorCode.INVALID_PENDING_STATE)
        if type(self.bindings) is not CellReportProposalBindings:
            _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
        self.bindings.to_jsonb()
        canonical_expiry = _canonical_utc_datetime(self.expires_at)
        if (
            self.expires_at.tzinfo is not dt.timezone.utc
            or canonical_expiry != self.expires_at
        ):
            _reject(CellReportPendingProposalErrorCode.INVALID_EXPIRY)
        receipts = _validate_operation_receipts(self.operation_receipts)
        if len(receipts) != workflow.revision:
            _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
        _require_base_state_digest(self.base_state_digest)

    @property
    def last_operation_effect_id(self) -> str:
        return self.operation_receipts[-1].effect_id

    @property
    def last_operation_payload_digest(self) -> str:
        return self.operation_receipts[-1].payload_digest

    def __repr__(self) -> str:
        return "CellReportPendingProposal(<redacted>)"

    def to_jsonb(self) -> dict[str, object]:
        """Return a detached closed object suitable for the JSONB column."""

        self.__post_init__()
        return {
            "schema": CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1,
            "bindings": self.bindings.to_jsonb(),
            "expires_at": _render_utc_datetime(self.expires_at),
            "operation_receipts": [
                receipt.to_jsonb()
                for receipt in _validate_operation_receipts(
                    self.operation_receipts
                )
            ],
            "base_state_digest": _require_base_state_digest(
                self.base_state_digest
            ),
            "workflow": cell_report_workflow_payload(self.workflow),
        }


def build_cell_report_pending_proposal(
    *,
    workflow: CellReportWorkflow,
    bindings: CellReportProposalBindings,
    expires_at: dt.datetime,
    operation_effect_id: str,
    operation_payload_digest: str,
    base_state_digest: str,
    prior_operation_receipts: tuple[
        CellReportProposalOperationReceipt, ...
    ] = (),
) -> CellReportPendingProposal:
    if type(prior_operation_receipts) is not tuple:
        _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
    if prior_operation_receipts:
        _validate_operation_receipts(prior_operation_receipts)
    receipts = (
        *prior_operation_receipts,
        CellReportProposalOperationReceipt(
            effect_id=_require_effect_id(operation_effect_id),
            payload_digest=_require_payload_digest(operation_payload_digest),
        ),
    )
    return CellReportPendingProposal(
        workflow=workflow,
        bindings=bindings,
        expires_at=_canonical_utc_datetime(expires_at),
        operation_receipts=receipts,
        base_state_digest=_require_base_state_digest(base_state_digest),
    )


def rehydrate_cell_report_pending_proposal(
    value: object,
) -> CellReportPendingProposal:
    """Hydrate untrusted JSONB, rejecting unknown keys and schemas."""

    if type(value) is not dict:
        _reject(CellReportPendingProposalErrorCode.INVALID_PROPOSAL)
    if value.get("schema") != CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1:
        _reject(CellReportPendingProposalErrorCode.UNSUPPORTED_SCHEMA)
    if len(value) != len(_ENVELOPE_KEYS) or value.keys() != _ENVELOPE_KEYS:
        _reject(CellReportPendingProposalErrorCode.INVALID_PROPOSAL)

    bindings_value = value.get("bindings")
    if (
        type(bindings_value) is not dict
        or len(bindings_value) != len(_BINDING_KEYS)
        or bindings_value.keys() != _BINDING_KEYS
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_BINDING)
    bindings = CellReportProposalBindings(
        tenant=_require_binding("tenant", bindings_value.get("tenant")),
        meeting=_require_binding("meeting", bindings_value.get("meeting")),
        conversation=_require_binding(
            "conversation",
            bindings_value.get("conversation"),
        ),
        actor=_require_binding("actor", bindings_value.get("actor")),
    )
    try:
        workflow = rehydrate_cell_report_workflow(value.get("workflow"))
    except ValueError:
        _reject(CellReportPendingProposalErrorCode.INVALID_WORKFLOW)
    receipts_value = value.get("operation_receipts")
    if (
        type(receipts_value) is not list
        or not receipts_value
        or len(receipts_value) > MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS
    ):
        _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
    receipts: list[CellReportProposalOperationReceipt] = []
    for raw in receipts_value:
        if (
            type(raw) is not dict
            or len(raw) != len(_OPERATION_RECEIPT_KEYS)
            or raw.keys() != _OPERATION_RECEIPT_KEYS
        ):
            _reject(CellReportPendingProposalErrorCode.INVALID_OPERATION_RECEIPTS)
        receipts.append(
            CellReportProposalOperationReceipt(
                effect_id=_require_effect_id(raw.get("effect_id")),
                payload_digest=_require_payload_digest(raw.get("payload_digest")),
            )
        )
    return CellReportPendingProposal(
        workflow=workflow,
        bindings=bindings,
        expires_at=_parse_utc_datetime(value.get("expires_at")),
        operation_receipts=tuple(receipts),
        base_state_digest=_require_base_state_digest(
            value.get("base_state_digest")
        ),
    )


__all__ = [
    "CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1",
    "MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS",
    "CellReportPendingProposal",
    "CellReportPendingProposalError",
    "CellReportPendingProposalErrorCode",
    "CellReportProposalBindings",
    "CellReportProposalOperationReceipt",
    "build_cell_report_pending_proposal",
    "cell_report_proposal_bindings_match",
    "derive_cell_report_proposal_bindings",
    "derive_cell_report_proposal_base_state_digest",
    "rehydrate_cell_report_pending_proposal",
]

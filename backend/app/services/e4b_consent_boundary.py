"""Boundary E4b C2, inteiramente em memória e sem adapter concreto.

Os contextos deste módulo são atestações de pré-condições resolvidas no
servidor. Eles tornam a fronteira explícita, mas não provam autenticação real,
autorização real ou persistência. As únicas leituras possíveis passam pelas
portas abstratas abaixo e recebem snapshots E4b fechados.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.domain.e4b_consent import (
    E4B_RECEIPT_ALLOWLIST,
    E4bAction,
    E4bAuthorityResolution,
    E4bClassification,
    E4bConcession,
    E4bConfirmedOperation,
    E4bConsentIntent,
    E4bDenialReason,
    E4bFingerprint,
    E4bIdempotencyKey,
    E4bOrigin,
    E4bReceipt,
    E4bValidationError,
    classify_e4b_intent,
    fingerprint_matches_intent,
    project_receipt,
)


class E4bBoundaryValidationError(ValueError):
    """Valor não atende ao contrato fechado do boundary E4b."""


class E4bReplayOutcome(str, Enum):
    """Resultados de negócio exclusivos da classificação de replay."""

    NEW = "NEW"
    EXACT_REPLAY = "EXACT_REPLAY"
    CONFLICT = "CONFLICT"
    DENIED = "DENIED"


class E4bReconciliationOutcome(str, Enum):
    """Resultados de negócio exclusivos da reconciliação read-only."""

    CONFIRMED = "CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class E4bBoundaryOperation(str, Enum):
    """Operação lógica para uma falha interna sanitizada."""

    REPLAY = "REPLAY"
    RECONCILE = "RECONCILE"


class E4bBoundaryFailureCode(str, Enum):
    """Códigos sanitizados, sem detalhe de infraestrutura ou conteúdo."""

    INVALID_CONTEXT = "INVALID_CONTEXT"
    INVALID_SELECTOR = "INVALID_SELECTOR"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SNAPSHOT_UNTRUSTED = "SNAPSHOT_UNTRUSTED"
    CHAIN_INCOMPLETE = "CHAIN_INCOMPLETE"


class E4bSnapshotPresence(str, Enum):
    """Prova fechada de presença, ausência ou inaplicabilidade de um snapshot."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class E4bReplayObservation(str, Enum):
    """Estado da cadeia observada para replay antes da classificação C0."""

    COMPLETE = "COMPLETE"
    INCOMPLETE_OR_INCONSISTENT = "INCOMPLETE_OR_INCONSISTENT"


class E4bReconciliationObservation(str, Enum):
    """Estado observado por uma porta E4b de reconciliação."""

    CONFIRMED = "CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"
    INCOMPLETE_OR_INCONSISTENT = "INCOMPLETE_OR_INCONSISTENT"


E4B_FUTURE_LOGICAL_ORDER: Final[tuple[str, ...]] = (
    "autoridade e tenant",
    "K",
    "L",
    "C",
    "stream",
    "revalidação",
    "staging",
    "owner externo",
)
"""Ordem documental futura, sem aquisição de recurso nesta fase C2."""


def _fail(field_name: str, message: str) -> None:
    raise E4bBoundaryValidationError(f"{field_name}: {message}")


def _require_uuid(value: object, *, field_name: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _fail(field_name, "UUID não nulo obrigatório")
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(field_name, "texto normalizado obrigatório")
    if len(value) > 128:
        _fail(field_name, "texto excede o limite")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(field_name, "texto contém caractere de controle")
    return value


def _require_exact_enum(
    value: object, enum_type: type[Enum], *, field_name: str
) -> None:
    if type(value) is not enum_type:
        _fail(field_name, "enum fechado obrigatório")


def _require_key(value: object, *, field_name: str) -> E4bIdempotencyKey:
    if type(value) is not E4bIdempotencyKey:
        _fail(field_name, "chave E4b obrigatória")
    try:
        canonical = E4bIdempotencyKey(igreja_id=value.igreja_id, value=value.value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise E4bBoundaryValidationError(
            f"{field_name}: chave E4b inválida"
        ) from exc
    if canonical != value:
        _fail(field_name, "chave E4b inválida")
    return value


def _require_fingerprint(value: object, *, field_name: str) -> E4bFingerprint:
    if type(value) is not E4bFingerprint:
        _fail(field_name, "fingerprint E4b obrigatório")
    try:
        canonical = E4bFingerprint(value.value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise E4bBoundaryValidationError(
            f"{field_name}: fingerprint E4b inválido"
        ) from exc
    if canonical != value:
        _fail(field_name, "fingerprint E4b inválido")
    return value


def _require_selector(value: object, *, field_name: str) -> "E4bLookupSelector":
    if type(value) not in (E4bOperationSelector, E4bCorrelationSelector):
        _fail(field_name, "seletor E4b I ou C obrigatório")
    if not _selector_has_closed_shape(value):
        _fail(field_name, "seletor E4b inválido")
    return value


@dataclass(frozen=True, slots=True)
class E4bServerResolvedReplayContext:
    """Contexto fechado para replay, atestado antes de entrar neste módulo."""

    igreja_id: uuid.UUID
    authority: E4bAuthorityResolution
    server_resolved: bool = True
    presented_credential: object | None = field(default=None, repr=False, compare=False)
    legacy_artifact: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        if type(self.authority) is not E4bAuthorityResolution:
            _fail("authority", "resolução E4b obrigatória")
        if not _authority_has_closed_shape(self.authority):
            _fail("authority", "resolução E4b inválida")
        if type(self.server_resolved) is not bool:
            _fail("server_resolved", "booleano obrigatório")


@dataclass(frozen=True, slots=True)
class E4bServerResolvedReadContext:
    """Contexto fechado para reconciliação, atestado antes da leitura E4b."""

    igreja_id: uuid.UUID
    authority: E4bAuthorityResolution
    server_resolved: bool = True
    read_authorized: bool = True
    presented_credential: object | None = field(default=None, repr=False, compare=False)
    legacy_artifact: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        if type(self.authority) is not E4bAuthorityResolution:
            _fail("authority", "resolução E4b obrigatória")
        if not _authority_has_closed_shape(self.authority):
            _fail("authority", "resolução E4b inválida")
        if type(self.server_resolved) is not bool:
            _fail("server_resolved", "booleano obrigatório")
        if type(self.read_authorized) is not bool:
            _fail("read_authorized", "booleano obrigatório")


@dataclass(frozen=True, slots=True)
class E4bOperationSelector:
    """Seletor fechado por I, sempre scoped à igreja E4b."""

    igreja_id: uuid.UUID
    operation_id: uuid.UUID

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.operation_id, field_name="operation_id")


@dataclass(frozen=True, slots=True)
class E4bCorrelationSelector:
    """Seletor fechado por C, sempre scoped à igreja E4b."""

    igreja_id: uuid.UUID
    correlation_id: uuid.UUID

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.correlation_id, field_name="correlation_id")


E4bLookupSelector = E4bOperationSelector | E4bCorrelationSelector


def _selector_has_closed_shape(selector: object) -> bool:
    """Revalida I ou C sem aceitar objeto congelado adulterado."""

    try:
        if type(selector) is E4bOperationSelector:
            canonical = E4bOperationSelector(
                igreja_id=selector.igreja_id,
                operation_id=selector.operation_id,
            )
        elif type(selector) is E4bCorrelationSelector:
            canonical = E4bCorrelationSelector(
                igreja_id=selector.igreja_id,
                correlation_id=selector.correlation_id,
            )
        else:
            return False
    except Exception:
        return False
    return canonical == selector


@dataclass(frozen=True, slots=True)
class E4bSnapshotProvenance:
    """Proveniência mínima que uma porta E4b precisa atestar."""

    igreja_id: uuid.UUID
    origin: E4bOrigin
    server_resolved: bool = True
    read_only: bool = True

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_exact_enum(self.origin, E4bOrigin, field_name="origin")
        if type(self.server_resolved) is not bool:
            _fail("server_resolved", "booleano obrigatório")
        if type(self.read_only) is not bool:
            _fail("read_only", "booleano obrigatório")


@dataclass(frozen=True, slots=True)
class E4bReplayReadRequest:
    """Pedido fechado derivado da intenção, sem aceitar dados livres."""

    igreja_id: uuid.UUID
    idempotency_key: E4bIdempotencyKey
    fingerprint: E4bFingerprint
    correlation_id: uuid.UUID
    action: E4bAction
    origin: E4bOrigin
    titular_pessoa_id: uuid.UUID
    finalidade_id: str
    origin_accept_operation_id: uuid.UUID | None

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        key = _require_key(self.idempotency_key, field_name="idempotency_key")
        if key.igreja_id != self.igreja_id:
            _fail("igreja_id", "K pertence a outra igreja")
        _require_fingerprint(self.fingerprint, field_name="fingerprint")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        _require_exact_enum(self.action, E4bAction, field_name="action")
        _require_exact_enum(self.origin, E4bOrigin, field_name="origin")
        _require_uuid(self.titular_pessoa_id, field_name="titular_pessoa_id")
        _require_text(self.finalidade_id, field_name="finalidade_id")
        if self.origin_accept_operation_id is not None:
            _require_uuid(
                self.origin_accept_operation_id,
                field_name="origin_accept_operation_id",
            )


@dataclass(frozen=True, slots=True)
class E4bReconciliationReadRequest:
    """Pedido fechado por exatamente um seletor I ou C."""

    igreja_id: uuid.UUID
    selector: E4bLookupSelector

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        selector = _require_selector(self.selector, field_name="selector")
        if selector.igreja_id != self.igreja_id:
            _fail("igreja_id", "seletor pertence a outra igreja")


@dataclass(frozen=True, slots=True)
class E4bHistoricalOperationIdentity:
    """Identidade histórica fechada que permite revalidar F sem input atual."""

    igreja_id: uuid.UUID
    operation_id: uuid.UUID
    receipt_id: uuid.UUID
    idempotency_key: E4bIdempotencyKey
    fingerprint: E4bFingerprint
    authority: E4bAuthorityResolution
    action: E4bAction
    origin_accept_operation_id: uuid.UUID | None

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.operation_id, field_name="operation_id")
        _require_uuid(self.receipt_id, field_name="receipt_id")
        key = _require_key(self.idempotency_key, field_name="idempotency_key")
        if key.igreja_id != self.igreja_id:
            _fail("igreja_id", "K pertence a outra igreja")
        _require_fingerprint(self.fingerprint, field_name="fingerprint")
        if type(self.authority) is not E4bAuthorityResolution:
            _fail("authority", "resolução histórica E4b obrigatória")
        if self.authority.igreja_id != self.igreja_id:
            _fail("igreja_id", "autoridade pertence a outra igreja")
        _require_exact_enum(self.action, E4bAction, field_name="action")
        if self.origin_accept_operation_id is not None:
            _require_uuid(
                self.origin_accept_operation_id,
                field_name="origin_accept_operation_id",
            )

    def as_intent(self) -> E4bConsentIntent:
        """Recompõe somente a intenção tipada necessária para validar F."""

        return E4bConsentIntent(
            action=self.action,
            idempotency_key=self.idempotency_key,
            fingerprint=self.fingerprint,
            authority=self.authority,
            origin_accept_operation_id=self.origin_accept_operation_id,
        )


def _require_present_or_absent(
    presence: object,
    value: object | None,
    expected_type: type[object],
    *,
    field_name: str,
) -> None:
    _require_exact_enum(presence, E4bSnapshotPresence, field_name=f"{field_name}_presence")
    if presence is E4bSnapshotPresence.PRESENT:
        if type(value) is not expected_type:
            _fail(field_name, "snapshot E4b presente obrigatório")
    elif value is not None:
        _fail(field_name, "snapshot ausente não pode transportar valor")


def _require_historical_identity_for_presence(
    presence: object,
    identity: object | None,
    *,
    field_name: str,
) -> None:
    """Fecha a cardinalidade entre payload observado e sua prova histórica."""

    if presence is E4bSnapshotPresence.PRESENT:
        if type(identity) is not E4bHistoricalOperationIdentity:
            _fail(field_name, "snapshot presente exige identidade histórica E4b")
    elif identity is not None:
        _fail(field_name, "payload ausente não pode transportar identidade histórica")


def _confirmed_operation_is_canonical(operation: object) -> bool:
    """Revalida um snapshot confirmado que pode ter sido adulterado após C0."""

    if type(operation) is not E4bConfirmedOperation:
        return False
    try:
        canonical = E4bConfirmedOperation(
            operation_id=operation.operation_id,
            igreja_id=operation.igreja_id,
            idempotency_key=operation.idempotency_key,
            correlation_id=operation.correlation_id,
            fingerprint=operation.fingerprint,
            action=operation.action,
            origin=operation.origin,
            titular_pessoa_id=operation.titular_pessoa_id,
            manifestante_pessoa_id=operation.manifestante_pessoa_id,
            manifestant_role=operation.manifestant_role,
            responsavel_pessoa_id=operation.responsavel_pessoa_id,
            operador_id=operation.operador_id,
            finalidade_id=operation.finalidade_id,
            origin_accept_operation_id=operation.origin_accept_operation_id,
            concession_state=operation.concession_state,
            receipt_id=operation.receipt_id,
            confirmed_at=operation.confirmed_at,
            contract_version=operation.contract_version,
            policy_version=operation.policy_version,
            term_version=operation.term_version,
            content_digest=operation.content_digest,
        )
    except Exception:
        return False
    return canonical == operation


def _concession_is_canonical(concession: object) -> bool:
    """Revalida a projeção de concessão antes de permitir `NEW` ou C0."""

    if type(concession) is not E4bConcession:
        return False
    try:
        canonical = E4bConcession(
            igreja_id=concession.igreja_id,
            titular_pessoa_id=concession.titular_pessoa_id,
            finalidade_id=concession.finalidade_id,
            state=concession.state,
            accept_operation_id=concession.accept_operation_id,
            withdraw_operation_id=concession.withdraw_operation_id,
        )
    except Exception:
        return False
    return canonical == concession


def _authority_has_closed_shape(authority: object) -> bool:
    """Revalida autoridade E4b sem converter atestação válida em semântica."""

    if type(authority) is not E4bAuthorityResolution:
        return False
    try:
        canonical = E4bAuthorityResolution(
            igreja_id=authority.igreja_id,
            titular_pessoa_id=authority.titular_pessoa_id,
            manifestante_pessoa_id=authority.manifestante_pessoa_id,
            manifestant_role=authority.manifestant_role,
            responsavel_pessoa_id=authority.responsavel_pessoa_id,
            operador_id=authority.operador_id,
            operator_kind=authority.operator_kind,
            finalidade_id=authority.finalidade_id,
            origin=authority.origin,
            correlation_id=authority.correlation_id,
            contract_version=authority.contract_version,
            policy_version=authority.policy_version,
            term_version=authority.term_version,
            content_digest=authority.content_digest,
            server_resolved=authority.server_resolved,
            manifestant_relation_valid=authority.manifestant_relation_valid,
            operator_role_links=authority.operator_role_links,
            legacy_artifact=authority.legacy_artifact,
        )
    except Exception:
        return False
    return canonical == authority


def _historical_identity_has_closed_shape(identity: object) -> bool:
    """Fecha identidade e autoridade interna antes de C0 ou receipt."""

    if type(identity) is not E4bHistoricalOperationIdentity:
        return False
    try:
        if not _authority_has_closed_shape(identity.authority):
            return False
        canonical = E4bHistoricalOperationIdentity(
            igreja_id=identity.igreja_id,
            operation_id=identity.operation_id,
            receipt_id=identity.receipt_id,
            idempotency_key=identity.idempotency_key,
            fingerprint=identity.fingerprint,
            authority=identity.authority,
            action=identity.action,
            origin_accept_operation_id=identity.origin_accept_operation_id,
        )
    except Exception:
        return False
    return canonical == identity


def _historical_payload_matches_tenant(
    operation: object,
    identity: object,
    *,
    igreja_id: object,
) -> bool:
    """Vincula operação, prova histórica e K ao mesmo tenant fechado."""

    if (
        type(operation) is not E4bConfirmedOperation
        or type(identity) is not E4bHistoricalOperationIdentity
        or type(igreja_id) is not uuid.UUID
        or not _historical_identity_has_closed_shape(identity)
    ):
        return False
    return (
        operation.igreja_id == igreja_id
        and type(operation.idempotency_key) is E4bIdempotencyKey
        and operation.idempotency_key.igreja_id == igreja_id
        and identity.igreja_id == igreja_id
        and type(identity.idempotency_key) is E4bIdempotencyKey
        and identity.idempotency_key.igreja_id == igreja_id
    )


def _historical_payload_matches_replay_scope(
    operation: object,
    identity: object,
    *,
    igreja_id: object,
    idempotency_key: object,
) -> bool:
    """Vincula payload histórico `PRESENT` à igreja e à K do request."""

    return (
        _historical_payload_matches_tenant(
            operation,
            identity,
            igreja_id=igreja_id,
        )
        and type(idempotency_key) is E4bIdempotencyKey
        and operation.idempotency_key == idempotency_key
        and identity.idempotency_key == idempotency_key
    )


@dataclass(frozen=True, slots=True)
class E4bReplaySnapshot:
    """Observação fechada para replay, incluindo provas explícitas de ausência."""

    igreja_id: uuid.UUID
    idempotency_key: E4bIdempotencyKey
    fingerprint: E4bFingerprint
    correlation_id: uuid.UUID
    action: E4bAction
    origin: E4bOrigin
    origin_accept_operation_id: uuid.UUID | None
    provenance: E4bSnapshotProvenance
    operation_presence: E4bSnapshotPresence
    existing_operation: E4bConfirmedOperation | None
    concession_presence: E4bSnapshotPresence
    concession: E4bConcession | None
    origin_presence: E4bSnapshotPresence
    origin_accept_operation: E4bConfirmedOperation | None
    observation: E4bReplayObservation = E4bReplayObservation.COMPLETE
    existing_operation_identity: E4bHistoricalOperationIdentity | None = None
    origin_accept_operation_identity: E4bHistoricalOperationIdentity | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        key = _require_key(self.idempotency_key, field_name="idempotency_key")
        if key.igreja_id != self.igreja_id:
            _fail("igreja_id", "K pertence a outra igreja")
        _require_fingerprint(self.fingerprint, field_name="fingerprint")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        _require_exact_enum(self.action, E4bAction, field_name="action")
        _require_exact_enum(self.origin, E4bOrigin, field_name="origin")
        if self.origin_accept_operation_id is not None:
            _require_uuid(
                self.origin_accept_operation_id,
                field_name="origin_accept_operation_id",
            )
        if type(self.provenance) is not E4bSnapshotProvenance:
            _fail("provenance", "proveniência E4b obrigatória")
        if (
            self.existing_operation_identity is not None
            and type(self.existing_operation_identity) is not E4bHistoricalOperationIdentity
        ):
            _fail("existing_operation_identity", "identidade histórica E4b obrigatória")
        if (
            self.origin_accept_operation_identity is not None
            and type(self.origin_accept_operation_identity)
            is not E4bHistoricalOperationIdentity
        ):
            _fail(
                "origin_accept_operation_identity",
                "identidade histórica E4b obrigatória",
            )
        _require_exact_enum(
            self.observation,
            E4bReplayObservation,
            field_name="observation",
        )
        _require_present_or_absent(
            self.operation_presence,
            self.existing_operation,
            E4bConfirmedOperation,
            field_name="existing_operation",
        )
        _require_present_or_absent(
            self.concession_presence,
            self.concession,
            E4bConcession,
            field_name="concession",
        )
        _require_present_or_absent(
            self.origin_presence,
            self.origin_accept_operation,
            E4bConfirmedOperation,
            field_name="origin_accept_operation",
        )
        _require_historical_identity_for_presence(
            self.operation_presence,
            self.existing_operation_identity,
            field_name="existing_operation_identity",
        )
        _require_historical_identity_for_presence(
            self.origin_presence,
            self.origin_accept_operation_identity,
            field_name="origin_accept_operation_identity",
        )
        if (
            self.observation is E4bReplayObservation.COMPLETE
            and self.operation_presence is E4bSnapshotPresence.NOT_APPLICABLE
        ):
            _fail("operation_presence", "K deve ter presença ou ausência provada")
        if self.observation is E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT:
            if (
                self.operation_presence is not E4bSnapshotPresence.NOT_APPLICABLE
                or self.concession_presence is not E4bSnapshotPresence.NOT_APPLICABLE
                or self.origin_presence is not E4bSnapshotPresence.NOT_APPLICABLE
            ):
                _fail("observation", "cadeia incompleta não carrega prova parcial")
        if self.existing_operation is not None:
            if not _confirmed_operation_is_canonical(self.existing_operation):
                _fail("existing_operation", "operação confirmada E4b inválida")
            if self.existing_operation.igreja_id != self.igreja_id:
                _fail("existing_operation", "operação pertence a outra igreja")
            if self.existing_operation.idempotency_key != self.idempotency_key:
                _fail("existing_operation", "operação não pertence a K")
            if not _historical_payload_matches_replay_scope(
                self.existing_operation,
                self.existing_operation_identity,
                igreja_id=self.igreja_id,
                idempotency_key=self.idempotency_key,
            ):
                _fail(
                    "existing_operation_identity",
                    "operação e identidade não pertencem ao escopo do replay",
                )
        if self.concession is not None:
            if not _concession_is_canonical(self.concession):
                _fail("concession", "concessão E4b inválida")
            if self.concession.igreja_id != self.igreja_id:
                _fail("concession", "concessão pertence a outra igreja")
        if (
            self.origin_accept_operation is not None
            and self.origin_accept_operation.igreja_id != self.igreja_id
        ):
            _fail("origin_accept_operation", "origem pertence a outra igreja")
        if self.origin_accept_operation is not None:
            if not _confirmed_operation_is_canonical(self.origin_accept_operation):
                _fail("origin_accept_operation", "origem E4b inválida")
            if not _historical_payload_matches_tenant(
                self.origin_accept_operation,
                self.origin_accept_operation_identity,
                igreja_id=self.igreja_id,
            ):
                _fail(
                    "origin_accept_operation_identity",
                    "origem e identidade não pertencem à igreja do replay",
                )


@dataclass(frozen=True, slots=True)
class E4bReconciliationSnapshot:
    """Observação fechada para reconciliação E4b read-only."""

    igreja_id: uuid.UUID
    selector: E4bLookupSelector
    provenance: E4bSnapshotProvenance
    observation: E4bReconciliationObservation
    operation: E4bConfirmedOperation | None
    historical_identity: E4bHistoricalOperationIdentity | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        selector = _require_selector(self.selector, field_name="selector")
        if selector.igreja_id != self.igreja_id:
            _fail("igreja_id", "seletor pertence a outra igreja")
        if type(self.provenance) is not E4bSnapshotProvenance:
            _fail("provenance", "proveniência E4b obrigatória")
        if (
            self.historical_identity is not None
            and type(self.historical_identity) is not E4bHistoricalOperationIdentity
        ):
            _fail("historical_identity", "identidade histórica E4b obrigatória")
        _require_exact_enum(
            self.observation,
            E4bReconciliationObservation,
            field_name="observation",
        )
        if self.observation is E4bReconciliationObservation.CONFIRMED:
            if type(self.operation) is not E4bConfirmedOperation:
                _fail("operation", "operação confirmada E4b obrigatória")
            if type(self.historical_identity) is not E4bHistoricalOperationIdentity:
                _fail("historical_identity", "operação confirmada exige identidade histórica")
            if not _confirmed_operation_is_canonical(self.operation):
                _fail("operation", "operação confirmada E4b inválida")
            if self.operation.igreja_id != self.igreja_id:
                _fail("operation", "operação pertence a outra igreja")
            if not _historical_payload_matches_tenant(
                self.operation,
                self.historical_identity,
                igreja_id=self.igreja_id,
            ):
                _fail(
                    "historical_identity",
                    "operação e identidade não pertencem ao tenant da reconciliação",
                )
        elif self.operation is not None or self.historical_identity is not None:
            _fail(
                "operation",
                "ausência ou incerteza não expõe operação ou identidade histórica",
            )


class E4bReplayReadPort(ABC):
    """Porta abstrata de leitura E4b para classificação de replay."""

    @abstractmethod
    def read_replay_snapshot(self, request: E4bReplayReadRequest) -> E4bReplaySnapshot:
        """Retorna uma observação E4b fechada, sem escrever ou reexecutar."""


class E4bReconciliationReadPort(ABC):
    """Porta abstrata de leitura E4b para reconciliação."""

    @abstractmethod
    def read_reconciliation_snapshot(
        self, request: E4bReconciliationReadRequest
    ) -> E4bReconciliationSnapshot:
        """Retorna uma observação E4b read-only, sem escrever ou reexecutar."""


@dataclass(frozen=True, slots=True)
class E4bReplayDecision:
    """Decisão minimizada de replay, sem operação bruta ou IDs de pessoas."""

    outcome: E4bReplayOutcome
    receipt: E4bReceipt | None = None
    denial_reason: E4bDenialReason | None = None

    def __post_init__(self) -> None:
        _require_exact_enum(self.outcome, E4bReplayOutcome, field_name="outcome")
        if self.outcome is E4bReplayOutcome.EXACT_REPLAY:
            if type(self.receipt) is not E4bReceipt:
                _fail("receipt", "replay exato exige receipt E4b")
        elif self.receipt is not None:
            _fail("receipt", "somente replay exato expõe receipt")
        if self.outcome is E4bReplayOutcome.DENIED:
            _require_exact_enum(
                self.denial_reason,
                E4bDenialReason,
                field_name="denial_reason",
            )
        elif self.denial_reason is not None:
            _fail("denial_reason", "somente negação expõe motivo sanitizado")


@dataclass(frozen=True, slots=True)
class E4bReconciliationDecision:
    """Decisão minimizada de reconciliação, sem operação bruta ou IDs pessoais."""

    outcome: E4bReconciliationOutcome
    receipt: E4bReceipt | None = None

    def __post_init__(self) -> None:
        _require_exact_enum(self.outcome, E4bReconciliationOutcome, field_name="outcome")
        if self.outcome is E4bReconciliationOutcome.CONFIRMED:
            if type(self.receipt) is not E4bReceipt:
                _fail("receipt", "confirmação exige receipt E4b")
        elif self.receipt is not None:
            _fail("receipt", "somente confirmação expõe receipt")


@dataclass(frozen=True, slots=True)
class E4bBoundaryFailure:
    """Falha interna sanitizada, disjunta de toda decisão de negócio."""

    operation: E4bBoundaryOperation
    code: E4bBoundaryFailureCode

    def __post_init__(self) -> None:
        _require_exact_enum(self.operation, E4bBoundaryOperation, field_name="operation")
        _require_exact_enum(self.code, E4bBoundaryFailureCode, field_name="code")


def _failure(
    operation: E4bBoundaryOperation, code: E4bBoundaryFailureCode
) -> E4bBoundaryFailure:
    return E4bBoundaryFailure(operation=operation, code=code)


def _trusted_provenance(provenance: object, *, igreja_id: uuid.UUID) -> bool:
    return (
        type(provenance) is E4bSnapshotProvenance
        and provenance.igreja_id == igreja_id
        and provenance.origin is E4bOrigin.E4B
        and provenance.server_resolved is True
        and provenance.read_only is True
    )


def _allowlisted_receipt(operation: object) -> E4bReceipt | None:
    """Projeta e confere o único receipt que pode atravessar esta fronteira."""

    if not _confirmed_operation_is_canonical(operation):
        return None
    try:
        if (
            type(operation.idempotency_key) is not E4bIdempotencyKey
            or operation.idempotency_key.igreja_id != operation.igreja_id
            or type(operation.fingerprint) is not E4bFingerprint
            or type(operation.origin) is not E4bOrigin
            or operation.origin is not E4bOrigin.E4B
            or type(operation.operation_id) is not uuid.UUID
            or operation.operation_id.int == 0
            or type(operation.correlation_id) is not uuid.UUID
            or operation.correlation_id.int == 0
        ):
            return None
        receipt = project_receipt(operation)
        mapping = receipt.to_mapping()
    except (AttributeError, TypeError, ValueError, E4bValidationError):
        return None
    if type(receipt) is not E4bReceipt or type(mapping) is not dict:
        return None
    if set(mapping) != E4B_RECEIPT_ALLOWLIST or not all(
        type(value) is str for value in mapping.values()
    ):
        return None
    if (
        receipt.operation_id != operation.operation_id
        or receipt.correlation_id != operation.correlation_id
        or receipt.receipt_id != operation.receipt_id
        or receipt.igreja_id != operation.igreja_id
        or receipt.fingerprint != operation.fingerprint
    ):
        return None
    direct_person_values = {
        str(operation.titular_pessoa_id),
        str(operation.manifestante_pessoa_id),
        str(operation.operador_id),
    }
    if operation.responsavel_pessoa_id is not None:
        direct_person_values.add(str(operation.responsavel_pessoa_id))
    if direct_person_values.intersection(mapping.values()):
        return None
    return receipt


def _valid_replay_context(
    intent: object, context: object
) -> tuple[E4bConsentIntent, E4bServerResolvedReplayContext] | None:
    if type(intent) is not E4bConsentIntent:
        return None
    if type(context) is not E4bServerResolvedReplayContext:
        return None
    try:
        authority = intent.authority
        if (
            context.server_resolved is not True
            or context.presented_credential is not None
            or context.legacy_artifact is not None
            or type(authority) is not E4bAuthorityResolution
            or not _authority_has_closed_shape(authority)
            or not _authority_has_closed_shape(context.authority)
            or context.authority != authority
            or context.igreja_id != authority.igreja_id
            or type(intent.action) is not E4bAction
            or type(authority.origin) is not E4bOrigin
            or not isinstance(authority.correlation_id, uuid.UUID)
            or authority.correlation_id.int == 0
        ):
            return None
        _require_key(intent.idempotency_key, field_name="idempotency_key")
        _require_fingerprint(intent.fingerprint, field_name="fingerprint")
    except (AttributeError, TypeError, ValueError, E4bBoundaryValidationError):
        return None
    return intent, context


def _valid_read_context(context: object) -> E4bServerResolvedReadContext | None:
    if type(context) is not E4bServerResolvedReadContext:
        return None
    try:
        authority = context.authority
        if (
            context.server_resolved is not True
            or context.read_authorized is not True
            or context.presented_credential is not None
            or context.legacy_artifact is not None
            or type(authority) is not E4bAuthorityResolution
            or not _authority_has_closed_shape(authority)
            or authority.server_resolved is not True
            or authority.legacy_artifact is not None
            or context.igreja_id != authority.igreja_id
            or authority.origin is not E4bOrigin.E4B
            or type(authority.correlation_id) is not uuid.UUID
            or authority.correlation_id.int == 0
        ):
            return None
    except AttributeError:
        return None
    return context


def _replay_precondition_decision(intent: E4bConsentIntent) -> E4bReplayDecision | None:
    """Aplica negações C0 independentes da observação antes de ler a porta."""

    try:
        if intent.legacy_artifact is not None or intent.authority.legacy_artifact is not None:
            return E4bReplayDecision(
                outcome=E4bReplayOutcome.DENIED,
                denial_reason=E4bDenialReason.LEGACY_ARTIFACT,
            )
        preliminary = classify_e4b_intent(intent)
    except (AttributeError, TypeError, ValueError, E4bValidationError):
        return None
    if preliminary.classification is not E4bClassification.DENIED:
        return None
    if (
        preliminary.reason is E4bDenialReason.MISSING_ORIGIN
        and intent.action is E4bAction.WITHDRAW
        and intent.origin_accept_operation_id is not None
    ):
        # C0 ainda precisa da origem E4b para decidir este caso específico.
        return None
    if type(preliminary.reason) is not E4bDenialReason:
        return None
    return E4bReplayDecision(
        outcome=E4bReplayOutcome.DENIED,
        denial_reason=preliminary.reason,
    )


def _same_closed_replay_identity(
    intent: E4bConsentIntent, operation: E4bConfirmedOperation
) -> bool:
    """Confere dimensões fechadas persistidas antes de aceitar replay exato.

    O C0 usa F como classificador de replay. Nesta fronteira, F igual não é
    suficiente quando um snapshot externo traz outra dimensão fechada com o
    mesmo digest copiado. A cadeia passa a ser não confiável, sem ser exposta.
    """

    authority = intent.authority
    return (
        operation.igreja_id == authority.igreja_id
        and operation.idempotency_key == intent.idempotency_key
        and operation.correlation_id == authority.correlation_id
        and operation.fingerprint == intent.fingerprint
        and operation.action is intent.action
        and operation.origin is authority.origin
        and operation.titular_pessoa_id == authority.titular_pessoa_id
        and operation.manifestante_pessoa_id == authority.manifestante_pessoa_id
        and operation.manifestant_role is authority.manifestant_role
        and operation.responsavel_pessoa_id == authority.responsavel_pessoa_id
        and operation.operador_id == authority.operador_id
        and operation.finalidade_id == authority.finalidade_id
        and operation.origin_accept_operation_id == intent.origin_accept_operation_id
        and operation.contract_version == authority.contract_version
        and operation.policy_version == authority.policy_version
        and operation.term_version == authority.term_version
        and operation.content_digest == authority.content_digest
    )


def _historical_identity_is_canonical(identity: object) -> bool:
    if not _historical_identity_has_closed_shape(identity):
        return False
    try:
        authority = identity.authority
        if (
            authority.server_resolved is not True
            or authority.manifestant_relation_valid is not True
            or authority.legacy_artifact is not None
            or authority.origin is not E4bOrigin.E4B
        ):
            return False
        return fingerprint_matches_intent(identity.as_intent())
    except (AttributeError, TypeError, ValueError, E4bValidationError):
        return False


def _historical_identity_matches_operation(
    identity: E4bHistoricalOperationIdentity, operation: E4bConfirmedOperation
) -> bool:
    authority = identity.authority
    return (
        operation.igreja_id == identity.igreja_id
        and operation.operation_id == identity.operation_id
        and operation.receipt_id == identity.receipt_id
        and operation.idempotency_key == identity.idempotency_key
        and operation.fingerprint == identity.fingerprint
        and operation.correlation_id == authority.correlation_id
        and operation.action is identity.action
        and operation.origin is authority.origin
        and operation.titular_pessoa_id == authority.titular_pessoa_id
        and operation.manifestante_pessoa_id == authority.manifestante_pessoa_id
        and operation.manifestant_role is authority.manifestant_role
        and operation.responsavel_pessoa_id == authority.responsavel_pessoa_id
        and operation.operador_id == authority.operador_id
        and operation.finalidade_id == authority.finalidade_id
        and operation.origin_accept_operation_id == identity.origin_accept_operation_id
        and operation.contract_version == authority.contract_version
        and operation.policy_version == authority.policy_version
        and operation.term_version == authority.term_version
        and operation.content_digest == authority.content_digest
    )


def _complete_historical_operation_proof(
    identity: object, operation: object
) -> bool:
    return (
        type(identity) is E4bHistoricalOperationIdentity
        and type(operation) is E4bConfirmedOperation
        and _confirmed_operation_is_canonical(operation)
        and _historical_identity_is_canonical(identity)
        and _historical_identity_matches_operation(identity, operation)
    )


def _replay_snapshot_matches_request(
    *, request: E4bReplayReadRequest, snapshot: object
) -> bool:
    if type(snapshot) is not E4bReplaySnapshot:
        return False
    try:
        return (
            snapshot.igreja_id == request.igreja_id
            and snapshot.idempotency_key == request.idempotency_key
            and snapshot.fingerprint == request.fingerprint
            and snapshot.correlation_id == request.correlation_id
            and snapshot.action is request.action
            and snapshot.origin is request.origin
            and snapshot.origin_accept_operation_id == request.origin_accept_operation_id
            and _trusted_provenance(snapshot.provenance, igreja_id=request.igreja_id)
            and type(snapshot.observation) is E4bReplayObservation
            and type(snapshot.operation_presence) is E4bSnapshotPresence
            and type(snapshot.concession_presence) is E4bSnapshotPresence
            and type(snapshot.origin_presence) is E4bSnapshotPresence
        )
    except AttributeError:
        return False


def _replay_snapshot_shape_is_consistent(snapshot: object) -> bool:
    """Rejeita presença e prova histórica contraditórias antes do C0."""

    if type(snapshot) is not E4bReplaySnapshot:
        return False
    try:
        if (
            type(snapshot.observation) is not E4bReplayObservation
            or type(snapshot.operation_presence) is not E4bSnapshotPresence
            or type(snapshot.concession_presence) is not E4bSnapshotPresence
            or type(snapshot.origin_presence) is not E4bSnapshotPresence
        ):
            return False
        if snapshot.operation_presence is E4bSnapshotPresence.PRESENT:
            if (
                type(snapshot.existing_operation) is not E4bConfirmedOperation
                or not _confirmed_operation_is_canonical(snapshot.existing_operation)
                or type(snapshot.existing_operation_identity)
                is not E4bHistoricalOperationIdentity
                or not _historical_payload_matches_replay_scope(
                    snapshot.existing_operation,
                    snapshot.existing_operation_identity,
                    igreja_id=snapshot.igreja_id,
                    idempotency_key=snapshot.idempotency_key,
                )
            ):
                return False
        elif (
            snapshot.existing_operation is not None
            or snapshot.existing_operation_identity is not None
        ):
            return False

        if snapshot.concession_presence is E4bSnapshotPresence.PRESENT:
            if (
                type(snapshot.concession) is not E4bConcession
                or not _concession_is_canonical(snapshot.concession)
                or snapshot.concession.igreja_id != snapshot.igreja_id
            ):
                return False
        elif snapshot.concession is not None:
            return False

        if snapshot.origin_presence is E4bSnapshotPresence.PRESENT:
            if (
                type(snapshot.origin_accept_operation) is not E4bConfirmedOperation
                or not _confirmed_operation_is_canonical(
                    snapshot.origin_accept_operation
                )
                or type(snapshot.origin_accept_operation_identity)
                is not E4bHistoricalOperationIdentity
                or not _historical_payload_matches_tenant(
                    snapshot.origin_accept_operation,
                    snapshot.origin_accept_operation_identity,
                    igreja_id=snapshot.igreja_id,
                )
            ):
                return False
        elif (
            snapshot.origin_accept_operation is not None
            or snapshot.origin_accept_operation_identity is not None
        ):
            return False

        if snapshot.observation is E4bReplayObservation.COMPLETE:
            return snapshot.operation_presence in (
                E4bSnapshotPresence.PRESENT,
                E4bSnapshotPresence.ABSENT,
            )
        if snapshot.observation is E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT:
            return (
                snapshot.operation_presence is E4bSnapshotPresence.NOT_APPLICABLE
                and snapshot.concession_presence is E4bSnapshotPresence.NOT_APPLICABLE
                and snapshot.origin_presence is E4bSnapshotPresence.NOT_APPLICABLE
            )
        return False
    except AttributeError:
        return False


def _valid_replay_snapshot(
    *,
    intent: E4bConsentIntent,
    request: E4bReplayReadRequest,
    snapshot: object,
) -> bool:
    if type(snapshot) is not E4bReplaySnapshot:
        return False
    try:
        if not _replay_snapshot_shape_is_consistent(snapshot):
            return False
        if not _replay_snapshot_matches_request(request=request, snapshot=snapshot):
            return False
        if snapshot.observation is E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT:
            return False
        if snapshot.operation_presence is E4bSnapshotPresence.PRESENT:
            if not _confirmed_operation_is_canonical(snapshot.existing_operation):
                return False
            if not _historical_payload_matches_replay_scope(
                snapshot.existing_operation,
                snapshot.existing_operation_identity,
                igreja_id=request.igreja_id,
                idempotency_key=request.idempotency_key,
            ):
                return False
            if _allowlisted_receipt(snapshot.existing_operation) is None:
                return False
            if not _complete_historical_operation_proof(
                snapshot.existing_operation_identity, snapshot.existing_operation
            ):
                return False
            if (
                snapshot.existing_operation.fingerprint == request.fingerprint
                and not _same_closed_replay_identity(
                    intent, snapshot.existing_operation
                )
            ):
                return False
        elif snapshot.operation_presence is not E4bSnapshotPresence.ABSENT:
            return False

        if snapshot.concession_presence is E4bSnapshotPresence.PRESENT:
            concession = snapshot.concession
            if (
                type(concession) is not E4bConcession
                or not _concession_is_canonical(concession)
                or concession.igreja_id != request.igreja_id
                or concession.titular_pessoa_id != request.titular_pessoa_id
                or concession.finalidade_id != request.finalidade_id
            ):
                return False
        if snapshot.origin_presence is E4bSnapshotPresence.PRESENT:
            origin = snapshot.origin_accept_operation
            if (
                not _confirmed_operation_is_canonical(origin)
                or not _historical_payload_matches_tenant(
                    origin,
                    snapshot.origin_accept_operation_identity,
                    igreja_id=request.igreja_id,
                )
                or _allowlisted_receipt(origin) is None
                or origin.operation_id != request.origin_accept_operation_id
                or not _complete_historical_operation_proof(
                    snapshot.origin_accept_operation_identity, origin
                )
            ):
                return False

        if snapshot.operation_presence is E4bSnapshotPresence.ABSENT:
            if snapshot.concession_presence not in (
                E4bSnapshotPresence.PRESENT,
                E4bSnapshotPresence.ABSENT,
            ):
                return False
            if request.action is E4bAction.ACCEPT:
                if snapshot.origin_presence is not E4bSnapshotPresence.NOT_APPLICABLE:
                    return False
            elif snapshot.origin_presence not in (
                E4bSnapshotPresence.PRESENT,
                E4bSnapshotPresence.ABSENT,
            ):
                return False

        return True
    except (AttributeError, TypeError, ValueError, E4bValidationError):
        return False


def _trusted_incomplete_replay_snapshot(
    *, request: E4bReplayReadRequest, snapshot: object
) -> bool:
    """Distingue cadeia observada incompleta de snapshot bruto ou indisponível."""

    if type(snapshot) is not E4bReplaySnapshot:
        return False
    try:
        if not _replay_snapshot_shape_is_consistent(snapshot):
            return False
        if not _replay_snapshot_matches_request(request=request, snapshot=snapshot):
            return False
        if snapshot.observation is E4bReplayObservation.INCOMPLETE_OR_INCONSISTENT:
            return (
                snapshot.operation_presence is E4bSnapshotPresence.NOT_APPLICABLE
                and snapshot.existing_operation is None
                and snapshot.concession_presence is E4bSnapshotPresence.NOT_APPLICABLE
                and snapshot.concession is None
                and snapshot.origin_presence is E4bSnapshotPresence.NOT_APPLICABLE
                and snapshot.origin_accept_operation is None
            )
        if snapshot.observation is not E4bReplayObservation.COMPLETE:
            return False
        if (
            snapshot.operation_presence is E4bSnapshotPresence.PRESENT
            and not _complete_historical_operation_proof(
                snapshot.existing_operation_identity, snapshot.existing_operation
            )
        ):
            return True
        return (
            snapshot.origin_presence is E4bSnapshotPresence.PRESENT
            and not _complete_historical_operation_proof(
                snapshot.origin_accept_operation_identity,
                snapshot.origin_accept_operation,
            )
        )
    except AttributeError:
        return False


_INCOMPLETE_HISTORICAL_CHAIN: Final[object] = object()


def _reconciliation_snapshot_shape_is_consistent(snapshot: object) -> bool:
    """Mantém ausência e incerteza disjuntas de qualquer identidade histórica."""

    if type(snapshot) is not E4bReconciliationSnapshot:
        return False
    try:
        if type(snapshot.observation) is not E4bReconciliationObservation:
            return False
        if snapshot.observation is E4bReconciliationObservation.CONFIRMED:
            return (
                type(snapshot.operation) is E4bConfirmedOperation
                and _confirmed_operation_is_canonical(snapshot.operation)
                and type(snapshot.historical_identity)
                is E4bHistoricalOperationIdentity
                and _historical_payload_matches_tenant(
                    snapshot.operation,
                    snapshot.historical_identity,
                    igreja_id=snapshot.igreja_id,
                )
            )
        if snapshot.observation in (
            E4bReconciliationObservation.NOT_FOUND,
            E4bReconciliationObservation.UNKNOWN,
            E4bReconciliationObservation.INCOMPLETE_OR_INCONSISTENT,
        ):
            return snapshot.operation is None and snapshot.historical_identity is None
        return False
    except AttributeError:
        return False


def _valid_reconciliation_snapshot(
    *, request: E4bReconciliationReadRequest, snapshot: object
) -> E4bReceipt | None | bool | object:
    """Retorna receipt, ``None`` para ausência/incerteza, ou ``False`` se inválido."""

    if type(snapshot) is not E4bReconciliationSnapshot:
        return False
    try:
        if not _reconciliation_snapshot_shape_is_consistent(snapshot):
            return False
        if (
            snapshot.igreja_id != request.igreja_id
            or snapshot.selector != request.selector
            or not _trusted_provenance(snapshot.provenance, igreja_id=request.igreja_id)
            or type(snapshot.observation) is not E4bReconciliationObservation
        ):
            return False
        if snapshot.observation is E4bReconciliationObservation.CONFIRMED:
            operation = snapshot.operation
            if (
                not _confirmed_operation_is_canonical(operation)
                or not _historical_payload_matches_tenant(
                    operation,
                    snapshot.historical_identity,
                    igreja_id=request.igreja_id,
                )
            ):
                return False
            receipt = _allowlisted_receipt(operation)
            if receipt is None:
                return False
            if not _complete_historical_operation_proof(
                snapshot.historical_identity, operation
            ):
                return _INCOMPLETE_HISTORICAL_CHAIN
            if type(request.selector) is E4bOperationSelector:
                if operation.operation_id != request.selector.operation_id:
                    return False
            elif operation.correlation_id != request.selector.correlation_id:
                return False
            return receipt
        if snapshot.operation is not None:
            return False
        return None
    except (AttributeError, TypeError, ValueError, E4bValidationError):
        return False


def _replay_request(intent: E4bConsentIntent) -> E4bReplayReadRequest:
    authority = intent.authority
    return E4bReplayReadRequest(
        igreja_id=authority.igreja_id,
        idempotency_key=intent.idempotency_key,
        fingerprint=intent.fingerprint,
        correlation_id=authority.correlation_id,
        action=intent.action,
        origin=authority.origin,
        titular_pessoa_id=authority.titular_pessoa_id,
        finalidade_id=authority.finalidade_id,
        origin_accept_operation_id=intent.origin_accept_operation_id,
    )


def replay_intent(
    *,
    intent: object,
    context: object,
    port: object,
) -> E4bReplayDecision | E4bBoundaryFailure:
    """Classifica replay E4b por uma única leitura de porta abstrata.

    Falhas de contexto, porta ou snapshot retornam ``E4bBoundaryFailure`` e
    nunca são convertidas em ``NEW``. Esta função não faz staging, retry ou
    qualquer escrita.
    """

    validated = _valid_replay_context(intent, context)
    if validated is None:
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.INVALID_CONTEXT
        )
    closed_intent, _ = validated
    precondition = _replay_precondition_decision(closed_intent)
    if precondition is not None:
        return precondition
    if not isinstance(port, E4bReplayReadPort):
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SOURCE_UNAVAILABLE
        )
    try:
        request = _replay_request(closed_intent)
        snapshot = port.read_replay_snapshot(request)
    except (AttributeError, TypeError, ValueError, E4bBoundaryValidationError):
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SOURCE_UNAVAILABLE
        )
    except Exception:
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SOURCE_UNAVAILABLE
        )
    if not _replay_snapshot_shape_is_consistent(snapshot):
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED
        )
    if _trusted_incomplete_replay_snapshot(request=request, snapshot=snapshot):
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.CHAIN_INCOMPLETE
        )
    if not _valid_replay_snapshot(
        intent=closed_intent, request=request, snapshot=snapshot
    ):
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED
        )
    try:
        classified = classify_e4b_intent(
            closed_intent,
            existing_operation=snapshot.existing_operation,
            concession=snapshot.concession,
            origin_accept_operation=snapshot.origin_accept_operation,
        )
    except (AttributeError, TypeError, ValueError, E4bValidationError):
        return _failure(
            E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED
        )
    if classified.classification is E4bClassification.ELIGIBLE:
        return E4bReplayDecision(outcome=E4bReplayOutcome.NEW)
    if classified.classification is E4bClassification.REPLAY:
        receipt = _allowlisted_receipt(classified.existing_operation)
        if receipt is None or classified.receipt != receipt:
            return _failure(
                E4bBoundaryOperation.REPLAY,
                E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
            )
        return E4bReplayDecision(
            outcome=E4bReplayOutcome.EXACT_REPLAY,
            receipt=receipt,
        )
    if classified.classification is E4bClassification.CONFLICT:
        return E4bReplayDecision(outcome=E4bReplayOutcome.CONFLICT)
    if classified.classification is E4bClassification.DENIED:
        if type(classified.reason) is not E4bDenialReason:
            return _failure(
                E4bBoundaryOperation.REPLAY,
                E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
            )
        return E4bReplayDecision(
            outcome=E4bReplayOutcome.DENIED,
            denial_reason=classified.reason,
        )
    return _failure(
        E4bBoundaryOperation.REPLAY, E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED
    )


def reconcile(
    *,
    context: object,
    selector: object,
    port: object,
) -> E4bReconciliationDecision | E4bBoundaryFailure:
    """Reconcilia por I ou C mediante uma única leitura E4b read-only.

    Somente uma ausência explicitamente atestada vira ``NOT_FOUND``. Porta ou
    snapshot indisponível retornam falha interna, sem fallback ou retry.
    """

    closed_context = _valid_read_context(context)
    if closed_context is None:
        return _failure(
            E4bBoundaryOperation.RECONCILE, E4bBoundaryFailureCode.INVALID_CONTEXT
        )
    try:
        closed_selector = _require_selector(selector, field_name="selector")
        request = E4bReconciliationReadRequest(
            igreja_id=closed_context.igreja_id,
            selector=closed_selector,
        )
    except (TypeError, ValueError, E4bBoundaryValidationError):
        return _failure(
            E4bBoundaryOperation.RECONCILE, E4bBoundaryFailureCode.INVALID_SELECTOR
        )
    if not isinstance(port, E4bReconciliationReadPort):
        return _failure(
            E4bBoundaryOperation.RECONCILE,
            E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
        )
    try:
        snapshot = port.read_reconciliation_snapshot(request)
    except (AttributeError, TypeError, ValueError, E4bBoundaryValidationError):
        return _failure(
            E4bBoundaryOperation.RECONCILE,
            E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
        )
    except Exception:
        return _failure(
            E4bBoundaryOperation.RECONCILE,
            E4bBoundaryFailureCode.SOURCE_UNAVAILABLE,
        )
    if not _reconciliation_snapshot_shape_is_consistent(snapshot):
        return _failure(
            E4bBoundaryOperation.RECONCILE,
            E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
    receipt = _valid_reconciliation_snapshot(request=request, snapshot=snapshot)
    if receipt is _INCOMPLETE_HISTORICAL_CHAIN:
        return E4bReconciliationDecision(outcome=E4bReconciliationOutcome.UNKNOWN)
    if receipt is False:
        return _failure(
            E4bBoundaryOperation.RECONCILE,
            E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
        )
    if snapshot.observation is E4bReconciliationObservation.CONFIRMED:
        return E4bReconciliationDecision(
            outcome=E4bReconciliationOutcome.CONFIRMED,
            receipt=receipt,
        )
    if snapshot.observation is E4bReconciliationObservation.NOT_FOUND:
        return E4bReconciliationDecision(
            outcome=E4bReconciliationOutcome.NOT_FOUND
        )
    if snapshot.observation in (
        E4bReconciliationObservation.UNKNOWN,
        E4bReconciliationObservation.INCOMPLETE_OR_INCONSISTENT,
    ):
        return E4bReconciliationDecision(outcome=E4bReconciliationOutcome.UNKNOWN)
    return _failure(
        E4bBoundaryOperation.RECONCILE,
        E4bBoundaryFailureCode.SNAPSHOT_UNTRUSTED,
    )

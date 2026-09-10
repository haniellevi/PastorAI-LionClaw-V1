"""Portas E4b C3 de staging PostgreSQL, sem caller ou ownership transacional.

Este módulo não abre sessão, não escolhe principal operacional, não muda GUC ou
role, e nunca confirma, reverte ou fecha a transação recebida. A única forma de
exercitar o DML nesta fase é o harness PG17 local e descartável definido pela
especificação congelada. A integração de um caller e de ACL operacional fica
explicitamente fora de C3.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Final

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.e4b_consent import (
    E4B_FINGERPRINT_VERSION,
    E4bAction,
    E4bAuthorityResolution,
    E4bConcessionState,
    E4bConsentIntent,
    E4bFingerprint,
    E4bManifestantRole,
    E4bOrigin,
    E4bReceipt,
    E4bRole,
    fingerprint_matches_intent,
)


_UTC: Final = dt.timezone.utc
_LOCK_TIMEOUT: Final = "5s"
_LOCK_SCOPE_KEY: Final = "e4b_consent_persistence_lock_scope_v1"
_SAFE_VERSION_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_LOCK_SEEDS: Final[dict[str, int]] = {
    "K": 2026091001,
    "L": 2026091002,
    "C": 2026091003,
    "stream": 2026091004,
}
_ROLE_LINK_ORDER: Final[tuple[E4bRole, ...]] = (
    E4bRole.TITULAR,
    E4bRole.MANIFESTANTE,
    E4bRole.RESPONSAVEL,
)


class E4bPersistenceErrorCode(str, Enum):
    """Falhas sanitizadas, sem transportar detalhes de banco ou de pessoa."""

    INVALID_INPUT = "INVALID_INPUT"
    TRANSACTION_REQUIRED = "TRANSACTION_REQUIRED"
    SESSION_SCOPE_INVALID = "SESSION_SCOPE_INVALID"
    LOCK_TIMEOUT_INVALID = "LOCK_TIMEOUT_INVALID"
    LOCK_SCOPE_INVALID = "LOCK_SCOPE_INVALID"
    DATA_INTEGRITY = "DATA_INTEGRITY"


class E4bPersistenceError(RuntimeError):
    """Erro que deixa a decisão de rollback exclusivamente ao owner externo."""

    def __init__(self, code: E4bPersistenceErrorCode) -> None:
        self.code = code
        super().__init__(f"e4b persistence rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


class E4bStagingOutcome(str, Enum):
    """Resultados internos de staging, distintos de confirmação de commit."""

    STAGED = "STAGED"
    EXACT_REPLAY = "EXACT_REPLAY"
    CONFLICT = "CONFLICT"
    DENIED = "DENIED"


class E4bHoldAction(str, Enum):
    """Únicas mutações futuras do metadado de hold E4b."""

    APPLY = "APPLY"
    RESOLVE = "RESOLVE"


@dataclass(frozen=True, slots=True)
class E4bConsentStageRequest:
    """Entrada fechada, já resolvida por serviços de domínio externos a C3."""

    operation_id: uuid.UUID
    receipt_id: uuid.UUID
    intent: E4bConsentIntent

    def __post_init__(self) -> None:
        _require_uuid(self.operation_id, "operation_id")
        _require_uuid(self.receipt_id, "receipt_id")
        if type(self.intent) is not E4bConsentIntent:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        _canonical_intent(self.intent)
        if (
            self.intent.action is E4bAction.ACCEPT
            and self.intent.origin_accept_operation_id is not None
        ) or (
            self.intent.action is E4bAction.WITHDRAW
            and self.intent.origin_accept_operation_id is None
        ):
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.intent.origin_accept_operation_id == self.operation_id:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)


@dataclass(frozen=True, slots=True)
class E4bConsentStagingResult:
    """Resultado não durável enquanto o owner externo não confirmar a transação."""

    outcome: E4bStagingOutcome
    operation_id: uuid.UUID | None
    receipt: E4bReceipt | None
    requires_owner_commit: bool = True

    def __post_init__(self) -> None:
        if type(self.outcome) is not E4bStagingOutcome:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.operation_id is not None:
            _require_uuid(self.operation_id, "operation_id")
        if self.receipt is not None and type(self.receipt) is not E4bReceipt:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if type(self.requires_owner_commit) is not bool or not self.requires_owner_commit:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.outcome in (E4bStagingOutcome.STAGED, E4bStagingOutcome.EXACT_REPLAY):
            if self.operation_id is None or self.receipt is None:
                _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        elif self.operation_id is not None or self.receipt is not None:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)


@dataclass(frozen=True, slots=True)
class E4bHoldAuthorityResolution:
    """Atestação tipada de autoridade humana já rederivada fora de C3."""

    igreja_id: uuid.UUID
    authority_app_user_id: uuid.UUID
    authority_resolution_version: str
    authority_resolution_sha256: bytes
    server_resolved: bool = True

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, "igreja_id")
        _require_uuid(self.authority_app_user_id, "authority_app_user_id")
        _require_version(self.authority_resolution_version, "authority_resolution_version")
        if type(self.authority_resolution_sha256) is not bytes or len(
            self.authority_resolution_sha256
        ) != 32:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if type(self.server_resolved) is not bool or not self.server_resolved:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)


@dataclass(frozen=True, slots=True)
class E4bHoldStageRequest:
    """Entrada fechada da porta de hold, sem DTO, caller ou capability nova."""

    action: E4bHoldAction
    igreja_id: uuid.UUID
    operation_id: uuid.UUID
    hold_id: uuid.UUID
    hold_event_id: uuid.UUID
    authority: E4bHoldAuthorityResolution
    policy_version: str

    def __post_init__(self) -> None:
        if type(self.action) is not E4bHoldAction:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        for field_name in (
            "igreja_id",
            "operation_id",
            "hold_id",
            "hold_event_id",
        ):
            _require_uuid(getattr(self, field_name), field_name)
        _require_version(self.policy_version, "policy_version")
        if type(self.authority) is not E4bHoldAuthorityResolution:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.authority.igreja_id != self.igreja_id:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)


@dataclass(frozen=True, slots=True)
class E4bHoldStagingResult:
    """Resultado de staging de hold, jamais confirmação ou autorização humana."""

    outcome: E4bStagingOutcome
    hold_id: uuid.UUID | None
    requires_owner_commit: bool = True

    def __post_init__(self) -> None:
        if type(self.outcome) is not E4bStagingOutcome:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.hold_id is not None:
            _require_uuid(self.hold_id, "hold_id")
        if type(self.requires_owner_commit) is not bool or not self.requires_owner_commit:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.outcome is E4bStagingOutcome.STAGED and self.hold_id is None:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        if self.outcome is not E4bStagingOutcome.STAGED and self.hold_id is not None:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)


class E4bConsentStagingPort(ABC):
    """Contrato de consentimento que toma uma transação externa já aberta."""

    @abstractmethod
    def stage_consent(
        self, request: E4bConsentStageRequest
    ) -> E4bConsentStagingResult:
        """Encena no máximo um flush e devolve controle ao owner da transação."""


class E4bConsentHoldStagingPort(ABC):
    """Contrato independente para aplicar ou resolver metadado de hold E4b."""

    @abstractmethod
    def stage_hold(self, request: E4bHoldStageRequest) -> E4bHoldStagingResult:
        """Encena no máximo um flush e devolve controle ao owner da transação."""


def _reject(code: E4bPersistenceErrorCode) -> None:
    raise E4bPersistenceError(code)


def _require_uuid(value: object, field_name: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    return value


def _require_version(value: object, field_name: str) -> str:
    if type(value) is not str or _SAFE_VERSION_RE.fullmatch(value) is None:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    return value


def _canonical_uuid(value: uuid.UUID) -> str:
    canonical = str(_require_uuid(value, "uuid"))
    if canonical != canonical.lower():
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    return canonical


def _canonical_utf8(value: object) -> str:
    if type(value) is not str or not value or value.startswith("\ufeff") or "\x00" in value:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    return value


def _canonical_intent(intent: E4bConsentIntent) -> E4bConsentIntent:
    """Reidrata valores fechados sem consultar ou interpretar material legado."""

    try:
        if intent.legacy_artifact is not None or intent.authority.legacy_artifact is not None:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        authority = intent.authority
        canonical_authority = E4bAuthorityResolution(
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
        )
        canonical = E4bConsentIntent(
            action=intent.action,
            idempotency_key=intent.idempotency_key,
            fingerprint=intent.fingerprint,
            authority=canonical_authority,
            origin_accept_operation_id=intent.origin_accept_operation_id,
        )
    except Exception:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    if canonical != intent or not canonical.authority.server_resolved or not canonical.authority.manifestant_relation_valid:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    if canonical.idempotency_key.igreja_id != canonical.authority.igreja_id:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    if not fingerprint_matches_intent(canonical):
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    if tuple(_role_links(canonical.authority)) != _expected_role_links(
        canonical.authority
    ):
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    _canonical_utf8(canonical.authority.finalidade_id)
    _canonical_utf8(canonical.idempotency_key.value)
    return canonical


def _canonical_hold_authority(
    authority: E4bHoldAuthorityResolution,
) -> E4bHoldAuthorityResolution:
    """Revalida a atestação já server-owned sem criar capability ou caller."""

    try:
        canonical = E4bHoldAuthorityResolution(
            igreja_id=authority.igreja_id,
            authority_app_user_id=authority.authority_app_user_id,
            authority_resolution_version=authority.authority_resolution_version,
            authority_resolution_sha256=authority.authority_resolution_sha256,
            server_resolved=authority.server_resolved,
        )
    except Exception:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    if canonical != authority or not canonical.server_resolved:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    return canonical


def add_24m_utc(value: dt.datetime) -> dt.datetime:
    """Aplica a fórmula civil UTC de 24 meses, sem depender de TimeZone local."""

    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    utc_value = value.astimezone(_UTC)
    target_year = utc_value.year + 2
    target_day = min(
        utc_value.day,
        calendar.monthrange(target_year, utc_value.month)[1],
    )
    return utc_value.replace(year=target_year, day=target_day)


def e4b_advisory_lock_texts(
    *,
    igreja_id: uuid.UUID,
    idempotency_key: str,
    titular_pessoa_id: uuid.UUID,
    correlation_id: uuid.UUID,
    finalidade_id: str,
) -> tuple[tuple[str, int], tuple[str, int], tuple[str, int], tuple[str, int]]:
    """Monta a sequência K, L, C e stream v1 sem normalização implícita."""

    tenant = _canonical_uuid(igreja_id)
    titular = _canonical_uuid(titular_pessoa_id)
    correlation = _canonical_uuid(correlation_id)
    key = _canonical_utf8(idempotency_key)
    purpose = _canonical_utf8(finalidade_id)
    if not key.startswith("e4b:consent-operation:v1:"):
        _reject(E4bPersistenceErrorCode.INVALID_INPUT)
    key_digest = hashlib.sha256(key.encode("utf-8", "strict")).hexdigest()
    return (
        (f"e4b:consent-operation:v1:{tenant}:{key_digest}", _LOCK_SEEDS["K"]),
        (f"purpose-consent-person-v1:{tenant}:{titular}", _LOCK_SEEDS["L"]),
        (f"e4b:consent-correlation:v1:{tenant}:{correlation}", _LOCK_SEEDS["C"]),
        (
            f"e4b:consent-stream:v1:{tenant}:{titular}:{purpose}",
            _LOCK_SEEDS["stream"],
        ),
    )


def _role_links(authority: E4bAuthorityResolution) -> list[str]:
    return [role.value for role in _ROLE_LINK_ORDER if role in authority.operator_role_links]


def _expected_role_links(authority: E4bAuthorityResolution) -> tuple[str, ...]:
    """Calcula o único histórico de papéis que a guarda SQL aceita."""

    role_ids = {
        E4bRole.TITULAR: authority.titular_pessoa_id,
        E4bRole.MANIFESTANTE: authority.manifestante_pessoa_id,
        E4bRole.RESPONSAVEL: authority.responsavel_pessoa_id,
    }
    return tuple(
        role.value
        for role in _ROLE_LINK_ORDER
        if role_ids[role] is not None and authority.operador_id == role_ids[role]
    )


def _as_utc(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)
    return value.astimezone(_UTC)


def _merged_pause_projection(
    holds: list[dict[str, object]],
) -> tuple[int, dt.datetime | None, dt.timedelta]:
    """Retorna contagem active, início aberto e duração finita da união."""

    intervals: list[tuple[dt.datetime, dt.datetime | None]] = []
    active_count = 0
    for hold in holds:
        state = hold["hold_state"]
        applied = _as_utc(hold["applied_at"])
        resolved_raw = hold["resolved_at"]
        if state == "ACTIVE":
            active_count += 1
            intervals.append((applied, None))
        elif state == "RESOLVED" and resolved_raw is not None:
            resolved = _as_utc(resolved_raw)
            if resolved < applied:
                _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)
            intervals.append((applied, resolved))
        else:
            _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)
    intervals.sort(key=lambda value: value[0])
    merged: list[list[dt.datetime | None]] = []
    for start, end in intervals:
        if not merged:
            merged.append([start, end])
            continue
        current = merged[-1]
        current_end = current[1]
        if current_end is None or start <= current_end:
            if end is None or (current_end is not None and end > current_end):
                current[1] = end
        else:
            merged.append([start, end])
    finite_pause = dt.timedelta()
    open_component: dt.datetime | None = None
    for start, end in merged:
        if end is None:
            open_component = start
        else:
            finite_pause += end - start
    return active_count, open_component, finite_pause


class PostgresE4bConsentStagingAdapter(
    E4bConsentStagingPort, E4bConsentHoldStagingPort
):
    """Adapter interno para uma Session já aberta pelo owner externo.

    A classe é deliberadamente sem factory de conexão e sem ponto de entrada de
    runtime. Seus métodos emitem DML apenas quando um harness local concedido
    explicitamente os exercita em PG17 descartável.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def stage_consent(self, request: E4bConsentStageRequest) -> E4bConsentStagingResult:
        if type(request) is not E4bConsentStageRequest:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        try:
            intent = _canonical_intent(request.intent)
            authority = intent.authority
            self._require_external_transaction()
            self._require_tenant_session(authority.igreja_id)
            self._acquire_consent_locks(intent)

            existing = self._operation_by_key(authority.igreja_id, intent.idempotency_key.value)
            if existing is not None:
                return self._classify_existing(request, intent, existing)
            if self._operation_by_correlation(authority.igreja_id, authority.correlation_id) is not None:
                return E4bConsentStagingResult(E4bStagingOutcome.CONFLICT, None, None)

            stream = self._stream_for_update(authority)
            if intent.action is E4bAction.ACCEPT:
                if stream is not None:
                    return E4bConsentStagingResult(E4bStagingOutcome.DENIED, None, None)
            else:
                if not self._withdrawal_origin_is_active(intent, stream):
                    return E4bConsentStagingResult(E4bStagingOutcome.DENIED, None, None)

            # Reconstituir antes do único clock evita aceitar dataclass adulterada.
            intent = _canonical_intent(intent)
            confirmed_at = self._clock_timestamp()
            receipt = self._receipt_for(request, intent, confirmed_at)
            self._insert_operation(request, intent, confirmed_at)
            if intent.action is E4bAction.ACCEPT:
                self._insert_active_stream(request, intent, confirmed_at)
            else:
                self._withdraw_stream(request, intent, confirmed_at)
            self._insert_receipt(receipt)
            self._insert_retention(
                igreja_id=intent.authority.igreja_id,
                operation_id=request.operation_id,
                confirmed_at=confirmed_at,
            )
            self._flush()
            return E4bConsentStagingResult(
                E4bStagingOutcome.STAGED, request.operation_id, receipt
            )
        except E4bPersistenceError:
            raise
        except SQLAlchemyError:
            _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)

    def stage_hold(self, request: E4bHoldStageRequest) -> E4bHoldStagingResult:
        if type(request) is not E4bHoldStageRequest:
            _reject(E4bPersistenceErrorCode.INVALID_INPUT)
        try:
            authority = _canonical_hold_authority(request.authority)
            if authority.igreja_id != request.igreja_id:
                _reject(E4bPersistenceErrorCode.INVALID_INPUT)
            self._require_external_transaction()
            self._require_tenant_session(request.igreja_id)
            operation = self._one_or_none(
                "select titular_pessoa_id from public.e4b_consent_operations "
                "where igreja_id=:igreja_id and operation_id=:operation_id",
                {"igreja_id": request.igreja_id, "operation_id": request.operation_id},
            )
            if operation is None:
                return E4bHoldStagingResult(E4bStagingOutcome.DENIED, None)
            titular = operation["titular_pessoa_id"]
            self._acquire_hold_lock(request.igreja_id, titular)
            retention = self._one_or_none(
                "select * from public.e4b_consent_retentions "
                "where igreja_id=:igreja_id and operation_id=:operation_id for update",
                {"igreja_id": request.igreja_id, "operation_id": request.operation_id},
            )
            if retention is None:
                return E4bHoldStagingResult(E4bStagingOutcome.DENIED, None)
            _canonical_hold_authority(authority)
            event_at = self._clock_timestamp()
            if request.action is E4bHoldAction.APPLY:
                if self._one_or_none(
                    "select hold_id from public.e4b_consent_holds "
                    "where igreja_id=:igreja_id and hold_id=:hold_id",
                    {"igreja_id": request.igreja_id, "hold_id": request.hold_id},
                ) is not None:
                    return E4bHoldStagingResult(E4bStagingOutcome.DENIED, None)
                self._insert_hold_applied(request, event_at)
            elif request.action is E4bHoldAction.RESOLVE:
                current = self._one_or_none(
                    "select hold_state from public.e4b_consent_holds "
                    "where igreja_id=:igreja_id and hold_id=:hold_id and operation_id=:operation_id",
                    {
                        "igreja_id": request.igreja_id,
                        "hold_id": request.hold_id,
                        "operation_id": request.operation_id,
                    },
                )
                if current is None or current["hold_state"] != "ACTIVE":
                    return E4bHoldStagingResult(E4bStagingOutcome.DENIED, None)
                self._resolve_hold(request, event_at)
            else:
                _reject(E4bPersistenceErrorCode.INVALID_INPUT)
            self._reproject_retention(request, retention, event_at)
            self._flush()
            return E4bHoldStagingResult(E4bStagingOutcome.STAGED, request.hold_id)
        except E4bPersistenceError:
            raise
        except SQLAlchemyError:
            _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)

    def _require_external_transaction(self) -> None:
        try:
            if not self._session.in_transaction() or self._session.get_transaction() is None:
                _reject(E4bPersistenceErrorCode.TRANSACTION_REQUIRED)
        except (AttributeError, TypeError, SQLAlchemyError):
            _reject(E4bPersistenceErrorCode.TRANSACTION_REQUIRED)

    def _require_tenant_session(self, igreja_id: uuid.UUID) -> None:
        row = self._one(
            "select current_setting('app.tenant_igreja_id', true) as tenant_guc, "
            "current_setting('lock_timeout', true) as lock_timeout, current_user as effective_role, "
            "(select rolbypassrls from pg_catalog.pg_roles where rolname = current_user) as bypass",
            {},
        )
        if (
            row["tenant_guc"] != _canonical_uuid(igreja_id)
            or row["bypass"] is not False
        ):
            _reject(E4bPersistenceErrorCode.SESSION_SCOPE_INVALID)
        if row["lock_timeout"] != _LOCK_TIMEOUT:
            _reject(E4bPersistenceErrorCode.LOCK_TIMEOUT_INVALID)

    def _acquire_consent_locks(self, intent: E4bConsentIntent) -> None:
        authority = intent.authority
        scope = (
            _canonical_uuid(authority.igreja_id),
            intent.idempotency_key.value,
            _canonical_uuid(authority.titular_pessoa_id),
            _canonical_uuid(authority.correlation_id),
            authority.finalidade_id,
        )
        self._record_lock_scope("consent", scope)
        for lock_text, seed in e4b_advisory_lock_texts(
            igreja_id=authority.igreja_id,
            idempotency_key=intent.idempotency_key.value,
            titular_pessoa_id=authority.titular_pessoa_id,
            correlation_id=authority.correlation_id,
            finalidade_id=authority.finalidade_id,
        ):
            self._acquire_lock(lock_text, seed)

    def _acquire_hold_lock(self, igreja_id: uuid.UUID, titular_pessoa_id: uuid.UUID) -> None:
        tenant = _canonical_uuid(igreja_id)
        titular = _canonical_uuid(titular_pessoa_id)
        self._record_lock_scope("hold", (tenant, titular))
        self._acquire_lock(
            f"purpose-consent-person-v1:{tenant}:{titular}", _LOCK_SEEDS["L"]
        )

    def _record_lock_scope(self, kind: str, scope: tuple[object, ...]) -> None:
        transaction = self._session.get_transaction()
        existing = self._session.info.get(_LOCK_SCOPE_KEY)
        if existing is not None and existing[0] is transaction:
            if existing[1] != kind or existing[2] != scope:
                _reject(E4bPersistenceErrorCode.LOCK_SCOPE_INVALID)
            return
        self._session.info[_LOCK_SCOPE_KEY] = (transaction, kind, scope)

    def _acquire_lock(self, lock_text: str, seed: int) -> None:
        self._session.execute(
            text(
                "select pg_catalog.pg_advisory_xact_lock("
                "pg_catalog.hashtextextended(:lock_text, :seed))"
            ),
            {"lock_text": lock_text, "seed": seed},
        ).scalar_one()

    def _operation_by_key(self, igreja_id: uuid.UUID, key: str):
        return self._one_or_none(
            "select * from public.e4b_consent_operations "
            "where igreja_id=:igreja_id and idempotency_key=:idempotency_key",
            {"igreja_id": igreja_id, "idempotency_key": key},
        )

    def _operation_by_correlation(self, igreja_id: uuid.UUID, correlation_id: uuid.UUID):
        return self._one_or_none(
            "select operation_id from public.e4b_consent_operations "
            "where igreja_id=:igreja_id and correlation_id=:correlation_id",
            {"igreja_id": igreja_id, "correlation_id": correlation_id},
        )

    def _stream_for_update(self, authority: E4bAuthorityResolution):
        return self._one_or_none(
            "select * from public.e4b_consent_streams where igreja_id=:igreja_id "
            "and titular_pessoa_id=:titular_pessoa_id and finalidade_id=:finalidade_id for update",
            {
                "igreja_id": authority.igreja_id,
                "titular_pessoa_id": authority.titular_pessoa_id,
                "finalidade_id": authority.finalidade_id,
            },
        )

    def _withdrawal_origin_is_active(self, intent: E4bConsentIntent, stream) -> bool:
        authority = intent.authority
        if stream is None or stream["stream_state"] != "ACTIVE":
            return False
        origin = self._one_or_none(
            "select * from public.e4b_consent_operations where igreja_id=:igreja_id "
            "and operation_id=:operation_id",
            {
                "igreja_id": authority.igreja_id,
                "operation_id": intent.origin_accept_operation_id,
            },
        )
        return bool(
            origin is not None
            and origin["action"] == "ACCEPT"
            and origin["concession_state"] == "ACTIVE"
            and origin["operation_state"] == "CONFIRMED"
            and origin["titular_pessoa_id"] == authority.titular_pessoa_id
            and origin["finalidade_id"] == authority.finalidade_id
            and stream["accept_operation_id"] == intent.origin_accept_operation_id
        )

    def _classify_existing(
        self, request: E4bConsentStageRequest, intent: E4bConsentIntent, row
    ) -> E4bConsentStagingResult:
        if not self._existing_matches(intent, row):
            return E4bConsentStagingResult(E4bStagingOutcome.CONFLICT, None, None)
        receipt_row = self._one_or_none(
            "select * from public.e4b_consent_receipts "
            "where igreja_id=:igreja_id and operation_id=:operation_id",
            {"igreja_id": intent.authority.igreja_id, "operation_id": row["operation_id"]},
        )
        if receipt_row is None:
            _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)
        return E4bConsentStagingResult(
            E4bStagingOutcome.EXACT_REPLAY,
            row["operation_id"],
            self._receipt_from_row(receipt_row),
        )

    def _existing_matches(self, intent: E4bConsentIntent, row) -> bool:
        authority = intent.authority
        expected = {
            "idempotency_key": intent.idempotency_key.value,
            "correlation_id": authority.correlation_id,
            "action": intent.action.value,
            "origin": E4bOrigin.E4B.value,
            "origin_accept_operation_id": intent.origin_accept_operation_id,
            "origin_action": "ACCEPT" if intent.action is E4bAction.WITHDRAW else None,
            "titular_pessoa_id": authority.titular_pessoa_id,
            "manifestante_pessoa_id": authority.manifestante_pessoa_id,
            "responsavel_pessoa_id": authority.responsavel_pessoa_id,
            "manifestant_role": authority.manifestant_role.value,
            "manifestant_relation_valid": True,
            "operator_id": authority.operador_id,
            "operator_kind": authority.operator_kind.value,
            "server_resolved": True,
            "finalidade_id": authority.finalidade_id,
            "contract_version": authority.contract_version,
            "policy_version": authority.policy_version,
            "term_version": authority.term_version,
            "content_digest": authority.content_digest,
            "fingerprint_version": E4B_FINGERPRINT_VERSION,
            "fingerprint": intent.fingerprint.value,
            "concession_state": (
                "ACTIVE" if intent.action is E4bAction.ACCEPT else "WITHDRAWN"
            ),
            "operation_state": "CONFIRMED",
        }
        if any(row.get(key) != value for key, value in expected.items()):
            return False
        return tuple(row.get("operator_role_links") or ()) == tuple(_role_links(authority))

    def _clock_timestamp(self) -> dt.datetime:
        value = self._session.execute(text("select pg_catalog.clock_timestamp()")).scalar_one()
        return _as_utc(value)

    def _receipt_for(
        self,
        request: E4bConsentStageRequest,
        intent: E4bConsentIntent,
        confirmed_at: dt.datetime,
    ) -> E4bReceipt:
        authority = intent.authority
        return E4bReceipt(
            operation_id=request.operation_id,
            correlation_id=authority.correlation_id,
            receipt_id=request.receipt_id,
            igreja_id=authority.igreja_id,
            action=intent.action,
            concession_state=(
                E4bConcessionState.ACTIVE
                if intent.action is E4bAction.ACCEPT
                else E4bConcessionState.WITHDRAWN
            ),
            origin=E4bOrigin.E4B,
            manifestant_role=authority.manifestant_role,
            confirmed_at=confirmed_at,
            contract_version=authority.contract_version,
            policy_version=authority.policy_version,
            term_version=authority.term_version,
            content_digest=authority.content_digest,
            fingerprint=intent.fingerprint,
        )

    def _insert_operation(
        self, request: E4bConsentStageRequest, intent: E4bConsentIntent, confirmed_at: dt.datetime
    ) -> None:
        authority = intent.authority
        self._session.execute(
            text(
                "insert into public.e4b_consent_operations "
                "(igreja_id, operation_id, idempotency_key, correlation_id, action, origin, "
                "origin_accept_operation_id, origin_action, titular_pessoa_id, "
                "manifestante_pessoa_id, responsavel_pessoa_id, manifestant_role, "
                "manifestant_relation_valid, operator_id, operator_kind, operator_role_links, "
                "server_resolved, finalidade_id, contract_version, policy_version, term_version, "
                "content_digest, fingerprint_version, fingerprint, concession_state, "
                "operation_state, confirmed_at) values "
                "(:igreja_id, :operation_id, :idempotency_key, :correlation_id, :action, 'E4B', "
                ":origin_accept_operation_id, :origin_action, :titular_pessoa_id, "
                ":manifestante_pessoa_id, :responsavel_pessoa_id, :manifestant_role, true, "
                ":operator_id, :operator_kind, :operator_role_links, true, :finalidade_id, "
                ":contract_version, :policy_version, :term_version, :content_digest, "
                ":fingerprint_version, :fingerprint, :concession_state, 'CONFIRMED', :confirmed_at)"
            ),
            {
                "igreja_id": authority.igreja_id,
                "operation_id": request.operation_id,
                "idempotency_key": intent.idempotency_key.value,
                "correlation_id": authority.correlation_id,
                "action": intent.action.value,
                "origin_accept_operation_id": intent.origin_accept_operation_id,
                "origin_action": "ACCEPT" if intent.action is E4bAction.WITHDRAW else None,
                "titular_pessoa_id": authority.titular_pessoa_id,
                "manifestante_pessoa_id": authority.manifestante_pessoa_id,
                "responsavel_pessoa_id": authority.responsavel_pessoa_id,
                "manifestant_role": authority.manifestant_role.value,
                "operator_id": authority.operador_id,
                "operator_kind": authority.operator_kind.value,
                "operator_role_links": _role_links(authority),
                "finalidade_id": authority.finalidade_id,
                "contract_version": authority.contract_version,
                "policy_version": authority.policy_version,
                "term_version": authority.term_version,
                "content_digest": authority.content_digest,
                "fingerprint_version": E4B_FINGERPRINT_VERSION,
                "fingerprint": intent.fingerprint.value,
                "concession_state": (
                    "ACTIVE" if intent.action is E4bAction.ACCEPT else "WITHDRAWN"
                ),
                "confirmed_at": confirmed_at,
            },
        )

    def _insert_active_stream(
        self, request: E4bConsentStageRequest, intent: E4bConsentIntent, confirmed_at: dt.datetime
    ) -> None:
        authority = intent.authority
        self._session.execute(
            text(
                "insert into public.e4b_consent_streams "
                "(igreja_id, titular_pessoa_id, finalidade_id, accept_operation_id, "
                "accept_action, stream_state, withdraw_operation_id, withdraw_action, state_changed_at) "
                "values (:igreja_id, :titular_pessoa_id, :finalidade_id, :operation_id, "
                "'ACCEPT', 'ACTIVE', null, null, :confirmed_at)"
            ),
            {
                "igreja_id": authority.igreja_id,
                "titular_pessoa_id": authority.titular_pessoa_id,
                "finalidade_id": authority.finalidade_id,
                "operation_id": request.operation_id,
                "confirmed_at": confirmed_at,
            },
        )

    def _withdraw_stream(
        self, request: E4bConsentStageRequest, intent: E4bConsentIntent, confirmed_at: dt.datetime
    ) -> None:
        authority = intent.authority
        result = self._session.execute(
            text(
                "update public.e4b_consent_streams set stream_state='WITHDRAWN', "
                "withdraw_operation_id=:operation_id, withdraw_action='WITHDRAW', "
                "state_changed_at=:confirmed_at where igreja_id=:igreja_id "
                "and titular_pessoa_id=:titular_pessoa_id and finalidade_id=:finalidade_id "
                "and accept_operation_id=:origin_accept_operation_id and stream_state='ACTIVE'"
            ),
            {
                "operation_id": request.operation_id,
                "confirmed_at": confirmed_at,
                "igreja_id": authority.igreja_id,
                "titular_pessoa_id": authority.titular_pessoa_id,
                "finalidade_id": authority.finalidade_id,
                "origin_accept_operation_id": intent.origin_accept_operation_id,
            },
        )
        if result.rowcount != 1:
            _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)

    def _insert_receipt(self, receipt: E4bReceipt) -> None:
        self._session.execute(
            text(
                "insert into public.e4b_consent_receipts "
                "(igreja_id, receipt_id, operation_id, correlation_id, action, origin, "
                "manifestant_role, concession_state, confirmed_at, contract_version, "
                "policy_version, term_version, content_digest, fingerprint_version, fingerprint) "
                "values (:igreja_id, :receipt_id, :operation_id, :correlation_id, :action, 'E4B', "
                ":manifestant_role, :concession_state, :confirmed_at, :contract_version, "
                ":policy_version, :term_version, :content_digest, :fingerprint_version, :fingerprint)"
            ),
            {
                "igreja_id": receipt.igreja_id,
                "receipt_id": receipt.receipt_id,
                "operation_id": receipt.operation_id,
                "correlation_id": receipt.correlation_id,
                "action": receipt.action.value,
                "manifestant_role": receipt.manifestant_role.value,
                "concession_state": receipt.concession_state.value,
                "confirmed_at": receipt.confirmed_at,
                "contract_version": receipt.contract_version,
                "policy_version": receipt.policy_version,
                "term_version": receipt.term_version,
                "content_digest": receipt.content_digest,
                "fingerprint_version": E4B_FINGERPRINT_VERSION,
                "fingerprint": receipt.fingerprint.value,
            },
        )

    def _insert_retention(
        self, *, igreja_id: uuid.UUID, operation_id: uuid.UUID, confirmed_at: dt.datetime
    ) -> None:
        self._session.execute(
            text(
                "insert into public.e4b_consent_retentions "
                "(igreja_id, operation_id, retention_state, retention_anchor_at, "
                "retention_due_at, active_hold_count, suspension_started_at, "
                "last_hold_event_at, state_changed_at) values "
                "(:igreja_id, :operation_id, 'RETENTION_RUNNING', :confirmed_at, "
                ":retention_due_at, 0, null, null, :confirmed_at)"
            ),
            {
                "igreja_id": igreja_id,
                "operation_id": operation_id,
                "confirmed_at": confirmed_at,
                "retention_due_at": add_24m_utc(confirmed_at),
            },
        )

    def _insert_hold_applied(self, request: E4bHoldStageRequest, event_at: dt.datetime) -> None:
        self._session.execute(
            text(
                "insert into public.e4b_consent_holds "
                "(igreja_id, hold_id, operation_id, hold_state, policy_version, applied_at, resolved_at) "
                "values (:igreja_id, :hold_id, :operation_id, 'ACTIVE', :policy_version, :event_at, null)"
            ),
            {
                "igreja_id": request.igreja_id, "hold_id": request.hold_id,
                "operation_id": request.operation_id, "policy_version": request.policy_version,
                "event_at": event_at,
            },
        )
        self._insert_hold_event(request, "HOLD_APPLIED", 1, event_at)

    def _resolve_hold(self, request: E4bHoldStageRequest, event_at: dt.datetime) -> None:
        result = self._session.execute(
            text(
                "update public.e4b_consent_holds set hold_state='RESOLVED', resolved_at=:event_at "
                "where igreja_id=:igreja_id and hold_id=:hold_id and operation_id=:operation_id "
                "and hold_state='ACTIVE'"
            ),
            {
                "igreja_id": request.igreja_id, "hold_id": request.hold_id,
                "operation_id": request.operation_id, "event_at": event_at,
            },
        )
        if result.rowcount != 1:
            _reject(E4bPersistenceErrorCode.DATA_INTEGRITY)
        self._insert_hold_event(request, "HOLD_RESOLVED", 2, event_at)

    def _insert_hold_event(
        self, request: E4bHoldStageRequest, event_kind: str, event_sequence: int, event_at: dt.datetime
    ) -> None:
        self._session.execute(
            text(
                "insert into public.e4b_consent_hold_events "
                "(igreja_id, hold_event_id, hold_id, operation_id, event_kind, event_sequence, "
                "authority_app_user_id, authority_resolution_version, authority_resolution_sha256, "
                "policy_version, occurred_at) values "
                "(:igreja_id, :hold_event_id, :hold_id, :operation_id, :event_kind, :event_sequence, "
                ":authority_app_user_id, :authority_resolution_version, :authority_resolution_sha256, "
                ":policy_version, :event_at)"
            ),
            {
                "igreja_id": request.igreja_id,
                "hold_event_id": request.hold_event_id,
                "hold_id": request.hold_id,
                "operation_id": request.operation_id,
                "event_kind": event_kind,
                "event_sequence": event_sequence,
                "authority_app_user_id": request.authority.authority_app_user_id,
                "authority_resolution_version": request.authority.authority_resolution_version,
                "authority_resolution_sha256": request.authority.authority_resolution_sha256,
                "policy_version": request.policy_version,
                "event_at": event_at,
            },
        )

    def _reproject_retention(self, request: E4bHoldStageRequest, retention, event_at: dt.datetime) -> None:
        holds = [dict(row) for row in self._session.execute(
            text(
                "select hold_state, applied_at, resolved_at from public.e4b_consent_holds "
                "where igreja_id=:igreja_id and operation_id=:operation_id"
            ),
            {"igreja_id": request.igreja_id, "operation_id": request.operation_id},
        ).mappings().all()]
        events = [row[0] for row in self._session.execute(
            text(
                "select occurred_at from public.e4b_consent_hold_events "
                "where igreja_id=:igreja_id and operation_id=:operation_id"
            ),
            {"igreja_id": request.igreja_id, "operation_id": request.operation_id},
        ).all()]
        active_count, open_component, finite_pause = _merged_pause_projection(holds)
        anchor = _as_utc(retention["retention_anchor_at"])
        state = "RETENTION_HELD" if active_count else "RETENTION_RUNNING"
        self._session.execute(
            text(
                "update public.e4b_consent_retentions set retention_state=:retention_state, "
                "retention_due_at=:retention_due_at, active_hold_count=:active_hold_count, "
                "suspension_started_at=:suspension_started_at, last_hold_event_at=:last_hold_event_at, "
                "state_changed_at=:state_changed_at where igreja_id=:igreja_id and operation_id=:operation_id"
            ),
            {
                "retention_state": state,
                "retention_due_at": add_24m_utc(anchor) + finite_pause,
                "active_hold_count": active_count,
                "suspension_started_at": open_component,
                "last_hold_event_at": max(events) if events else None,
                "state_changed_at": event_at,
                "igreja_id": request.igreja_id,
                "operation_id": request.operation_id,
            },
        )

    def _receipt_from_row(self, row) -> E4bReceipt:
        return E4bReceipt(
            operation_id=row["operation_id"], correlation_id=row["correlation_id"],
            receipt_id=row["receipt_id"], igreja_id=row["igreja_id"],
            action=E4bAction(row["action"]),
            concession_state=E4bConcessionState(row["concession_state"]),
            origin=E4bOrigin(row["origin"]),
            manifestant_role=E4bManifestantRole(row["manifestant_role"]),
            confirmed_at=row["confirmed_at"], contract_version=row["contract_version"],
            policy_version=row["policy_version"], term_version=row["term_version"],
            content_digest=row["content_digest"], fingerprint=E4bFingerprint(row["fingerprint"]),
        )

    def _one_or_none(self, sql: str, parameters: dict[str, object]):
        return self._session.execute(text(sql), parameters).mappings().one_or_none()

    def _one(self, sql: str, parameters: dict[str, object]):
        return self._session.execute(text(sql), parameters).mappings().one()

    def _flush(self) -> None:
        self._session.flush()


__all__ = (
    "E4bConsentHoldStagingPort",
    "E4bConsentStageRequest",
    "E4bConsentStagingPort",
    "E4bConsentStagingResult",
    "E4bHoldAction",
    "E4bHoldAuthorityResolution",
    "E4bHoldStageRequest",
    "E4bHoldStagingResult",
    "E4bPersistenceError",
    "E4bPersistenceErrorCode",
    "E4bStagingOutcome",
    "PostgresE4bConsentStagingAdapter",
    "add_24m_utc",
    "e4b_advisory_lock_texts",
)

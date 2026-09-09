"""Offline consent evidence-store unit of work.

The service is intentionally an internal, transaction-borrowing boundary.  A
caller supplies a store backed by an already-open SQLAlchemy transaction (or a
synthetic memory fake in unit tests).  The service only validates, locks,
stages rows and flushes.  It never calls ``begin``, ``commit`` or ``rollback``
and it never imports a provider, runtime, vault or feature flag.

The SQL adapter is deliberately not implemented here.  ``ConsentEvidenceStoreProtocol``
is the seam for the migration/ORM work:

* ``lock_idempotency_key``
* ``lock_ledger_stream``
* ``lock_challenge``
* ``get_*`` reads, including ``get_ledger_state``
* ``insert_challenge``, ``insert_evidence``, ``insert_receipt``
* ``transition_challenge`` and ``flush``

The lock order is part of the contract and must remain exactly
tenant-key -> challenge read/create/lock -> ledger stream.  The service does
not write the existing purpose-consent ledger; E4 will review that integration
separately.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from app.db.rls_observability import require_tenant_scope
from app.domain.consent_evidence_store import (
    DEFAULT_CONSENT_EVIDENCE_SOURCE,
    ConsentChallenge,
    ConsentChallengeState,
    ConsentEvidenceAction,
    ConsentEvidenceLedgerState,
    ConsentEvidenceRecord,
    ConsentEvidenceRequest,
    ConsentEvidenceSchemaVersion,
    ConsentEvidenceSource,
    ConsentEvidenceSourceError,
    ConsentEvidenceType,
    ConsentEvidenceValidationError,
    ConsentReceipt,
    OpaqueConsentEvidenceIdempotencyKey,
    TrustedConsentEvidenceAuthority,
    build_evidence,
    compare_evidence_intent,
    compare_challenges,
    evidence_matches_digest,
    require_utc,
    validate_source_binding,
)


Clock = Callable[[], dt.datetime]


class ConsentEvidenceUnitOfWorkErrorCode(str, Enum):
    """Sanitized, stable rejection categories."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TRANSACTION_REQUIRED = "TRANSACTION_REQUIRED"
    TENANT_SCOPE_REQUIRED = "TENANT_SCOPE_REQUIRED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_INVALID = "SOURCE_INVALID"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    PERSON_NOT_FOUND = "PERSON_NOT_FOUND"
    CHALLENGE_NOT_FOUND = "CHALLENGE_NOT_FOUND"
    CHALLENGE_CONFLICT = "CHALLENGE_CONFLICT"
    CHALLENGE_EXPIRED = "CHALLENGE_EXPIRED"
    IDEMPOTENCY_REPLAY = "IDEMPOTENCY_REPLAY"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    LEDGER_CONFLICT = "LEDGER_CONFLICT"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    UNKNOWN = "UNKNOWN"


class ConsentEvidenceUnitOfWorkError(RuntimeError):
    """A sanitized UoW error that never exposes driver/source details."""

    def __init__(self, code: ConsentEvidenceUnitOfWorkErrorCode) -> None:
        self.code = code
        super().__init__(f"consent evidence operation rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


# Named aliases make the seam discoverable without proliferating error text.
ConsentEvidenceTransactionRequiredError = ConsentEvidenceUnitOfWorkError
ConsentEvidenceSourceUnavailableError = ConsentEvidenceUnitOfWorkError
ConsentEvidenceIdempotencyConflictError = ConsentEvidenceUnitOfWorkError
ConsentEvidenceChallengeExpiredError = ConsentEvidenceUnitOfWorkError


class ConsentEvidenceReconciliationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True, repr=False)
class ConsentEvidenceOperationResult:
    """Rows staged in the caller transaction.

    ``requires_caller_commit`` stays true even for a replay because a replay
    can observe writes staged in the current transaction.  ``delivery_claimed``
    is permanently false: delivery is outside the evidence-store contract.
    """

    challenge: ConsentChallenge = field(repr=False)
    presentation: ConsentEvidenceRecord = field(repr=False)
    manifestation: ConsentEvidenceRecord | None = field(repr=False)
    receipt: ConsentReceipt | None = field(repr=False)
    replayed: bool
    requires_caller_commit: bool = field(default=True, init=False)
    delivery_claimed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.challenge) is not ConsentChallenge:
            raise ConsentEvidenceValidationError("resultado exige desafio fechado")
        if type(self.presentation) is not ConsentEvidenceRecord:
            raise ConsentEvidenceValidationError("resultado exige apresentação fechada")
        if type(self.replayed) is not bool:
            raise ConsentEvidenceValidationError("replayed deve ser booleano estrito")
        if (
            self.presentation.igreja_id != self.challenge.igreja_id
            or self.presentation.desafio_id != self.challenge.id
            or self.presentation.tipo is not ConsentEvidenceType.PRESENTATION
            or not evidence_matches_digest(self.presentation, self.challenge)
        ):
            raise ConsentEvidenceValidationError("apresentação inconsistente")
        if self.manifestation is None:
            if self.receipt is not None:
                raise ConsentEvidenceValidationError("recibo sem manifestação")
            return
        if type(self.manifestation) is not ConsentEvidenceRecord:
            raise ConsentEvidenceValidationError("manifestação fechada obrigatória")
        if type(self.receipt) is not ConsentReceipt:
            raise ConsentEvidenceValidationError("manifestação exige recibo")
        if (
            self.challenge.estado is not ConsentChallengeState.CONSUMED
            or self.manifestation.igreja_id != self.challenge.igreja_id
            or self.manifestation.desafio_id != self.challenge.id
            or self.manifestation.tipo is not ConsentEvidenceType.MANIFESTATION
            or not evidence_matches_digest(self.manifestation, self.challenge)
            or self.manifestation.apresentacao_id != self.presentation.id
            or self.manifestation.acao is not ConsentEvidenceAction.REFUSE_INITIAL
            or self.receipt.igreja_id != self.challenge.igreja_id
            or self.receipt.evidencia_id != self.manifestation.id
            or self.receipt.chave_idempotencia
            != self.manifestation.chave_idempotencia
            or self.receipt.acao is not ConsentEvidenceAction.REFUSE_INITIAL
            or self.receipt.registrado_em != self.manifestation.registrado_em
            or self.receipt.schema_version
            is not ConsentEvidenceSchemaVersion.RECEIPT_LAB_V1
        ):
            raise ConsentEvidenceValidationError("manifestação/recibo inconsistentes")

    def __repr__(self) -> str:
        return (
            "ConsentEvidenceOperationResult("
            f"replayed={self.replayed!r}, "
            f"requires_caller_commit={self.requires_caller_commit!r}, "
            f"delivery_claimed={self.delivery_claimed!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ConsentEvidenceReconciliationResult:
    status: ConsentEvidenceReconciliationStatus
    operation: ConsentEvidenceOperationResult | None = field(
        default=None, repr=False
    )
    delivery_claimed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.status) is not ConsentEvidenceReconciliationStatus:
            raise ConsentEvidenceValidationError("status de reconciliação inválido")
        if self.status is ConsentEvidenceReconciliationStatus.CONFIRMED:
            if type(self.operation) is not ConsentEvidenceOperationResult:
                raise ConsentEvidenceValidationError("confirmação exige operação")
        elif self.operation is not None:
            raise ConsentEvidenceValidationError("operação só existe em confirmação")

    def __repr__(self) -> str:
        return f"ConsentEvidenceReconciliationResult(status={self.status.value!r})"


@runtime_checkable
class ConsentEvidenceStoreProtocol(Protocol):
    """Storage/UoW seam implemented by an SQLAlchemy adapter or memory fake.

    The adapter owns the external transaction.  All IDs are passed as typed
    UUID/value objects and all returned rows must be the closed domain DTOs;
    this service does not coerce arbitrary ORM dictionaries into authority.
    """

    def transaction_active(self) -> bool:
        """Return whether the caller's transaction is already active."""

    def require_readonly_observation(self) -> None:
        """Prove this is an independent read-only observation transaction.

        The adapter must not begin or end that transaction here.  It should
        reject a store that is the staging transaction, and verify its own
        transaction identity/read-only posture before any reconciliation read.
        """

    def require_tenant_scope(self, igreja_id: uuid.UUID) -> None:
        """Require authenticated role + exact app.tenant_igreja_id GUC."""

    def lock_idempotency_key(
        self,
        igreja_id: uuid.UUID,
        chave_idempotencia: OpaqueConsentEvidenceIdempotencyKey,
    ) -> None:
        ...

    def lock_challenge(self, igreja_id: uuid.UUID, desafio_id: uuid.UUID) -> None:
        ...

    def lock_ledger_stream(
        self,
        igreja_id: uuid.UUID,
        pessoa_id: uuid.UUID,
        finalidade: object,
    ) -> None:
        """Use the same transaction advisory key as the ledger trigger."""

    def get_challenge(
        self, igreja_id: uuid.UUID, desafio_id: uuid.UUID
    ) -> ConsentChallenge | None:
        ...

    def get_challenge_by_binding_interaction(
        self,
        igreja_id: uuid.UUID,
        binding_id: uuid.UUID,
        interaction_id: uuid.UUID,
    ) -> ConsentChallenge | None:
        ...

    def get_evidence_by_idempotency(
        self,
        igreja_id: uuid.UUID,
        chave_idempotencia: OpaqueConsentEvidenceIdempotencyKey,
    ) -> ConsentEvidenceRecord | None:
        ...

    def get_evidence_by_challenge_type(
        self,
        igreja_id: uuid.UUID,
        desafio_id: uuid.UUID,
        tipo: ConsentEvidenceType,
    ) -> ConsentEvidenceRecord | None:
        ...

    def get_receipt_by_evidence(
        self, igreja_id: uuid.UUID, evidencia_id: uuid.UUID
    ) -> ConsentReceipt | None:
        ...

    def get_ledger_state(
        self, igreja_id: uuid.UUID, pessoa_id: uuid.UUID, finalidade: object
    ) -> tuple[ConsentEvidenceLedgerState, uuid.UUID | None]:
        """Read the existing purpose stream under the stream advisory lock."""

    def insert_challenge(self, challenge: ConsentChallenge) -> bool:
        """Insert once; return false when a concurrent winner exists."""
        ...

    def insert_evidence(self, evidence: ConsentEvidenceRecord) -> None:
        ...

    def insert_receipt(self, receipt: ConsentReceipt) -> None:
        ...

    def transition_challenge(
        self,
        igreja_id: uuid.UUID,
        desafio_id: uuid.UUID,
        state: ConsentChallengeState,
        ended_at: dt.datetime,
    ) -> None:
        ...

    def flush(self) -> None:
        ...


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _fail(code: ConsentEvidenceUnitOfWorkErrorCode) -> None:
    raise ConsentEvidenceUnitOfWorkError(code)


def _require_request(request: object) -> ConsentEvidenceRequest:
    if type(request) is not ConsentEvidenceRequest:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.INVALID_ARGUMENT)
    return request


def _require_clock(clock: Callable[[], dt.datetime]) -> dt.datetime:
    if not callable(clock):
        _fail(ConsentEvidenceUnitOfWorkErrorCode.INVALID_ARGUMENT)
    try:
        value = clock()
    except Exception:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.UNKNOWN)
    try:
        return require_utc(value, field="clock")
    except ConsentEvidenceValidationError:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.INVALID_ARGUMENT)


def _store_call(
    store: ConsentEvidenceStoreProtocol,
    method_name: str,
    *args: object,
    code: ConsentEvidenceUnitOfWorkErrorCode = ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY,
) -> Any:
    method = getattr(store, method_name, None)
    if not callable(method):
        _fail(code)
    try:
        return method(*args)
    except ConsentEvidenceUnitOfWorkError:
        raise
    except Exception:
        # Driver and adapter details are deliberately not exposed.
        _fail(code)


def _require_external_transaction(store: object) -> None:
    method = getattr(store, "transaction_active", None)
    if not callable(method):
        # Supporting a raw SQLAlchemy Session is useful for adapters while
        # preserving the same fail-closed requirement.
        method = getattr(store, "in_transaction", None)
    if not callable(method):
        _fail(ConsentEvidenceUnitOfWorkErrorCode.TRANSACTION_REQUIRED)
    try:
        active = method()
    except Exception:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.TRANSACTION_REQUIRED)
    if type(active) is not bool or not active:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.TRANSACTION_REQUIRED)


def _require_tenant_scope(store: object, tenant_id: uuid.UUID) -> None:
    method = getattr(store, "require_tenant_scope", None)
    if callable(method):
        try:
            result = method(tenant_id)
            if result is not None:
                _fail(ConsentEvidenceUnitOfWorkErrorCode.TENANT_SCOPE_REQUIRED)
        except ConsentEvidenceUnitOfWorkError:
            raise
        except Exception:
            _fail(ConsentEvidenceUnitOfWorkErrorCode.TENANT_SCOPE_REQUIRED)
        return
    # A thin SQLAlchemy wrapper may expose its session as ``session``.  Reuse
    # the project's strict role + GUC barrier; no correction SET is performed.
    session = getattr(store, "session", None)
    if session is None:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.TENANT_SCOPE_REQUIRED)
    try:
        require_tenant_scope(
            session,
            expected_igreja_id=tenant_id,
            source="consent_evidence_store",
        )
    except Exception:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.TENANT_SCOPE_REQUIRED)


def _require_read_only_observation(store: object) -> None:
    method = getattr(store, "require_readonly_observation", None)
    if not callable(method):
        # Kept as a test-only compatibility spelling; the SQL adapter uses the
        # compact method name above.
        method = getattr(store, "require_read_only_observation", None)
    if not callable(method):
        _fail(ConsentEvidenceUnitOfWorkErrorCode.TRANSACTION_REQUIRED)
    try:
        result = method()
        if result is not None:
            _fail(ConsentEvidenceUnitOfWorkErrorCode.UNKNOWN)
    except ConsentEvidenceUnitOfWorkError:
        raise
    except Exception:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.UNKNOWN)


def _source_call(
    source: ConsentEvidenceSource,
    method_name: str,
    *args: object,
    now: dt.datetime,
) -> TrustedConsentEvidenceAuthority:
    method = getattr(source, method_name, None)
    if not callable(method) or isinstance(source, bool):
        _fail(ConsentEvidenceUnitOfWorkErrorCode.SOURCE_UNAVAILABLE)
    try:
        value = method(*args, now=now)
    except ConsentEvidenceUnitOfWorkError:
        raise
    except ConsentEvidenceSourceError:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.SOURCE_UNAVAILABLE)
    except Exception:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.SOURCE_INVALID)
    if type(value) is not TrustedConsentEvidenceAuthority:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.SOURCE_INVALID)
    return value


def _validate_authority(
    request: ConsentEvidenceRequest,
    authority: TrustedConsentEvidenceAuthority,
) -> None:
    try:
        validate_source_binding(request, authority)
    except ConsentEvidenceValidationError:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.SOURCE_INVALID)


def _require_allowed_action(request: ConsentEvidenceRequest, *, presentation: bool) -> None:
    action = request.acao
    if presentation:
        if action is not None:
            _fail(ConsentEvidenceUnitOfWorkErrorCode.INVALID_ARGUMENT)
        return
    if action is ConsentEvidenceAction.REFUSE_INITIAL:
        return
    # This branch runs before transaction/scope/source I/O.  ACCEPT and
    # WITHDRAW are known parser values but remain blocked until E4.
    if action in (ConsentEvidenceAction.ACCEPT, ConsentEvidenceAction.WITHDRAW):
        _fail(ConsentEvidenceUnitOfWorkErrorCode.ACTION_BLOCKED)
    _fail(ConsentEvidenceUnitOfWorkErrorCode.INVALID_ARGUMENT)


def _ensure_not_expired(
    challenge: ConsentChallenge, *, now: dt.datetime
) -> None:
    if now >= challenge.expira_em:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_EXPIRED)


def _same_ledger(
    expected: TrustedConsentEvidenceAuthority,
    actual: tuple[ConsentEvidenceLedgerState, uuid.UUID | None],
    *,
    require_absent: bool,
) -> None:
    if type(actual) is not tuple or len(actual) != 2:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
    state, event_id = actual
    if state is not expected.prior_ledger_state or event_id != expected.prior_event_id:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.LEDGER_CONFLICT)
    if require_absent and state is not ConsentEvidenceLedgerState.ABSENT:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.LEDGER_CONFLICT)


def _check_challenge_row(
    requested: ConsentChallenge,
    persisted: ConsentChallenge | None,
) -> ConsentChallenge:
    # This helper is only used after the service observed a row and locked it.
    # A vanished row is not a new-challenge case: never reinsert after the
    # challenge lock or after the ledger-stream serialization point.
    if persisted is None:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_NOT_FOUND)
    if type(persisted) is not ConsentChallenge or not compare_challenges(
        persisted, requested
    ):
        _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
    return persisted


def _new_evidence_id() -> uuid.UUID:
    return uuid.uuid4()


def _new_challenge_state(
    challenge: ConsentChallenge,
    *,
    state: ConsentChallengeState,
    ended_at: dt.datetime,
) -> ConsentChallenge:
    try:
        return challenge.with_state(state, ended_at)
    except ConsentEvidenceValidationError:
        _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)


class ConsentEvidenceUnitOfWork:
    """Borrow one caller transaction for evidence-store staging."""

    def __init__(
        self,
        store: ConsentEvidenceStoreProtocol,
        *,
        source: ConsentEvidenceSource | None = None,
        clock: Callable[[], dt.datetime] = utc_now,
    ) -> None:
        self._store = store
        self._source: ConsentEvidenceSource = (
            DEFAULT_CONSENT_EVIDENCE_SOURCE if source is None else source
        )
        self._clock = clock

    @property
    def store(self) -> ConsentEvidenceStoreProtocol:
        return self._store

    def _preflight(
        self,
        request: ConsentEvidenceRequest,
        *,
        presentation: bool,
    ) -> tuple[ConsentChallenge, TrustedConsentEvidenceAuthority, dt.datetime]:
        # Validate action before even checking transaction/scope.  This is the
        # explicit pre-I/O gate for ACCEPT/WITHDRAW.
        _require_allowed_action(request, presentation=presentation)
        _require_external_transaction(self._store)
        challenge = request.desafio
        _require_tenant_scope(self._store, challenge.igreja_id)
        pre_lock_now = _require_clock(self._clock)
        authority = _source_call(
            self._source,
            "resolve",
            request,
            now=pre_lock_now,
        )
        _validate_authority(request, authority)
        return challenge, authority, pre_lock_now

    def _lock_and_revalidate(
        self,
        request: ConsentEvidenceRequest,
        authority: TrustedConsentEvidenceAuthority,
        pre_lock_now: dt.datetime,
        *,
        require_ledger_absent: bool,
        allow_expired_replay: bool = False,
    ) -> tuple[ConsentChallenge, TrustedConsentEvidenceAuthority, dt.datetime]:
        challenge = request.desafio
        # Fixed order: tenant idempotency key -> challenge read/create/lock ->
        # ledger stream.  New challenge INSERT intentionally precedes the
        # stream lock so the composite Pessoa FK protects the subject without
        # requiring a Pessoa row lock or extra runtime privilege.
        _store_call(
            self._store,
            "lock_idempotency_key",
            challenge.igreja_id,
            request.chave_idempotencia,
        )

        existing_before_lock = _store_call(
            self._store,
            "get_challenge",
            challenge.igreja_id,
            challenge.id,
        )
        inserted_new = False
        if existing_before_lock is None:
            # The binding is also unique in the storage contract.  Check it
            # before attempting a new insert so a concurrent/different
            # challenge identity is rejected without ever being adopted.
            existing_binding = _store_call(
                self._store,
                "get_challenge_by_binding_interaction",
                challenge.igreja_id,
                challenge.binding_id,
                challenge.interaction_id,
            )
            if existing_binding is not None:
                if type(existing_binding) is not ConsentChallenge:
                    _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
                if (
                    existing_binding.id != challenge.id
                    or not compare_challenges(existing_binding, challenge)
                ):
                    _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
                # The binding lookup found the same identity; use the normal
                # existing-row lock/reread branch below.
                existing_before_lock = existing_binding
            else:
                if challenge.estado is not ConsentChallengeState.OPEN:
                    _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
                # An unpersisted challenge must not be staged once its
                # technical lifetime has already elapsed. Existing exact
                # replays are handled after their challenge lock and may be
                # recovered after expiry without creating another row.
                _ensure_not_expired(challenge, now=pre_lock_now)
                inserted = _store_call(
                    self._store,
                    "insert_challenge",
                    challenge,
                )
                if type(inserted) is not bool:
                    _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
                if inserted:
                    inserted_new = True
                else:
                    # ON CONFLICT DO NOTHING can report a winner for either
                    # the challenge identity or the unique binding. Resolve
                    # both rows before the stream lock. Never substitute a
                    # challenge with another ID.
                    winner_by_id = _store_call(
                        self._store,
                        "get_challenge",
                        challenge.igreja_id,
                        challenge.id,
                    )
                    winner_by_binding = _store_call(
                        self._store,
                        "get_challenge_by_binding_interaction",
                        challenge.igreja_id,
                        challenge.binding_id,
                        challenge.interaction_id,
                    )
                    if winner_by_binding is not None:
                        if type(winner_by_binding) is not ConsentChallenge:
                            _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
                        if winner_by_binding.id != challenge.id:
                            _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
                        if not compare_challenges(winner_by_binding, challenge):
                            _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
                    if winner_by_id is None:
                        # No row can be safely locked or adopted after an
                        # insert collision has been reported.
                        _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_NOT_FOUND)
                    if type(winner_by_id) is not ConsentChallenge:
                        _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
                    if (
                        winner_by_id.id != challenge.id
                        or not compare_challenges(winner_by_id, challenge)
                    ):
                        _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
                    existing_before_lock = winner_by_id

        if not inserted_new:
            if existing_before_lock is None:
                # Defensive: the only valid no-row path is the successful
                # insert above, which set inserted_new explicitly.
                _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_NOT_FOUND)
            if type(existing_before_lock) is not ConsentChallenge:
                _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
            if not compare_challenges(existing_before_lock, challenge):
                _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
            _store_call(self._store, "lock_challenge", challenge.igreja_id, challenge.id)
            reread = _store_call(
                self._store,
                "get_challenge",
                challenge.igreja_id,
                challenge.id,
            )
            challenge = _check_challenge_row(challenge, reread)

        _store_call(
            self._store,
            "lock_ledger_stream",
            challenge.igreja_id,
            challenge.pessoa_id,
            challenge.finalidade,
        )
        # The stream lock is the final serialization point.  Re-read the
        # server source and clock after it; any failure after a new challenge
        # INSERT is intentionally left to the external transaction owner to
        # roll back.
        post_lock_now = _require_clock(self._clock)
        authority = _source_call(
            self._source,
            "revalidate",
            request,
            authority,
            now=post_lock_now,
        )
        _validate_authority(request, authority)
        if challenge.estado is not ConsentChallengeState.OPEN:
            # A terminal row is only useful for a complete exact replay.  The
            # caller path below still verifies every row before returning it.
            if not (
                challenge.estado is ConsentChallengeState.CONSUMED
                or (
                    allow_expired_replay
                    and challenge.estado is ConsentChallengeState.EXPIRED
                )
            ):
                _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
        existing_binding = _store_call(
            self._store,
            "get_challenge_by_binding_interaction",
            challenge.igreja_id,
            challenge.binding_id,
            challenge.interaction_id,
        )
        if existing_binding is not None and (
            type(existing_binding) is not ConsentChallenge
            or existing_binding.id != challenge.id
            or not compare_challenges(existing_binding, challenge)
        ):
            _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
        _same_ledger(
            authority,
            _store_call(
                self._store,
                "get_ledger_state",
                challenge.igreja_id,
                challenge.pessoa_id,
                challenge.finalidade,
            ),
            require_absent=require_ledger_absent,
        )
        return challenge, authority, post_lock_now

    def record_presentation(
        self, request: ConsentEvidenceRequest
    ) -> ConsentEvidenceOperationResult:
        """Stage a PRESENTATION evidence row without any ledger write."""

        request = _require_request(request)
        challenge, authority, pre_lock_now = self._preflight(
            request, presentation=True
        )
        challenge, authority, post_lock_now = self._lock_and_revalidate(
            request,
            authority,
            pre_lock_now,
            require_ledger_absent=False,
            allow_expired_replay=True,
        )
        existing_by_key = _store_call(
            self._store,
            "get_evidence_by_idempotency",
            challenge.igreja_id,
            request.chave_idempotencia,
        )
        existing = _store_call(
            self._store,
            "get_evidence_by_challenge_type",
            challenge.igreja_id,
            challenge.id,
            ConsentEvidenceType.PRESENTATION,
        )
        if (
            existing_by_key is not None
            and type(existing_by_key) is not ConsentEvidenceRecord
        ) or (
            existing is not None and type(existing) is not ConsentEvidenceRecord
        ):
            _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
        if existing_by_key is not None and existing is None:
            _fail(ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT)
        if existing is not None:
            if (
                existing_by_key is None
                or existing_by_key.id != existing.id
                or existing.chave_idempotencia != request.chave_idempotencia.value
                or not compare_evidence_intent(existing, request=request)
            ):
                _fail(ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT)
            return ConsentEvidenceOperationResult(
                challenge=challenge,
                presentation=existing,
                manifestation=None,
                receipt=None,
                replayed=True,
            )
        if challenge.estado is not ConsentChallengeState.OPEN:
            if challenge.estado is ConsentChallengeState.EXPIRED:
                _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_EXPIRED)
            _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT)
        _ensure_not_expired(challenge, now=post_lock_now)
        evidence = build_evidence(
            evidence_id=_new_evidence_id(),
            igreja_id=challenge.igreja_id,
            desafio_id=challenge.id,
            tipo=ConsentEvidenceType.PRESENTATION,
            chave_idempotencia=request.chave_idempotencia,
            challenge=challenge,
            registrado_em=request.apresentada_em,
        )
        _store_call(self._store, "insert_evidence", evidence)
        _store_call(self._store, "flush")
        return ConsentEvidenceOperationResult(
            challenge=challenge,
            presentation=evidence,
            manifestation=None,
            receipt=None,
            replayed=False,
        )

    def record_initial_refusal(
        self, request: ConsentEvidenceRequest
    ) -> ConsentEvidenceOperationResult:
        """Atomically stage challenge, presentation, refusal and receipt."""

        request = _require_request(request)
        challenge, authority, pre_lock_now = self._preflight(
            request, presentation=False
        )
        challenge, authority, post_lock_now = self._lock_and_revalidate(
            request,
            authority,
            pre_lock_now,
            require_ledger_absent=True,
            allow_expired_replay=True,
        )

        by_key = _store_call(
            self._store,
            "get_evidence_by_idempotency",
            challenge.igreja_id,
            request.chave_idempotencia,
        )
        manifestation = _store_call(
            self._store,
            "get_evidence_by_challenge_type",
            challenge.igreja_id,
            challenge.id,
            ConsentEvidenceType.MANIFESTATION,
        )
        presentation = _store_call(
            self._store,
            "get_evidence_by_challenge_type",
            challenge.igreja_id,
            challenge.id,
            ConsentEvidenceType.PRESENTATION,
        )
        for row in (by_key, manifestation, presentation):
            if row is not None and type(row) is not ConsentEvidenceRecord:
                _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)

        if presentation is not None and (
            presentation.igreja_id != challenge.igreja_id
            or presentation.desafio_id != challenge.id
            or presentation.tipo is not ConsentEvidenceType.PRESENTATION
            or presentation.registrado_em != request.apresentada_em
            or not evidence_matches_digest(presentation, challenge)
        ):
            _fail(ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT)

        if challenge.estado is not ConsentChallengeState.OPEN and manifestation is None:
            if challenge.estado is ConsentChallengeState.EXPIRED:
                _fail(ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_EXPIRED)
            _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)

        if manifestation is not None:
            receipt = _store_call(
                self._store,
                "get_receipt_by_evidence",
                challenge.igreja_id,
                manifestation.id,
            )
            if (
                challenge.estado is not ConsentChallengeState.CONSUMED
                or presentation is None
                or by_key is None
                or by_key.id != manifestation.id
                or not compare_evidence_intent(
                    manifestation,
                    request=request,
                    presentation_id=presentation.id,
                )
                or type(receipt) is not ConsentReceipt
                or receipt.igreja_id != challenge.igreja_id
                or receipt.evidencia_id != manifestation.id
                or receipt.chave_idempotencia != request.chave_idempotencia.value
                or receipt.acao is not ConsentEvidenceAction.REFUSE_INITIAL
                or receipt.schema_version
                is not ConsentEvidenceSchemaVersion.RECEIPT_LAB_V1
                or receipt.registrado_em != request.manifestada_em
            ):
                _fail(ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT)
            return ConsentEvidenceOperationResult(
                challenge=challenge,
                presentation=presentation,
                manifestation=manifestation,
                receipt=receipt,
                replayed=True,
            )
        if by_key is not None:
            _fail(ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT)

        _ensure_not_expired(challenge, now=post_lock_now)

        if presentation is None:
            # This generated key is an internal identity, never caller input;
            # it is needed because the table has a unique key for each
            # evidence row while refusal's key belongs to the manifestation/
            # receipt.
            presentation = build_evidence(
                evidence_id=_new_evidence_id(),
                igreja_id=challenge.igreja_id,
                desafio_id=challenge.id,
                tipo=ConsentEvidenceType.PRESENTATION,
                chave_idempotencia=OpaqueConsentEvidenceIdempotencyKey.generate(),
                challenge=challenge,
                registrado_em=request.apresentada_em,
            )
            _store_call(self._store, "insert_evidence", presentation)

        manifestation = build_evidence(
            evidence_id=_new_evidence_id(),
            igreja_id=challenge.igreja_id,
            desafio_id=challenge.id,
            tipo=ConsentEvidenceType.MANIFESTATION,
            chave_idempotencia=request.chave_idempotencia,
            challenge=challenge,
            registrado_em=request.manifestada_em,
            apresentacao_id=presentation.id,
            acao=ConsentEvidenceAction.REFUSE_INITIAL,
        )
        receipt = ConsentReceipt(
            id=_new_evidence_id(),
            igreja_id=challenge.igreja_id,
            evidencia_id=manifestation.id,
            chave_idempotencia=request.chave_idempotencia.value,
            registrado_em=request.manifestada_em,
            acao=ConsentEvidenceAction.REFUSE_INITIAL,
        )
        _store_call(self._store, "insert_evidence", manifestation)
        _store_call(self._store, "insert_receipt", receipt)
        _store_call(
            self._store,
            "transition_challenge",
            challenge.igreja_id,
            challenge.id,
            ConsentChallengeState.CONSUMED,
            request.manifestada_em,
        )
        _store_call(self._store, "flush")
        return ConsentEvidenceOperationResult(
            challenge=_new_challenge_state(
                challenge,
                state=ConsentChallengeState.CONSUMED,
                ended_at=request.manifestada_em,
            ),
            presentation=presentation,
            manifestation=manifestation,
            receipt=receipt,
            replayed=False,
        )

    # Names used by early internal callers; all are the same narrow operation.
    stage_presentation = record_presentation
    persist_presentation = record_presentation
    stage_initial_refusal = record_initial_refusal
    persist_initial_refusal = record_initial_refusal

    def reconcile_initial_refusal(
        self, request: ConsentEvidenceRequest
    ) -> ConsentEvidenceReconciliationResult:
        """Read a committed result in a caller-owned transaction.

        This path performs no locks, inserts, transitions or flushes.  It is a
        recovery observation only: a confirmed receipt does not imply that a
        channel delivered it.
        """

        request = _require_request(request)
        _require_allowed_action(request, presentation=False)
        _require_external_transaction(self._store)
        try:
            _require_read_only_observation(self._store)
        except ConsentEvidenceUnitOfWorkError:
            return ConsentEvidenceReconciliationResult(
                status=ConsentEvidenceReconciliationStatus.UNKNOWN
            )
        challenge = request.desafio
        _require_tenant_scope(self._store, challenge.igreja_id)
        try:
            authority = _source_call(
                self._source,
                "resolve",
                request,
                now=_require_clock(self._clock),
            )
            _validate_authority(request, authority)
            existing = _store_call(
                self._store,
                "get_evidence_by_idempotency",
                challenge.igreja_id,
                request.chave_idempotencia,
            )
            if existing is None:
                return ConsentEvidenceReconciliationResult(
                    status=ConsentEvidenceReconciliationStatus.NOT_FOUND
                )
            if type(existing) is not ConsentEvidenceRecord:
                _fail(ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY)
            stored_challenge = _store_call(
                self._store,
                "get_challenge",
                challenge.igreja_id,
                challenge.id,
            )
            presentation = _store_call(
                self._store,
                "get_evidence_by_challenge_type",
                challenge.igreja_id,
                challenge.id,
                ConsentEvidenceType.PRESENTATION,
            )
            manifestation = _store_call(
                self._store,
                "get_evidence_by_challenge_type",
                challenge.igreja_id,
                challenge.id,
                ConsentEvidenceType.MANIFESTATION,
            )
            receipt = _store_call(
                self._store,
                "get_receipt_by_evidence",
                challenge.igreja_id,
                existing.id,
            )
            ledger_state = _store_call(
                self._store,
                "get_ledger_state",
                challenge.igreja_id,
                challenge.pessoa_id,
                challenge.finalidade,
            )
            if (
                type(stored_challenge) is not ConsentChallenge
                or not compare_challenges(stored_challenge, challenge)
                or stored_challenge.estado is not ConsentChallengeState.CONSUMED
                or type(presentation) is not ConsentEvidenceRecord
                or presentation.igreja_id != challenge.igreja_id
                or presentation.desafio_id != challenge.id
                or presentation.tipo is not ConsentEvidenceType.PRESENTATION
                or presentation.registrado_em != request.apresentada_em
                or presentation.apresentacao_id is not None
                or presentation.acao is not None
                or not evidence_matches_digest(presentation, stored_challenge)
                or type(manifestation) is not ConsentEvidenceRecord
                or manifestation.id != existing.id
                or type(receipt) is not ConsentReceipt
                or not compare_evidence_intent(
                    manifestation,
                    request=request,
                    presentation_id=presentation.id,
                )
                or receipt.evidencia_id != manifestation.id
                or receipt.igreja_id != challenge.igreja_id
                or receipt.chave_idempotencia != request.chave_idempotencia.value
                or receipt.acao is not ConsentEvidenceAction.REFUSE_INITIAL
                or receipt.schema_version
                is not ConsentEvidenceSchemaVersion.RECEIPT_LAB_V1
                or receipt.registrado_em != request.manifestada_em
                or ledger_state
                != (
                    ConsentEvidenceLedgerState.ABSENT,
                    None,
                )
            ):
                return ConsentEvidenceReconciliationResult(
                    status=ConsentEvidenceReconciliationStatus.CONFLICT
                )
            return ConsentEvidenceReconciliationResult(
                status=ConsentEvidenceReconciliationStatus.CONFIRMED,
                operation=ConsentEvidenceOperationResult(
                    challenge=stored_challenge,
                    presentation=presentation,
                    manifestation=manifestation,
                    receipt=receipt,
                    replayed=True,
                ),
            )
        except ConsentEvidenceUnitOfWorkError as exc:
            if exc.code in {
                ConsentEvidenceUnitOfWorkErrorCode.TENANT_SCOPE_REQUIRED,
                ConsentEvidenceUnitOfWorkErrorCode.TRANSACTION_REQUIRED,
            }:
                raise
            return ConsentEvidenceReconciliationResult(
                status=ConsentEvidenceReconciliationStatus.UNKNOWN
            )
        except Exception:
            # Never leak source/driver exceptions or claim that delivery took
            # place when the observation itself failed.
            return ConsentEvidenceReconciliationResult(
                status=ConsentEvidenceReconciliationStatus.UNKNOWN
            )

    reconcile = reconcile_initial_refusal


def record_consent_presentation(
    store: ConsentEvidenceStoreProtocol,
    request: ConsentEvidenceRequest,
    *,
    source: ConsentEvidenceSource | None = None,
    clock: Callable[[], dt.datetime] = utc_now,
) -> ConsentEvidenceOperationResult:
    return ConsentEvidenceUnitOfWork(store, source=source, clock=clock).record_presentation(
        request
    )


def record_initial_consent_refusal(
    store: ConsentEvidenceStoreProtocol,
    request: ConsentEvidenceRequest,
    *,
    source: ConsentEvidenceSource | None = None,
    clock: Callable[[], dt.datetime] = utc_now,
) -> ConsentEvidenceOperationResult:
    return ConsentEvidenceUnitOfWork(
        store, source=source, clock=clock
    ).record_initial_refusal(request)


persist_initial_refusal = record_initial_consent_refusal
stage_initial_refusal = record_initial_consent_refusal


def reconcile_consent_evidence(
    store: ConsentEvidenceStoreProtocol,
    request: ConsentEvidenceRequest,
    *,
    source: ConsentEvidenceSource | None = None,
    clock: Callable[[], dt.datetime] = utc_now,
) -> ConsentEvidenceReconciliationResult:
    return ConsentEvidenceUnitOfWork(
        store, source=source, clock=clock
    ).reconcile_initial_refusal(request)


__all__ = [
    "ConsentEvidenceIdempotencyConflictError",
    "ConsentEvidenceOperationResult",
    "ConsentEvidenceReconciliationResult",
    "ConsentEvidenceReconciliationStatus",
    "ConsentEvidenceSourceUnavailableError",
    "ConsentEvidenceStoreProtocol",
    "ConsentEvidenceTransactionRequiredError",
    "ConsentEvidenceUnitOfWork",
    "ConsentEvidenceUnitOfWorkError",
    "ConsentEvidenceUnitOfWorkErrorCode",
    "ConsentEvidenceChallengeExpiredError",
    "persist_initial_refusal",
    "record_consent_presentation",
    "record_initial_consent_refusal",
    "reconcile_consent_evidence",
    "stage_initial_refusal",
    "utc_now",
]

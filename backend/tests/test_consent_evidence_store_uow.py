"""Synthetic unit tests for the offline consent-evidence UoW."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid

import pytest

from app.domain.consent_evidence_store import (
    ConsentChallenge,
    ConsentChallengeState,
    ConsentEvidenceAction,
    ConsentEvidenceAgeStatus,
    ConsentEvidenceAuthenticationState,
    ConsentEvidenceChannel,
    ConsentEvidenceChoiceMode,
    ConsentEvidenceInteractionIntegrity,
    ConsentEvidenceLanguage,
    ConsentEvidenceLedgerState,
    ConsentEvidenceRecord,
    ConsentEvidenceRequest,
    ConsentEvidenceSessionState,
    ConsentEvidenceSubjectKind,
    ConsentEvidenceType,
    ConsentReceipt,
    OpaqueConsentEvidenceIdempotencyKey,
    TrustedAdultSelfSubject,
    TrustedConsentEvidenceAuthority,
)
from app.domain.purpose_consent import PurposeConsentPurpose
from app.services.consent_evidence_store import (
    ConsentEvidenceReconciliationStatus,
    ConsentEvidenceUnitOfWork,
    ConsentEvidenceUnitOfWorkError,
    ConsentEvidenceUnitOfWorkErrorCode,
)


UTC = dt.timezone.utc
TENANT = uuid.UUID("10000000-0000-4000-8000-000000000001")
OTHER_TENANT = uuid.UUID("10000000-0000-4000-8000-000000000009")
PERSON = uuid.UUID("20000000-0000-4000-8000-000000000002")
PACKAGE = uuid.UUID("30000000-0000-4000-8000-000000000003")
BINDING = uuid.UUID("40000000-0000-4000-8000-000000000004")
INTERACTION = uuid.UUID("50000000-0000-4000-8000-000000000005")
CHALLENGE_ID = uuid.UUID("60000000-0000-4000-8000-000000000006")
DIGEST = hashlib.sha256(b"synthetic").hexdigest()


def _time(minute: int) -> dt.datetime:
    return dt.datetime(2026, 9, 7, 12, minute, tzinfo=UTC)


def _challenge(**changes: object) -> ConsentChallenge:
    values: dict[str, object] = {
        "id": CHALLENGE_ID,
        "igreja_id": TENANT,
        "pessoa_id": PERSON,
        "finalidade": PurposeConsentPurpose.TAREFAS_OPERACIONAIS,
        "package_id": PACKAGE,
        "package_version": "1.0.0",
        "content_digest": DIGEST,
        "catalog_entry_digest": DIGEST,
        "notice_text_digest": DIGEST,
        "binding_id": BINDING,
        "interaction_id": INTERACTION,
        "canal": ConsentEvidenceChannel.WHATSAPP,
        "idioma": ConsentEvidenceLanguage.PT_BR,
        "criado_em": _time(0),
        "expira_em": _time(30),
    }
    values.update(changes)
    return ConsentChallenge(**values)


def _request(
    *,
    action: ConsentEvidenceAction | None = ConsentEvidenceAction.REFUSE_INITIAL,
    challenge: ConsentChallenge | None = None,
    key: OpaqueConsentEvidenceIdempotencyKey | None = None,
    presented_at: dt.datetime | None = None,
    manifested_at: dt.datetime | None = None,
) -> ConsentEvidenceRequest:
    return ConsentEvidenceRequest(
        desafio=challenge or _challenge(),
        chave_idempotencia=key or OpaqueConsentEvidenceIdempotencyKey.generate(),
        apresentada_em=presented_at or _time(1),
        manifestada_em=(
            manifested_at
            if manifested_at is not None
            else (_time(2) if action is not None else None)
        ),
        acao=action,
    )


def _subject(
    *,
    age: ConsentEvidenceAgeStatus = ConsentEvidenceAgeStatus.ADULT,
    auth: ConsentEvidenceAuthenticationState = ConsentEvidenceAuthenticationState.VALID,
    session: ConsentEvidenceSessionState = ConsentEvidenceSessionState.ACTIVE,
    integrity: ConsentEvidenceInteractionIntegrity = ConsentEvidenceInteractionIntegrity.ORIGINAL_DIRECT,
    choice: ConsentEvidenceChoiceMode = ConsentEvidenceChoiceMode.EXPLICIT_CONTROL,
) -> TrustedAdultSelfSubject:
    return TrustedAdultSelfSubject(
        kind=ConsentEvidenceSubjectKind.ADULT_SELF,
        age_status=age,
        authentication_state=auth,
        session_state=session,
        interaction_integrity=integrity,
        choice_mode=choice,
    )


def _authority(
    request: ConsentEvidenceRequest,
    *,
    subject: TrustedAdultSelfSubject | None = None,
    prior_state: ConsentEvidenceLedgerState = ConsentEvidenceLedgerState.ABSENT,
    prior_event_id: uuid.UUID | None = None,
    action: ConsentEvidenceAction | None = None,
) -> TrustedConsentEvidenceAuthority:
    challenge = request.desafio
    return TrustedConsentEvidenceAuthority(
        igreja_id=challenge.igreja_id,
        pessoa_id=challenge.pessoa_id,
        actor_id=challenge.pessoa_id,
        finalidade=challenge.finalidade,
        package_id=challenge.package_id,
        package_version=challenge.package_version,
        content_digest=challenge.content_digest,
        catalog_entry_digest=challenge.catalog_entry_digest,
        notice_text_digest=challenge.notice_text_digest,
        binding_id=challenge.binding_id,
        interaction_id=challenge.interaction_id,
        canal=challenge.canal,
        idioma=challenge.idioma,
        subject=subject or _subject(),
        prior_ledger_state=prior_state,
        prior_event_id=prior_event_id,
        action=action if action is not None else request.acao,
        presented_at=request.apresentada_em,
        manifested_at=request.manifestada_em,
    )


class SyntheticSource:
    def __init__(self, *, revoke_after_resolve: bool = False) -> None:
        self.calls: list[str] = []
        self.revoke_after_resolve = revoke_after_resolve
        self.request: ConsentEvidenceRequest | None = None

    def resolve(self, request: ConsentEvidenceRequest, *, now: dt.datetime):
        self.calls.append("resolve")
        self.request = request
        return _authority(
            request,
            subject=_subject(
                choice=(
                    ConsentEvidenceChoiceMode.PRESENTATION_ONLY
                    if request.acao is None
                    else ConsentEvidenceChoiceMode.EXPLICIT_CONTROL
                )
            ),
        )

    def revalidate(
        self,
        request: ConsentEvidenceRequest,
        previous: TrustedConsentEvidenceAuthority,
        *,
        now: dt.datetime,
    ):
        self.calls.append("revalidate")
        if self.revoke_after_resolve:
            raise RuntimeError("synthetic authority revoked")
        return _authority(
            request,
            subject=_subject(
                choice=(
                    ConsentEvidenceChoiceMode.PRESENTATION_ONLY
                    if request.acao is None
                    else ConsentEvidenceChoiceMode.EXPLICIT_CONTROL
                )
            ),
        )


class MemoryConsentEvidenceStore:
    """A transactional-shape fake; mutations are visible until caller rollback."""

    def __init__(
        self,
        *,
        scope_tenant: uuid.UUID = TENANT,
        scope_role: str = "authenticated",
        scope_guc: uuid.UUID = TENANT,
    ) -> None:
        self.scope_tenant = scope_tenant
        self.scope_role = scope_role
        self.scope_guc = scope_guc
        self.active = True
        self.readonly_observation = True
        self.challenges: dict[uuid.UUID, ConsentChallenge] = {}
        self.evidence: dict[uuid.UUID, ConsentEvidenceRecord] = {}
        self.receipts: dict[uuid.UUID, ConsentReceipt] = {}
        self.ledger: dict[tuple[uuid.UUID, uuid.UUID, object], tuple[ConsentEvidenceLedgerState, uuid.UUID | None]] = {}
        self.calls: list[str] = []
        self.flushes = 0

    def transaction_active(self) -> bool:
        self.calls.append("transaction_active")
        return self.active

    def require_tenant_scope(self, igreja_id: uuid.UUID) -> None:
        self.calls.append("require_tenant_scope")
        if (
            self.scope_role != "authenticated"
            or self.scope_tenant != igreja_id
            or self.scope_guc != igreja_id
        ):
            raise RuntimeError("scope mismatch")

    def require_readonly_observation(self) -> None:
        self.calls.append("require_readonly_observation")
        if not self.readonly_observation:
            raise RuntimeError("same staging transaction")

    def lock_idempotency_key(self, igreja_id, chave_idempotencia) -> None:
        self.calls.append("lock_idempotency_key")

    def lock_challenge(self, igreja_id, desafio_id) -> None:
        self.calls.append("lock_challenge")

    def lock_ledger_stream(self, igreja_id, pessoa_id, finalidade) -> None:
        self.calls.append("lock_ledger_stream")

    def get_challenge(self, igreja_id, desafio_id):
        self.calls.append("get_challenge")
        return self.challenges.get(desafio_id)

    def get_challenge_by_binding_interaction(self, igreja_id, binding_id, interaction_id):
        self.calls.append("get_challenge_by_binding_interaction")
        for challenge in self.challenges.values():
            if (
                challenge.igreja_id == igreja_id
                and challenge.binding_id == binding_id
                and challenge.interaction_id == interaction_id
            ):
                return challenge
        return None

    def get_evidence_by_idempotency(self, igreja_id, chave_idempotencia):
        self.calls.append("get_evidence_by_idempotency")
        key = chave_idempotencia.value
        return next(
            (
                evidence
                for evidence in self.evidence.values()
                if evidence.igreja_id == igreja_id and evidence.chave_idempotencia == key
            ),
            None,
        )

    def get_evidence_by_challenge_type(self, igreja_id, desafio_id, tipo):
        self.calls.append("get_evidence_by_challenge_type")
        return next(
            (
                evidence
                for evidence in self.evidence.values()
                if evidence.igreja_id == igreja_id
                and evidence.desafio_id == desafio_id
                and evidence.tipo is tipo
            ),
            None,
        )

    def get_receipt_by_evidence(self, igreja_id, evidencia_id):
        self.calls.append("get_receipt_by_evidence")
        return next(
            (
                receipt
                for receipt in self.receipts.values()
                if receipt.igreja_id == igreja_id and receipt.evidencia_id == evidencia_id
            ),
            None,
        )

    def get_ledger_state(self, igreja_id, pessoa_id, finalidade):
        self.calls.append("get_ledger_state")
        return self.ledger.get(
            (igreja_id, pessoa_id, finalidade),
            (ConsentEvidenceLedgerState.ABSENT, None),
        )

    def insert_challenge(self, challenge):
        self.calls.append("insert_challenge")
        if challenge.id in self.challenges:
            return False
        self.challenges[challenge.id] = challenge
        return True

    def insert_evidence(self, evidence):
        self.calls.append("insert_evidence")
        self.evidence[evidence.id] = evidence

    def insert_receipt(self, receipt):
        self.calls.append("insert_receipt")
        self.receipts[receipt.id] = receipt

    def transition_challenge(self, igreja_id, desafio_id, state, ended_at):
        self.calls.append("transition_challenge")
        challenge = self.challenges[desafio_id]
        self.challenges[desafio_id] = challenge.with_state(state, ended_at)

    def flush(self):
        self.calls.append("flush")
        self.flushes += 1

    def snapshot(self):
        """Represent the caller's external transaction savepoint."""

        return dict(self.challenges), dict(self.evidence), dict(self.receipts)

    def rollback_external(self, snapshot) -> None:
        """Undo staged rows as the transaction owner, never as the service."""

        self.challenges, self.evidence, self.receipts = snapshot


def _uow(
    store: MemoryConsentEvidenceStore,
    source: SyntheticSource | None = None,
    now: dt.datetime = _time(3),
) -> ConsentEvidenceUnitOfWork:
    return ConsentEvidenceUnitOfWork(store, source=source or SyntheticSource(), clock=lambda: now)


def test_accept_and_withdraw_are_blocked_before_any_store_or_source_io() -> None:
    store = MemoryConsentEvidenceStore()
    source = SyntheticSource()
    for action in (ConsentEvidenceAction.ACCEPT, ConsentEvidenceAction.WITHDRAW):
        request = _request(action=action)
        with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
            _uow(store, source).record_initial_refusal(request)
        assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.ACTION_BLOCKED
        assert store.calls == []
        assert source.calls == []


def test_default_source_denies_without_authority_and_no_ledger_is_touched() -> None:
    store = MemoryConsentEvidenceStore()
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        ConsentEvidenceUnitOfWork(store).record_initial_refusal(_request())
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.SOURCE_UNAVAILABLE
    assert "lock_idempotency_key" not in store.calls
    assert store.ledger == {}


def test_valid_refusal_stages_four_rows_in_lock_order_without_ledger_or_transaction_control() -> None:
    store = MemoryConsentEvidenceStore()
    source = SyntheticSource()
    request = _request()
    result = _uow(store, source).record_initial_refusal(request)
    assert result.replayed is False
    assert result.requires_caller_commit is True
    assert result.delivery_claimed is False
    assert result.challenge.estado is ConsentChallengeState.CONSUMED
    assert result.presentation.tipo is ConsentEvidenceType.PRESENTATION
    assert result.manifestation is not None
    assert result.receipt is not None
    assert result.receipt.chave_idempotencia == request.chave_idempotencia.value
    assert len(store.challenges) == 1
    assert len(store.evidence) == 2
    assert len(store.receipts) == 1
    assert store.ledger == {}
    locks = [name for name in store.calls if name.startswith("lock_")]
    assert locks == ["lock_idempotency_key", "lock_ledger_stream"]
    assert store.calls.index("insert_challenge") < store.calls.index(
        "lock_ledger_stream"
    )
    assert source.calls == ["resolve", "revalidate"]
    assert store.flushes == 1
    # No commit/begin/rollback methods are present on the fake; this test's
    # successful path proves they were not looked up or called.
    assert all(name not in store.calls for name in ("begin", "commit", "rollback"))


def test_presentation_also_inserts_challenge_before_evidence_and_never_ledger_writes() -> None:
    store = MemoryConsentEvidenceStore()
    source = SyntheticSource()
    request = _request(action=None)
    result = _uow(store, source).record_presentation(request)
    assert result.receipt is None
    assert result.manifestation is None
    assert len(store.challenges) == 1
    assert len(store.evidence) == 1
    assert store.evidence[result.presentation.id].tipo is ConsentEvidenceType.PRESENTATION
    assert store.ledger == {}
    assert store.calls.index("insert_challenge") < store.calls.index("insert_evidence")
    assert store.calls.index("insert_challenge") < store.calls.index(
        "lock_ledger_stream"
    ) < store.calls.index("insert_evidence")
    replay = _uow(store, SyntheticSource()).record_presentation(request)
    assert replay.replayed is True
    assert replay.presentation.id == result.presentation.id


def test_scope_role_or_guc_mismatch_fails_before_locks() -> None:
    for kwargs in (
        {"scope_role": "postgres"},
        {"scope_tenant": OTHER_TENANT},
        {"scope_guc": OTHER_TENANT},
    ):
        store = MemoryConsentEvidenceStore(**kwargs)
        with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
            _uow(store).record_initial_refusal(_request())
        assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.TENANT_SCOPE_REQUIRED
        assert "lock_idempotency_key" not in store.calls


def test_post_lock_clock_expiry_is_denied_and_source_is_revalidated() -> None:
    store = MemoryConsentEvidenceStore()
    source = SyntheticSource()
    snapshot = store.snapshot()
    clock_values = iter((_time(3), _time(30)))
    uow = ConsentEvidenceUnitOfWork(
        store,
        source=source,
        clock=lambda: next(clock_values),
    )
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        uow.record_initial_refusal(_request())
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_EXPIRED
    assert source.calls == ["resolve", "revalidate"]
    assert "insert_challenge" in store.calls
    assert "lock_ledger_stream" in store.calls
    assert store.evidence == {}
    assert store.receipts == {}
    store.rollback_external(snapshot)
    assert store.challenges == {}
    assert store.ledger == {}


def test_post_lock_source_revocation_leaves_staged_challenge_for_external_rollback() -> None:
    store = MemoryConsentEvidenceStore()
    source = SyntheticSource(revoke_after_resolve=True)
    snapshot = store.snapshot()
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store, source).record_initial_refusal(_request())
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.SOURCE_INVALID
    assert source.calls == ["resolve", "revalidate"]
    assert "insert_challenge" in store.calls
    assert "insert_evidence" not in store.calls
    assert "insert_receipt" not in store.calls
    assert store.challenges
    store.rollback_external(snapshot)
    assert store.challenges == {}
    assert store.evidence == {}
    assert store.receipts == {}


def test_partial_receipt_failure_requires_external_rollback() -> None:
    class FailingReceiptStore(MemoryConsentEvidenceStore):
        def insert_receipt(self, receipt):
            super().insert_receipt(receipt)
            raise RuntimeError("synthetic failure after receipt staging")

    store = FailingReceiptStore()
    snapshot = store.snapshot()
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store, SyntheticSource()).record_initial_refusal(_request())
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.DATA_INTEGRITY
    assert store.challenges and store.evidence and store.receipts
    assert store.ledger == {}
    store.rollback_external(snapshot)
    assert store.challenges == store.evidence == store.receipts == {}


def test_existing_ledger_grant_is_not_reclassified_as_initial_refusal() -> None:
    store = MemoryConsentEvidenceStore()
    prior_event = uuid.UUID("80000000-0000-4000-8000-000000000008")
    store.ledger[(TENANT, PERSON, PurposeConsentPurpose.TAREFAS_OPERACIONAIS)] = (
        ConsentEvidenceLedgerState.GRANTED,
        prior_event,
    )
    source = SyntheticSource()
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store, source).record_initial_refusal(_request())
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.LEDGER_CONFLICT
    assert "insert_challenge" in store.calls
    assert store.evidence == {}
    assert store.receipts == {}
    store.rollback_external(({}, {}, {}))
    assert store.challenges == {}


def test_exact_replay_uses_immutable_challenge_match_and_returns_original_rows() -> None:
    store = MemoryConsentEvidenceStore()
    source = SyntheticSource()
    request = _request()
    first = _uow(store, source).record_initial_refusal(request)
    # Request DTO remains OPEN; the persisted row is CONSUMED.  Replay compares
    # immutable challenge binding only and still requires fresh source checks.
    replay = _uow(store, SyntheticSource()).record_initial_refusal(request)
    assert replay.replayed is True
    assert replay.manifestation is not None and first.manifestation is not None
    assert replay.manifestation.id == first.manifestation.id
    assert replay.receipt is not None and first.receipt is not None
    assert replay.receipt.id == first.receipt.id


def test_locked_challenge_disappearing_on_reread_is_not_reinserted() -> None:
    class DeletesAfterChallengeLock(MemoryConsentEvidenceStore):
        def lock_challenge(self, igreja_id, desafio_id) -> None:
            super().lock_challenge(igreja_id, desafio_id)
            self.challenges.pop(desafio_id, None)

    store = DeletesAfterChallengeLock()
    request = _request()
    _uow(store).record_initial_refusal(request)
    store.calls.clear()
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store).record_initial_refusal(request)
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_NOT_FOUND
    assert "insert_challenge" not in store.calls


def test_insert_collision_resolves_same_id_before_stream_then_later_key_conflicts() -> None:
    committed = MemoryConsentEvidenceStore()
    original_request = _request()
    _uow(committed).record_initial_refusal(original_request)
    winner = committed.challenges[original_request.desafio.id]

    class CollisionStore(MemoryConsentEvidenceStore):
        def __init__(self) -> None:
            super().__init__()
            self.challenges = dict(committed.challenges)
            self.evidence = dict(committed.evidence)
            self.receipts = dict(committed.receipts)
            self.hide_id_read = True
            self.hide_binding_read = True

        def get_challenge(self, igreja_id, desafio_id):
            if self.hide_id_read:
                self.calls.append("get_challenge")
                self.hide_id_read = False
                return None
            return super().get_challenge(igreja_id, desafio_id)

        def get_challenge_by_binding_interaction(
            self, igreja_id, binding_id, interaction_id
        ):
            if self.hide_binding_read:
                self.calls.append("get_challenge_by_binding_interaction")
                self.hide_binding_read = False
                return None
            return super().get_challenge_by_binding_interaction(
                igreja_id, binding_id, interaction_id
            )

        def insert_challenge(self, challenge):
            self.calls.append("insert_challenge")
            return False

    store = CollisionStore()
    retry = _request(key=OpaqueConsentEvidenceIdempotencyKey.generate())
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store).record_initial_refusal(retry)
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT
    assert store.challenges[retry.desafio.id] == winner
    assert store.calls.index("insert_challenge") < store.calls.index(
        "lock_challenge"
    ) < store.calls.index("lock_ledger_stream")
    assert len(store.evidence) == len(committed.evidence)
    assert len(store.receipts) == len(committed.receipts)


def test_binding_winner_with_different_challenge_id_is_rejected_before_insert() -> None:
    store = MemoryConsentEvidenceStore()
    incumbent = _challenge(
        id=uuid.UUID("61000000-0000-4000-8000-000000000061")
    )
    store.challenges[incumbent.id] = incumbent
    request = _request()
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store).record_initial_refusal(request)
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT
    assert "get_challenge_by_binding_interaction" in store.calls
    assert "insert_challenge" not in store.calls
    assert "lock_challenge" not in store.calls
    assert "lock_ledger_stream" not in store.calls


def test_exact_replay_after_expiry_recovers_original_but_new_write_is_denied() -> None:
    store = MemoryConsentEvidenceStore()
    request = _request()
    first = _uow(store, now=_time(3)).record_initial_refusal(request)
    replay = _uow(store, now=_time(30)).record_initial_refusal(request)
    assert replay.replayed is True
    assert replay.receipt is not None and first.receipt is not None
    assert replay.receipt.id == first.receipt.id

    fresh_store = MemoryConsentEvidenceStore()
    expired_request = _request(challenge=_challenge())
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(fresh_store, now=_time(30)).record_initial_refusal(expired_request)
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_EXPIRED
    assert fresh_store.challenges == {}
    assert fresh_store.evidence == {}
    assert fresh_store.receipts == {}
    assert "insert_challenge" not in fresh_store.calls
    assert "lock_ledger_stream" not in fresh_store.calls


def test_same_key_with_changed_challenge_is_a_conflict_not_an_overwrite() -> None:
    store = MemoryConsentEvidenceStore()
    request = _request()
    _uow(store).record_initial_refusal(request)
    changed = _request(
        key=request.chave_idempotencia,
        challenge=_challenge(package_version="2.0.0"),
    )
    with pytest.raises(ConsentEvidenceUnitOfWorkError) as raised:
        _uow(store).record_initial_refusal(changed)
    assert raised.value.code is ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT
    assert len(store.evidence) == 2


def test_reconciliation_requires_independent_readonly_snapshot_and_never_claims_delivery() -> None:
    store = MemoryConsentEvidenceStore()
    request = _request()
    _uow(store).record_initial_refusal(request)
    reconciled = _uow(store).reconcile_initial_refusal(request)
    assert reconciled.status is ConsentEvidenceReconciliationStatus.CONFIRMED
    assert reconciled.operation is not None
    assert reconciled.delivery_claimed is False
    assert reconciled.operation.delivery_claimed is False
    assert "require_readonly_observation" in store.calls
    assert store.flushes == 1

    store.readonly_observation = False
    unknown = _uow(store).reconcile_initial_refusal(request)
    assert unknown.status is ConsentEvidenceReconciliationStatus.UNKNOWN
    assert unknown.delivery_claimed is False
    assert store.flushes == 1


def test_reconciliation_distinguishes_not_found_and_sanitizes_adapter_errors() -> None:
    store = MemoryConsentEvidenceStore()
    request = _request()
    assert _uow(store).reconcile_initial_refusal(request).status is ConsentEvidenceReconciliationStatus.NOT_FOUND

    class BrokenStore(MemoryConsentEvidenceStore):
        def get_evidence_by_idempotency(self, igreja_id, chave_idempotencia):
            raise RuntimeError("driver password leaked")

    broken = BrokenStore()
    result = _uow(broken).reconcile_initial_refusal(request)
    assert result.status is ConsentEvidenceReconciliationStatus.UNKNOWN
    assert "driver password leaked" not in repr(result)


def test_reconciliation_never_starts_or_finishes_a_transaction() -> None:
    store = MemoryConsentEvidenceStore()
    store.begin = lambda: pytest.fail("begin must stay caller-owned")
    store.commit = lambda: pytest.fail("commit must stay caller-owned")
    store.rollback = lambda: pytest.fail("rollback must stay caller-owned")
    request = _request()
    _uow(store).record_initial_refusal(request)
    result = _uow(store).reconcile_initial_refusal(request)
    assert result.status is ConsentEvidenceReconciliationStatus.CONFIRMED

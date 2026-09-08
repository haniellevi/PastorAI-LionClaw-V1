"""Synthetic unit tests for the closed consent-evidence domain."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import replace
from enum import Enum

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
    ConsentEvidenceRequest,
    ConsentEvidenceSessionState,
    ConsentEvidenceSubjectKind,
    ConsentEvidenceType,
    ConsentEvidenceValidationError,
    OpaqueConsentEvidenceIdempotencyKey,
    TrustedAdultSelfSubject,
    TrustedConsentEvidenceAuthority,
    add_calendar_years,
    build_evidence,
    canonical_json,
    compute_evidence_digest,
    evidence_matches_digest,
    presentation_retention_deadline,
    receipt_retention_deadline,
    refusal_retention_deadline,
    validate_source_binding,
)
from app.domain.purpose_consent import PurposeConsentPurpose


UTC = dt.timezone.utc
TENANT = uuid.UUID("10000000-0000-4000-8000-000000000001")
OTHER_TENANT = uuid.UUID("10000000-0000-4000-8000-000000000009")
PERSON = uuid.UUID("20000000-0000-4000-8000-000000000002")
PACKAGE = uuid.UUID("30000000-0000-4000-8000-000000000003")
BINDING = uuid.UUID("40000000-0000-4000-8000-000000000004")
INTERACTION = uuid.UUID("50000000-0000-4000-8000-000000000005")
ZERO = uuid.UUID(int=0)
DIGEST = hashlib.sha256(b"synthetic").hexdigest()


def _time(hour: int, minute: int, second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, 7, hour, minute, second, tzinfo=UTC)


def _challenge(**changes: object) -> ConsentChallenge:
    values: dict[str, object] = {
        "id": uuid.UUID("60000000-0000-4000-8000-000000000006"),
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
        "criado_em": _time(12, 0),
        "expira_em": _time(12, 30),
    }
    values.update(changes)
    return ConsentChallenge(**values)


def _request(
    *,
    action: ConsentEvidenceAction | None = ConsentEvidenceAction.REFUSE_INITIAL,
    key: OpaqueConsentEvidenceIdempotencyKey | None = None,
    challenge: ConsentChallenge | None = None,
    presented: dt.datetime | None = None,
    manifested: dt.datetime | None = None,
) -> ConsentEvidenceRequest:
    return ConsentEvidenceRequest(
        desafio=challenge or _challenge(),
        chave_idempotencia=key or OpaqueConsentEvidenceIdempotencyKey.generate(),
        apresentada_em=presented or _time(12, 1),
        manifestada_em=(
            manifested
            if manifested is not None
            else (_time(12, 2) if action is not None else None)
        ),
        acao=action,
    )


def _subject(
    *,
    age: ConsentEvidenceAgeStatus = ConsentEvidenceAgeStatus.ADULT,
    auth: ConsentEvidenceAuthenticationState = ConsentEvidenceAuthenticationState.VALID,
    session: object = None,
    integrity: ConsentEvidenceInteractionIntegrity = ConsentEvidenceInteractionIntegrity.ORIGINAL_DIRECT,
    choice: ConsentEvidenceChoiceMode = ConsentEvidenceChoiceMode.EXPLICIT_CONTROL,
) -> TrustedAdultSelfSubject:
    return TrustedAdultSelfSubject(
        kind=ConsentEvidenceSubjectKind.ADULT_SELF,
        age_status=age,
        authentication_state=auth,
        session_state=(ConsentEvidenceSessionState.ACTIVE if session is None else session),
        interaction_integrity=integrity,
        choice_mode=choice,
    )


def _authority(
    request: ConsentEvidenceRequest,
    *,
    subject: TrustedAdultSelfSubject | None = None,
    prior: ConsentEvidenceLedgerState = ConsentEvidenceLedgerState.ABSENT,
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
        prior_ledger_state=prior,
        action=action if action is not None else request.acao,
        presented_at=request.apresentada_em,
        manifested_at=request.manifestada_em,
    )


def test_closed_dtos_reject_nil_ids_and_expose_no_dynamic_fields() -> None:
    with pytest.raises(ConsentEvidenceValidationError):
        _challenge(id=ZERO)
    challenge = _challenge()
    with pytest.raises(AttributeError):
        challenge.unexpected = "forbidden"  # type: ignore[attr-defined]
    with pytest.raises(ConsentEvidenceValidationError):
        _challenge(package_version="versão livre")


def test_canonical_json_rejects_numbers_non_ascii_and_non_string_keys() -> None:
    with pytest.raises(ConsentEvidenceValidationError):
        canonical_json({"sequence": 1})
    with pytest.raises(ConsentEvidenceValidationError):
        canonical_json({"ação": "x"})
    with pytest.raises(ConsentEvidenceValidationError):
        canonical_json({1: "x"})  # type: ignore[dict-item]
    assert canonical_json({"b": "x", "a": True}) == '{"a":true,"b":"x"}'

    class NumericEnum(Enum):
        VALUE = 1

    with pytest.raises(ConsentEvidenceValidationError):
        canonical_json({"enum": NumericEnum.VALUE})


def test_live_key_has_unforgeable_process_secret_and_persisted_rows_use_text() -> None:
    key = OpaqueConsentEvidenceIdempotencyKey.generate()
    assert key._was_server_minted_in_this_process()
    forged = object.__new__(OpaqueConsentEvidenceIdempotencyKey)
    object.__setattr__(forged, "value", key.value)
    object.__setattr__(forged, "_mint_proof", hashlib.sha256(key.value.encode()).digest())
    assert not forged._was_server_minted_in_this_process()
    # A hydrated DB value is valid as a row key, but cannot become a live
    # authority object by constructing the opaque class.
    challenge = _challenge()
    evidence = build_evidence(
        evidence_id=uuid.UUID("70000000-0000-4000-8000-000000000007"),
        igreja_id=TENANT,
        desafio_id=challenge.id,
        tipo=ConsentEvidenceType.PRESENTATION,
        chave_idempotencia=key,
        challenge=challenge,
        registrado_em=_time(12, 1),
    )
    assert type(evidence.chave_idempotencia) is str
    assert evidence_matches_digest(evidence, challenge)


def test_evidence_digest_includes_complete_immutable_challenge_binding() -> None:
    challenge = _challenge()
    evidence = build_evidence(
        evidence_id=uuid.UUID("70000000-0000-4000-8000-000000000007"),
        igreja_id=TENANT,
        desafio_id=challenge.id,
        tipo=ConsentEvidenceType.PRESENTATION,
        chave_idempotencia=OpaqueConsentEvidenceIdempotencyKey.generate(),
        challenge=challenge,
        registrado_em=_time(12, 1),
    )
    assert compute_evidence_digest(evidence, challenge) == evidence.evidence_digest
    assert not evidence_matches_digest(evidence, _challenge(package_version="2.0.0"))
    assert not evidence_matches_digest(evidence, _challenge(content_digest="0" * 64))


def test_manifestation_requires_presentation_and_refusal_action_only() -> None:
    key = OpaqueConsentEvidenceIdempotencyKey.generate()
    with pytest.raises(ConsentEvidenceValidationError):
        # A PRESENTATION cannot carry an action or presentation FK.
        build_evidence(
            evidence_id=uuid.uuid4(),
            igreja_id=TENANT,
            desafio_id=_challenge().id,
            tipo=ConsentEvidenceType.PRESENTATION,
            chave_idempotencia=key,
            challenge=_challenge(),
            registrado_em=_time(12, 1),
            acao=ConsentEvidenceAction.REFUSE_INITIAL,
        )


def test_adult_self_authority_is_typed_and_not_a_boolean_grant() -> None:
    request = _request()
    authority = _authority(request)
    assert not hasattr(authority, "authorized")
    assert authority.subject.kind is ConsentEvidenceSubjectKind.ADULT_SELF
    assert authority.subject.age_status is ConsentEvidenceAgeStatus.ADULT
    with pytest.raises(ConsentEvidenceValidationError):
        replace(
            authority,
            actor_id=uuid.UUID("80000000-0000-4000-8000-000000000008"),
        )


@pytest.mark.parametrize(
    "subject",
    [
        _subject(age=ConsentEvidenceAgeStatus.MINOR),
        _subject(age=ConsentEvidenceAgeStatus.UNKNOWN),
        _subject(session=ConsentEvidenceSessionState.EXPIRED),
        _subject(session=ConsentEvidenceSessionState.UNKNOWN),
        _subject(integrity=ConsentEvidenceInteractionIntegrity.FORWARDED),
    ],
    ids=[
        "minor",
        "unknown_age",
        "expired_session",
        "unknown_session",
        "forwarded_interaction",
    ],
)
def test_source_binding_rejects_non_adult_or_non_original_interactions(
    subject: TrustedAdultSelfSubject,
) -> None:
    request = _request()
    authority = _authority(request, subject=subject)
    with pytest.raises(ConsentEvidenceValidationError):
        validate_source_binding(request, authority)


def test_source_binding_rejects_authority_from_another_tenant() -> None:
    request = _request()
    authority = replace(_authority(request), igreja_id=OTHER_TENANT)
    with pytest.raises(ConsentEvidenceValidationError):
        validate_source_binding(request, authority)


def test_presentation_authority_cannot_smuggle_an_action() -> None:
    request = _request(action=None)
    authority = _authority(request, action=ConsentEvidenceAction.REFUSE_INITIAL)
    with pytest.raises(ConsentEvidenceValidationError):
        validate_source_binding(request, authority)


def test_calendar_retention_clamps_leap_day_and_presentation_never_extends_after_expiry() -> None:
    leap = dt.datetime(2024, 2, 29, 10, 11, 12, 123456, tzinfo=UTC)
    assert add_calendar_years(leap, 5) == dt.datetime(
        2029, 2, 28, 10, 11, 12, 123456, tzinfo=UTC
    )
    assert refusal_retention_deadline(leap) == add_calendar_years(leap, 5)
    created = _time(12, 0)
    expires = _time(12, 30)
    assert presentation_retention_deadline(
        challenge_created_at=created,
        challenge_expires_at=expires,
        abandoned_at=_time(12, 10),
    ) == _time(12, 10) + dt.timedelta(days=90)
    assert presentation_retention_deadline(
        challenge_created_at=created,
        challenge_expires_at=expires,
        abandoned_at=_time(13, 0),
    ) == expires + dt.timedelta(days=90)
    assert receipt_retention_deadline(
        action=ConsentEvidenceAction.REFUSE_INITIAL,
        recorded_at=_time(12, 2),
    ) == add_calendar_years(_time(12, 2), 5)


def test_challenge_terminal_transition_cannot_reopen_or_mutate() -> None:
    challenge = _challenge()
    consumed = challenge.with_state(ConsentChallengeState.CONSUMED, _time(12, 2))
    assert consumed.estado is ConsentChallengeState.CONSUMED
    with pytest.raises(ConsentEvidenceValidationError):
        consumed.with_state(ConsentChallengeState.CANCELLED, _time(12, 3))
    with pytest.raises(ConsentEvidenceValidationError):
        challenge.with_state(ConsentChallengeState.EXPIRED, _time(12, 29))
    assert challenge.with_state(ConsentChallengeState.EXPIRED, _time(12, 30)).estado is ConsentChallengeState.EXPIRED
    with pytest.raises(ConsentEvidenceValidationError):
        _request(presented=_time(12, 30))

"""Documentary evidence-store proof, no writer/API/provider/database.

All trust inputs are independent synthetic fixtures, not a production source.
Schema validation uses the bounded interpreter already used by the project;
semantic checks are mandatory and exist only in this test module.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from tests import test_consent_immutable_catalog as catalog_contract
from tests import test_d2b2b2_decision_payload_schema as schema_contract


ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "docs/governance/consent/evidence-store"
EXAMPLE = STORE / "examples/igreja-exemplo-refusal.synthetic-example.json"
PINNED_EVIDENCE = "a503a9c37c59d69e61b8ac68fb6fabdbbc839cf2e73a2cdcc9e42ce5980b0921"


def _uid(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def _record():
    return catalog_contract._load(EXAMPLE)


def _catalog():
    return catalog_contract._load(catalog_contract.EXAMPLE)


def _trusted():
    """Fixture of independently observed server-owned binding, never a DTO grant."""
    return {
        "tenant_ref": _uid(202), "controller_ref": _uid(502),
        "person_ref": _uid(503), "purpose": "tarefas_operacionais",
        "package_id": _uid(101), "package_version": "1.0.0",
        "content_digest": catalog_contract.PINNED_CONTENT,
        "catalog_entry_digest": catalog_contract.PINNED_ENTRY,
        "notice_version": "synthetic-notice-v1", "language": "pt-BR",
        "channel": "whatsapp", "correlation_id": _uid(504),
        "challenge_ref": _uid(505), "actor_ref": _uid(503),
        "authentication_method_ref": _uid(506), "interaction_ref": _uid(507),
        "selected_action": "REFUSE_INITIAL", "prior_ledger_state": "ausente",
        "prior_event_ref": None, "interaction_integrity": "ORIGINAL_DIRECT",
        "choice_explicit": True, "age_band": "ADULT",
        "authentication_state": "VALID", "session_active": True,
        "challenge_created_at": "2026-09-07T12:00:00Z",
        "challenge_expires_at": "2026-09-07T12:30:00Z",
        "presented_at": "2026-09-07T12:01:00Z",
        "manifested_at": "2026-09-07T12:02:00Z",
        "delivery_state": "DELIVERED", "renderer_version": "synthetic-renderer/v1",
    }


def _evidence_digest(record):
    return catalog_contract._digest({key: value for key, value in record.items() if key != "evidence_digest"})


def _rehash(record):
    record["evidence_digest"] = _evidence_digest(record)
    return record


def _instant(value):
    parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return parsed.replace(tzinfo=dt.timezone.utc)


def _validate(record, trusted, catalog, *, evidence_anchor=None):
    schema_contract._assert_valid(record, catalog_contract._load(STORE / "evidence.schema.json"))
    catalog_contract._validate(catalog, anchor=trusted["catalog_entry_digest"])
    for key in ("tenant_ref", "controller_ref", "person_ref", "purpose", "package_id", "package_version", "content_digest", "catalog_entry_digest", "notice_version", "language", "channel"):
        assert record[key] == trusted[key], "trusted binding mismatch"
    assert record["tenant_ref"] == catalog["tenant_binding"]
    for key in ("purpose", "package_id", "package_version", "content_digest"):
        assert record[key] == catalog[key], "catalog binding mismatch"
    notice_channel = "painel" if record["channel"] == "painel_autenticado" else "whatsapp"
    notice = catalog["decision_payload"]["notice_texts_by_channel_and_language"][notice_channel][record["language"]]
    assert record["notice_text_digest"] == hashlib.sha256(notice.encode("utf-8")).hexdigest(), "wrong notice"
    for key in ("actor_ref", "authentication_method_ref", "interaction_ref", "selected_action", "manifested_at"):
        assert record["manifestation"][key] == trusted[key], "manifestation binding mismatch"
    assert record["manifestation"]["actor_ref"] == record["person_ref"], "adult actor mismatch"
    assert record["presentation"]["correlation_id"] == trusted["correlation_id"]
    assert record["presentation"]["presented_at"] == trusted["presented_at"]
    assert record["presentation"]["delivery_state"] == trusted["delivery_state"], "delivery observation mismatch"
    assert record["presentation"]["renderer_version"] == trusted["renderer_version"]
    assert record["challenge"]["challenge_ref"] == trusted["challenge_ref"]
    assert record["challenge"]["created_at"] == trusted["challenge_created_at"]
    assert record["challenge"]["expires_at"] == trusted["challenge_expires_at"]
    assert trusted["interaction_integrity"] == "ORIGINAL_DIRECT", "edited or forwarded interaction"
    assert trusted["choice_explicit"] is True, "delivery is not choice"
    assert record["subject"]["age_band"] == trusted["age_band"] == "ADULT", "age not independently established"
    assert trusted["authentication_state"] == "VALID" and trusted["session_active"] is True, "authentication unavailable"
    created = _instant(record["challenge"]["created_at"])
    presented = _instant(record["presentation"]["presented_at"])
    manifested = _instant(record["manifestation"]["manifested_at"])
    expires = _instant(record["challenge"]["expires_at"])
    assert created <= presented <= manifested < expires, "invalid challenge chronology"
    assert dt.timedelta(0) < expires - created <= dt.timedelta(minutes=30), "challenge too long"
    assert record["presentation"]["delivery_state"] != "FAILED", "presentation failed"

    action = record["manifestation"]["selected_action"]
    prior = trusted["prior_event_ref"]
    if action == "REFUSE_INITIAL":
        assert trusted["prior_ledger_state"] == "ausente", "not an initial refusal"
        assert prior is None and record["previous_event_ref"] is None and record["withdrawn_event_ref"] is None
        prospective_effect = "NO_LEDGER_EVENT"
    elif action == "ACCEPT":
        assert trusted["prior_ledger_state"] in {"ausente", "retirado"}
        assert record["previous_event_ref"] == prior and record["withdrawn_event_ref"] is None
        assert (prior is None) == (trusted["prior_ledger_state"] == "ausente")
        prospective_effect = "FUTURE_CONCESSION_REQUIRES_WRITER"
    else:
        assert trusted["prior_ledger_state"] == "concedido" and prior is not None
        assert record["previous_event_ref"] == prior and record["withdrawn_event_ref"] == prior
        prospective_effect = "FUTURE_WITHDRAWAL_REQUIRES_WRITER"
    assert record["evidence_digest"] == _evidence_digest(record), "evidence digest mismatch"
    if evidence_anchor is not None:
        assert record["evidence_digest"] == evidence_anchor, "immutable evidence changed"
    return prospective_effect


def _retry_outcome(previous, candidate):
    """Pure comparison of synthetic fixtures, not a durable store or writer."""
    scope = ("tenant_ref", "person_ref", "purpose")
    if any(previous[key] != candidate[key] for key in scope):
        return "SEPARATE_SCOPE"
    same_key = previous["idempotency_key"] == candidate["idempotency_key"]
    same_challenge = previous["challenge"]["challenge_ref"] == candidate["challenge"]["challenge_ref"]
    same_interaction = previous["manifestation"]["interaction_ref"] == candidate["manifestation"]["interaction_ref"]
    if same_key or same_challenge or same_interaction:
        assert catalog_contract._canonical(previous) == catalog_contract._canonical(candidate), "idempotency conflict"
        return "REPLAY_EXISTING"
    return "NEW_CANDIDATE_NOT_AUTHORIZED"


def test_valid_synthetic_initial_refusal_has_no_ledger_event():
    record = _record()
    assert _validate(record, _trusted(), _catalog(), evidence_anchor=PINNED_EVIDENCE) == "NO_LEDGER_EVENT"
    assert record["receipt_delivery_state"] == "NOT_SENT"
    assert _trusted()["prior_ledger_state"] == "ausente"


@pytest.mark.parametrize("field", ["telefone", "cpf", "documento_civil", "message_text", "audio", "transcription", "intimate_reason", "token", "secret"])
@pytest.mark.parametrize("location", ["root", "presentation", "manifestation"])
def test_sensitive_fields_are_rejected_at_every_object_boundary(field, location):
    record = _record()
    target = record if location == "root" else record[location]
    target[field] = "synthetic forbidden content"
    with pytest.raises(AssertionError):
        _validate(record, _trusted(), _catalog())


@pytest.mark.parametrize("value", ["+" + "0" * 12, ".".join(["0" * 3] * 3) + "-00", "texto sintetico de mensagem"])
def test_sensitive_shaped_values_cannot_hide_inside_allowed_reference(value):
    record = _record()
    record["manifestation"]["interaction_ref"] = value
    with pytest.raises(AssertionError):
        _validate(record, _trusted(), _catalog())


@pytest.mark.parametrize("field", ["content_digest", "catalog_entry_digest", "notice_text_digest", "tenant_ref", "person_ref", "controller_ref", "package_id", "purpose"])
def test_rehash_cannot_rebind_evidence_to_other_digest_or_identity(field):
    record = _record()
    record[field] = "0" * 64 if "digest" in field else ("comunicados" if field == "purpose" else _uid(999))
    _rehash(record)
    with pytest.raises(AssertionError):
        _validate(record, _trusted(), _catalog())


@pytest.mark.parametrize("field", ["controller_approved", "catalog_ready", "writer_eligible", "operational_authorization", "next_stage_authorized"])
@pytest.mark.parametrize("value", [True, 1, "true"])
def test_documentary_proof_cannot_enable_approval_or_runtime(field, value):
    record = _record()
    record[field] = value
    with pytest.raises(AssertionError):
        _validate(record, _trusted(), _catalog())


def test_delivery_does_not_supply_missing_or_ambiguous_choice():
    record = _record()
    for action in (None, "DELIVERED", "READ", "OK", "REACTION"):
        record["manifestation"]["selected_action"] = action
        with pytest.raises(AssertionError):
            _validate(record, _trusted(), _catalog())
    with pytest.raises(AssertionError, match="delivery is not choice"):
        _validate(_record(), _trusted() | {"choice_explicit": False}, _catalog())


@pytest.mark.parametrize("integrity", ["EDITED", "FORWARDED", "UNKNOWN"])
def test_edited_forwarded_or_unknown_origin_is_not_a_manifestation(integrity):
    with pytest.raises(AssertionError):
        _validate(_record(), _trusted() | {"interaction_integrity": integrity}, _catalog())


@pytest.mark.parametrize("change", ["expired", "long", "before", "invalid_date"])
def test_challenge_chronology_fails_closed(change):
    record, expected = _record(), _trusted()
    if change == "long":
        record["challenge"]["expires_at"] = expected["challenge_expires_at"] = "2026-09-07T12:31:00Z"
    else:
        value = {"expired": "2026-09-07T12:30:00Z", "before": "2026-09-07T11:59:00Z", "invalid_date": "2026-02-31T12:02:00Z"}[change]
        record["manifestation"]["manifested_at"] = expected["manifested_at"] = value
    _rehash(record)
    with pytest.raises((AssertionError, ValueError)):
        _validate(record, expected, _catalog())


def test_minor_or_unknown_age_is_not_silently_treated_as_adult():
    for age in ("UNKNOWN", "CHILD", "ADOLESCENT"):
        record = _record()
        record["subject"]["age_band"] = age
        with pytest.raises(AssertionError):
            _validate(record, _trusted(), _catalog())
    with pytest.raises(AssertionError, match="age not independently established"):
        _validate(_record(), _trusted() | {"age_band": "UNKNOWN"}, _catalog())


@pytest.mark.parametrize("change", [{"authentication_state": "UNKNOWN"}, {"session_active": False}, {"session_active": 1}])
def test_authentication_is_required_independently_of_method_reference(change):
    with pytest.raises(AssertionError, match="authentication unavailable"):
        _validate(_record(), _trusted() | change, _catalog())


def test_initial_refusal_does_not_overwrite_prior_grant():
    with pytest.raises(AssertionError, match="not an initial refusal"):
        _validate(_record(), _trusted() | {"prior_ledger_state": "concedido", "prior_event_ref": _uid(700)}, _catalog())


def test_acceptance_and_withdrawal_are_only_future_classifications():
    accepted = _record()
    accepted["manifestation"]["selected_action"] = "ACCEPT"
    _rehash(accepted)
    assert _validate(accepted, _trusted() | {"selected_action": "ACCEPT"}, _catalog()) == "FUTURE_CONCESSION_REQUIRES_WRITER"
    withdrawn = _record()
    withdrawn["manifestation"]["selected_action"] = "WITHDRAW"
    withdrawn["previous_event_ref"] = withdrawn["withdrawn_event_ref"] = _uid(700)
    _rehash(withdrawn)
    expected = _trusted() | {"selected_action": "WITHDRAW", "prior_ledger_state": "concedido", "prior_event_ref": _uid(700)}
    assert _validate(withdrawn, expected, _catalog()) == "FUTURE_WITHDRAWAL_REQUIRES_WRITER"
    assert accepted["writer_eligible"] is withdrawn["writer_eligible"] is False


def test_idempotency_exact_retry_and_conflicting_reuse():
    record = _record()
    assert _retry_outcome(record, copy.deepcopy(record)) == "REPLAY_EXISTING"
    for mutation in ("action", "digest", "new_key_same_challenge", "new_receipt"):
        changed = copy.deepcopy(record)
        if mutation == "action":
            changed["manifestation"]["selected_action"] = "ACCEPT"
        elif mutation == "digest":
            changed["content_digest"] = "0" * 64
        elif mutation == "new_key_same_challenge":
            changed["idempotency_key"] = _uid(901)
        else:
            changed["durable_receipt_ref"] = _uid(902)
        _rehash(changed)
        with pytest.raises(AssertionError, match="idempotency conflict"):
            _retry_outcome(record, changed)


def test_hash_is_integrity_not_authenticity():
    changed = _record()
    changed["immutable_storage_ref"] = _uid(800)
    _rehash(changed)
    _validate(changed, _trusted(), _catalog())
    with pytest.raises(AssertionError, match="immutable evidence changed"):
        _validate(changed, _trusted(), _catalog(), evidence_anchor=PINNED_EVIDENCE)


def test_delivery_status_requires_independent_observation_not_read_assumption():
    unknown = _record()
    unknown["presentation"]["delivery_state"] = "UNKNOWN"
    _rehash(unknown)
    with pytest.raises(AssertionError, match="delivery observation mismatch"):
        _validate(unknown, _trusted(), _catalog())
    # The presentation and explicit choice have their own trusted observation;
    # a missing delivery acknowledgment neither supplies nor cancels choice.
    assert _validate(unknown, _trusted() | {"delivery_state": "UNKNOWN"}, _catalog()) == "NO_LEDGER_EVENT"


def test_cross_tenant_collision_cannot_replay_another_persons_evidence():
    original = _record()
    other_tenant = copy.deepcopy(original)
    other_tenant["tenant_ref"] = _uid(999)
    _rehash(other_tenant)
    # Same key, challenge and interaction must never select the prior tenant's
    # evidence. SEPARATE_SCOPE is not acceptance of the candidate or authority.
    assert _retry_outcome(original, other_tenant) == "SEPARATE_SCOPE"
    with pytest.raises(AssertionError, match="trusted binding mismatch"):
        _validate(other_tenant, _trusted(), _catalog())


def test_contract_keeps_the_three_surfaces_and_operational_gaps_explicit():
    contract = (STORE / "CONTRACT.md").read_text(encoding="utf-8")
    for phrase in ("ledger D2B2a", "evidence store", "recibo", "DRAFT_NOT_APPROVED", "catalog_ready=false", "writer_eligible=false", "custódia", "assinaturas"):
        assert phrase in contract
    assert "Igreja Exemplo" in contract

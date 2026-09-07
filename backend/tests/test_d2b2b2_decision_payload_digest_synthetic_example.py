"""End-to-end proof of the decision_payload digest pipeline, on synthetic data.

Scope: prove, before any real tenant materialization, that a decision_payload
which validates against docs/governance/consent/d2b2b2-decision-payload.schema.json
can be JCS-canonicalized (RFC 8785) and SHA-256-digested exactly as
digest_contract in docs/governance/consent/d2b2b2-decision-packet.template.json
describes ("content_digest = lowercase_hex(SHA-256(UTF8(JCS(decision_payload))))",
see also section 23.2 of docs/governance/consent/
d2b2b2-decision-packet-tarefas-operacionais.md).

The example file (docs/governance/consent/examples/
d2b2b2-decision-payload.tarefas-operacionais.synthetic-example.json) is
entirely fictitious: a made-up UUID tenant, a made-up church name ("Igreja
Exemplo de Testes"), and opaque `ref:...` placeholders everywhere a real
document/contact/evidence reference would go. No CNPJ, phone, or e-mail
appears anywhere.

This does not compute an "official" digest for any real church: it only
proves the mechanics (canonicalization is deterministic, order-independent,
and sensitive to any content change) work end to end against the schema this
mission produced. No `jsonschema` or JCS package is installed in this
backend's venv, so both the schema validator and the canonicalizer are the
same self-contained implementations used by
backend/tests/test_d2b2b2_decision_payload_schema.py (imported dynamically
below, not duplicated).
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "consent"
    / "examples"
    / "d2b2b2-decision-payload.tarefas-operacionais.synthetic-example.json"
)
SCHEMA_TEST_PATH = Path(__file__).resolve().parent / "test_d2b2b2_decision_payload_schema.py"


def _load_schema_test_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_d2b2b2_decision_payload_schema_reference", SCHEMA_TEST_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_example_decision_payload() -> dict[str, Any]:
    """Load the example file and strip the two file-level, non-payload keys.

    `$comment` and `$schema` are conveniences of the example *file*; they are
    not part of decision_payload itself (they are not in DECISION_PAYLOAD_KEYS
    and would be rejected by additionalProperties: false if left in).
    """

    raw = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    payload = dict(raw)
    payload.pop("$comment", None)
    payload.pop("$schema", None)
    return payload


def _jcs_canonicalize(payload: dict[str, Any]) -> bytes:
    """A scoped RFC 8785 (JCS) canonicalizer sufficient for this payload shape.

    decision_payload contains only objects, arrays, strings, booleans, and
    null -- never numbers -- so the hard part of JCS (ECMAScript-compatible
    number serialization) never comes up here. What remains of JCS for this
    shape is: (1) sort object member names, recursively, (2) no insignificant
    whitespace, (3) do not escape non-ASCII characters (UTF-8 them instead of
    \\uXXXX). Python's json.dumps with sort_keys=True + ensure_ascii=False +
    compact separators satisfies exactly that for string/bool/null/object/
    array trees. This is not a general-purpose JCS implementation and must
    not be reused for payloads that may contain numbers.
    """

    for key in payload:
        assert not isinstance(payload[key], float), (
            f"{key}: JCS number formatting is out of scope for this helper; "
            "decision_payload never contains numbers"
        )
    text = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def _content_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_jcs_canonicalize(payload)).hexdigest()


def test_synthetic_example_validates_against_the_decision_payload_schema() -> None:
    module = _load_schema_test_module()
    schema = module._load_schema()
    payload = _load_example_decision_payload()
    module._assert_valid(payload, schema)


def test_synthetic_example_matches_the_existing_decision_payload_key_contract() -> None:
    module = _load_schema_test_module()
    payload = _load_example_decision_payload()
    reference_keys = module._load_decision_payload_keys_reference()
    assert set(payload) == reference_keys


def test_digest_is_deterministic_across_repeated_computation() -> None:
    payload = _load_example_decision_payload()
    first = _content_digest(payload)
    second = _content_digest(copy.deepcopy(payload))
    assert first == second
    assert len(first) == 64
    assert first == first.lower()
    assert all(character in "0123456789abcdef" for character in first)


def test_digest_is_independent_of_input_key_order() -> None:
    payload = _load_example_decision_payload()
    reordered = json.loads(json.dumps(payload))  # fresh dict, insertion order preserved
    shuffled = dict(reversed(list(reordered.items())))
    shuffled["controller_identity_and_institutional_contact"] = dict(
        reversed(list(shuffled["controller_identity_and_institutional_contact"].items()))
    )
    assert _content_digest(payload) == _content_digest(shuffled)


def test_digest_changes_when_any_field_changes() -> None:
    baseline = _content_digest(_load_example_decision_payload())
    for key in _load_example_decision_payload():
        if key in {"payload_schema_version", "purpose"}:
            continue  # const/enum fields under this schema; not meaningful to mutate here
        mutated = _load_example_decision_payload()
        mutated[key] = {"mutated_for_test": key}
        assert _content_digest(mutated) != baseline, f"digest did not change when {key} changed"


def test_digest_excludes_governance_envelope_fields_by_construction() -> None:
    """A materializer cannot influence the digest by editing envelope fields.

    content_digest is defined over decision_payload alone (digest_contract:
    governance_envelope_is_excluded=true). Since the schema's root object
    has no properties for content_digest/purpose_status/controller_approved/
    human_packet_complete/catalog_ready/writer_eligible/
    nominal_approval_record_refs, they cannot appear inside the object that
    gets canonicalized in the first place -- this test simply demonstrates
    that fact for the synthetic example instance actually used above.
    """

    payload = _load_example_decision_payload()
    for envelope_field in (
        "content_digest",
        "purpose_status",
        "controller_approved",
        "human_packet_complete",
        "catalog_ready",
        "writer_eligible",
        "nominal_approval_record_refs",
    ):
        assert envelope_field not in payload


def test_reference_content_digest_for_the_synthetic_example_is_reproduced() -> None:
    """Pins today's digest of the checked-in synthetic example.

    This is not an "official" digest for any real church -- see the module
    docstring. It only proves the pipeline is reproducible: if this assertion
    ever fails, either the example file changed or the canonicalizer changed,
    and both are worth a human look before trusting the next digest.
    """

    payload = _load_example_decision_payload()
    digest = _content_digest(payload)
    assert digest == "cde60f0db986a8777cc1109da78b2b9a7a970af26f3e515a1465678459efde35"

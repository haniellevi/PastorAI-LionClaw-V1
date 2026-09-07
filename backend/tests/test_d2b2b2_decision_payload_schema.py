"""Structural tests for the d2b2b2/decision-payload/v1 JSON Schema.

This schema was missing: docs/governance/consent/d2b2b2-decision-packet.template.json
declares `decision_payload_schema_version: d2b2b2/decision-payload/v1` in its
digest_contract, but no versioned schema file existed for it. This test file
validates the newly authored schema (docs/governance/consent/
d2b2b2-decision-payload.schema.json) against a synthetic example, and proves
the negative cases the mission asked for: forbidden identity fields are
rejected, and the derived/governance-envelope indicators cannot be smuggled
into decision_payload.

No `jsonschema` package is declared in backend/requirements*.txt, so a small
recursive validator implementing only the JSON Schema 2020-12 keywords this
particular schema actually uses ($ref, type, const, enum, pattern, not,
minLength, minProperties, minItems, required, properties,
additionalProperties, propertyNames, items, anyOf) is used instead of adding
a new dependency for a documentation-only artifact.

This file makes no network call, touches no database, and materializes no
real tenant. All identifiers are synthetic.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "consent"
    / "d2b2b2-decision-payload.schema.json"
)
DECISION_PACKET_DOCS_TEST_PATH = (
    Path(__file__).resolve().parent / "test_d2b2b2_decision_packet_docs.py"
)


def _load_schema() -> dict[str, Any]:
    raw = SCHEMA_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def _load_decision_payload_keys_reference() -> frozenset[str]:
    """Import DECISION_PAYLOAD_KEYS from the sibling doc test, without a package.

    This is the closed key set the existing template/test contract already
    enforces (backend/tests/test_d2b2b2_decision_packet_docs.py). Cross
    checking against it, instead of retyping the list, is what keeps this new
    schema from silently drifting away from the contract already implemented.
    """

    spec = importlib.util.spec_from_file_location(
        "_d2b2b2_decision_packet_docs_reference",
        DECISION_PACKET_DOCS_TEST_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.DECISION_PAYLOAD_KEYS)


class SchemaValidationError(AssertionError):
    """Raised by _validate when an instance does not satisfy a schema."""


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/$defs/"), f"unsupported $ref: {ref}"
        return root["$defs"][ref[len("#/$defs/") :]]
    return schema


_PY_TYPE_BY_JSON_TYPE = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _check_type(instance: Any, json_type: str) -> bool:
    if json_type == "integer":
        return type(instance) is int
    if json_type == "number":
        return type(instance) in (int, float) and type(instance) is not bool
    expected = _PY_TYPE_BY_JSON_TYPE[json_type]
    if json_type == "boolean":
        return type(instance) is bool
    if type(instance) is bool and json_type != "boolean":
        return False
    return isinstance(instance, expected)


def _validate(instance: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> None:
    schema = _resolve(schema, root)

    if "const" in schema:
        if instance != schema["const"]:
            raise SchemaValidationError(f"{path}: expected const {schema['const']!r}")

    if "enum" in schema:
        if instance not in schema["enum"]:
            raise SchemaValidationError(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_check_type(instance, t) for t in types):
            raise SchemaValidationError(f"{path}: expected type {types}, got {type(instance).__name__}")

    if "pattern" in schema:
        if type(instance) is str and re.search(schema["pattern"], instance) is None:
            raise SchemaValidationError(f"{path}: {instance!r} does not match pattern {schema['pattern']!r}")

    if "minLength" in schema and type(instance) is str:
        if len(instance) < schema["minLength"]:
            raise SchemaValidationError(f"{path}: string shorter than minLength")

    if "minItems" in schema and type(instance) is list:
        if len(instance) < schema["minItems"]:
            raise SchemaValidationError(f"{path}: array shorter than minItems")

    if "minProperties" in schema and type(instance) is dict:
        if len(instance) < schema["minProperties"]:
            raise SchemaValidationError(f"{path}: object has fewer than minProperties")

    if "anyOf" in schema:
        errors = []
        for index, subschema in enumerate(schema["anyOf"]):
            try:
                _validate(instance, subschema, root, f"{path}/anyOf[{index}]")
                break
            except SchemaValidationError as exc:
                errors.append(str(exc))
        else:
            raise SchemaValidationError(f"{path}: no branch of anyOf matched: {errors}")

    if "not" in schema:
        try:
            _validate(instance, schema["not"], root, f"{path}/not")
        except SchemaValidationError:
            pass
        else:
            raise SchemaValidationError(f"{path}: instance must not validate against 'not' schema")

    if type(instance) is dict:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for field in required:
            if field not in instance:
                raise SchemaValidationError(f"{path}: missing required property {field!r}")

        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if "propertyNames" in schema:
                _validate(key, schema["propertyNames"], root, f"{path}/propertyNames")
            if key in properties:
                _validate(value, properties[key], root, f"{path}.{key}")
            elif additional is False:
                raise SchemaValidationError(f"{path}: additional property {key!r} not allowed")
            elif additional is True:
                continue
            else:
                _validate(value, additional, root, f"{path}.{key}")

    if type(instance) is list and "items" in schema:
        for index, item in enumerate(instance):
            _validate(item, schema["items"], root, f"{path}[{index}]")


def _assert_valid(instance: Any, schema: dict[str, Any]) -> None:
    _validate(instance, schema, schema)


def _assert_invalid(instance: Any, schema: dict[str, Any]) -> None:
    with pytest.raises(SchemaValidationError):
        _validate(instance, schema, schema)


def _synthetic_uuid(suffix: str) -> str:
    return f"00000000-0000-4000-8000-{suffix:0>12}"


def _minimal_valid_payload() -> dict[str, Any]:
    """A synthetic, fully fictitious tarefas_operacionais decision_payload.

    Every identifier is an obviously-fake UUID or opaque ref string. No real
    CNPJ, name, phone, or e-mail appears anywhere in this module.
    """

    return {
        "payload_schema_version": "d2b2b2/decision-payload/v1",
        "purpose": "tarefas_operacionais",
        "package_id": _synthetic_uuid("1"),
        "package_version": "1.0.0",
        "supersedes_content_digest": None,
        "tenant_binding": _synthetic_uuid("2"),
        "controller_identity_and_institutional_contact": {
            "controller_legal_name": "Igreja Exemplo",
            "institutional_contact_channel_ref": "ref:institutional-contact:example",
        },
        "real_processing_agents": "ref:governance:real-processing-agents:example",
        "operations_and_minimum_data": {"celula": ["igreja_ref", "celula_ref", "reuniao_ref"]},
        "data_sensitivity_assessment": "ref:governance:sensitivity:example",
        "legal_hypothesis_common_data": "lgpd_art_7_i_consent",
        "legal_hypothesis_sensitive_data": "lgpd_art_11_i_specific_highlighted_consent",
        "consent_based_operation": True,
        "notice_texts_by_channel_and_language": {
            "whatsapp": {"pt-BR": "Texto de exemplo do aviso no WhatsApp."},
            "painel": {"pt-BR": "Texto de exemplo do aviso no painel."},
        },
        "refusal_rights_and_withdrawal": "ref:governance:refusal-and-withdrawal:example",
        "presentation_and_manifestation_evidence_contract": "ref:governance:evidence-contract:example",
        "children_adolescents_unknown_age_and_guardian_policy": {
            "applicability_status": "APPLICABLE",
            "justification": "ref:governance:minor-justification:example",
            "evidence_ref": "ref:evidence:minor:example",
            "reviewer_record_ref": "ref:approval:minor-reviewer:example",
            "best_interest_assessment_ref": "ref:assessment:best-interest:example",
            "age_or_guardian_measures": "ref:governance:guardian-measures:example",
            "risk_and_impact_assessment_ref": "ref:assessment:risk-impact:example",
        },
        "validity_expiration_material_change_and_reacceptance": "ref:governance:validity:example",
        "retention_and_disposal_matrix": {
            "ledger": "ref:retention:ledger:example",
            "evidence": "ref:retention:evidence:example",
            "messages": "ref:retention:messages:example",
            "media": "ref:retention:media:example",
            "transcripts": "ref:retention:transcripts:example",
            "summaries": "ref:retention:summaries:example",
            "checkpoints": "ref:retention:checkpoints:example",
            "vectors": "ref:retention:vectors:example",
            "logs": "ref:retention:logs:example",
            "dead_letter": "ref:retention:dead-letter:example",
            "backups": "ref:retention:backups:example",
        },
        "optout_withdrawal_deletion_legal_hold_and_reactivation": "ref:governance:optout:example",
        "international_transfer_inventory_and_mechanism": "ref:governance:transfer-inventory:example",
        "rights_incidents_and_periodic_review_owners": "ref:governance:rights-incidents:example",
        "rbac_by_action_and_scope": "ref:governance:rbac:example",
        "server_side_resource_binding_evidence": "ref:governance:server-side-binding:example",
        "durable_idempotency_receipt_policy": "ref:governance:idempotency-receipt:example",
        "ai_memory_and_tenant_isolation": "ref:governance:ai-memory-isolation:example",
    }


def test_schema_file_is_valid_json_and_declares_2020_12() -> None:
    schema = _load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_schema_required_keys_match_the_existing_template_contract() -> None:
    schema = _load_schema()
    reference_keys = _load_decision_payload_keys_reference()
    assert set(schema["required"]) == reference_keys
    assert set(schema["properties"]) == reference_keys


def test_minimal_synthetic_payload_is_valid() -> None:
    schema = _load_schema()
    payload = _minimal_valid_payload()
    _assert_valid(payload, schema)


def test_payload_schema_version_is_fixed_const() -> None:
    schema = _load_schema()
    payload = _minimal_valid_payload()
    payload["payload_schema_version"] = "d2b2b2/decision-payload/v2"
    _assert_invalid(payload, schema)


@pytest.mark.parametrize(
    "field,value",
    [
        ("package_id", "not-a-uuid"),
        ("tenant_binding", "not-a-uuid"),
        ("package_version", "not-semver"),
        ("purpose", "finalidade_inexistente"),
        ("consent_based_operation", "true"),
    ],
)
def test_malformed_scalar_fields_are_rejected(field: str, value: Any) -> None:
    schema = _load_schema()
    payload = _minimal_valid_payload()
    payload[field] = value
    _assert_invalid(payload, schema)


def test_top_level_forbidden_identity_field_is_rejected() -> None:
    """additionalProperties: false blocks any key outside the closed contract."""

    schema = _load_schema()
    for forbidden_key, forbidden_value in (
        ("cpf", "111.111.111-11"),
        ("telefone_pessoal", "+5511999999999"),
        ("email_pessoal", "pessoa@example.com"),
        ("documento_civil", "RG 00.000.000-0"),
    ):
        payload = _minimal_valid_payload()
        payload[forbidden_key] = forbidden_value
        _assert_invalid(payload, schema)


def test_nested_forbidden_identity_field_name_is_rejected_in_freeform_content() -> None:
    """propertyNames on freeformGovernanceObject blocks PII keys inside narrative fields."""

    schema = _load_schema()
    for forbidden_key in ("cpf", "rg", "telefone_pessoal", "email_pessoal", "senha"):
        payload = _minimal_valid_payload()
        payload["operations_and_minimum_data"] = {forbidden_key: "111.111.111-11"}
        _assert_invalid(payload, schema)


def test_nested_forbidden_identity_field_is_rejected_in_controller_identity() -> None:
    """additionalProperties: false on the controller-identity object blocks PII keys too."""

    schema = _load_schema()
    payload = _minimal_valid_payload()
    payload["controller_identity_and_institutional_contact"]["cpf"] = "111.111.111-11"
    _assert_invalid(payload, schema)


def test_cpf_or_phone_shaped_value_is_rejected_in_opaque_ref() -> None:
    """Even under an allowed key, a CPF- or E.164-phone-shaped string is rejected."""

    schema = _load_schema()
    for forbidden_value in ("111.111.111-11", "+5511999999999"):
        payload = _minimal_valid_payload()
        payload["controller_identity_and_institutional_contact"][
            "institutional_contact_channel_ref"
        ] = forbidden_value
        _assert_invalid(payload, schema)


@pytest.mark.parametrize(
    "derived_indicator,value",
    [
        ("purpose_status", "CONTROLLER_APPROVED"),
        ("controller_approved", True),
        ("human_packet_complete", True),
        ("catalog_ready", True),
        ("writer_eligible", True),
        ("content_digest", "a" * 64),
        ("nominal_approval_record_refs", {}),
    ],
)
def test_derived_governance_envelope_indicators_cannot_be_filled_by_materializer(
    derived_indicator: str, value: Any
) -> None:
    """These belong beside decision_payload in the packet, never inside it.

    additionalProperties: false at the schema root means any attempt by a
    materializer to write purpose_status/controller_approved/
    human_packet_complete/catalog_ready/writer_eligible/content_digest/
    nominal_approval_record_refs into decision_payload itself is rejected.
    """

    schema = _load_schema()
    payload = _minimal_valid_payload()
    payload[derived_indicator] = value
    _assert_invalid(payload, schema)


def test_schema_documents_derived_indicators_as_read_only() -> None:
    schema = _load_schema()
    envelope_docs = schema["x-out-of-scope-governance-envelope-fields"]
    for indicator in (
        "purpose_status",
        "controller_approved",
        "human_packet_complete",
        "catalog_ready",
        "writer_eligible",
        "content_digest",
        "nominal_approval_record_refs",
    ):
        assert envelope_docs[indicator]["readOnly"] is True


def test_children_policy_rejects_unknown_applicability_status() -> None:
    schema = _load_schema()
    payload = _minimal_valid_payload()
    payload["children_adolescents_unknown_age_and_guardian_policy"][
        "applicability_status"
    ] = "MAYBE"
    _assert_invalid(payload, schema)


def test_retention_matrix_requires_exactly_the_eleven_canonical_surfaces() -> None:
    schema = _load_schema()

    missing_surface = _minimal_valid_payload()
    del missing_surface["retention_and_disposal_matrix"]["backups"]
    _assert_invalid(missing_surface, schema)

    extra_surface = _minimal_valid_payload()
    extra_surface["retention_and_disposal_matrix"]["unexpected_surface"] = "ref:example"
    _assert_invalid(extra_surface, schema)


def test_supersedes_content_digest_accepts_null_or_sha256_hex_only() -> None:
    schema = _load_schema()

    ok = _minimal_valid_payload()
    ok["supersedes_content_digest"] = "0" * 64
    _assert_valid(ok, schema)

    bad = _minimal_valid_payload()
    bad["supersedes_content_digest"] = "not-a-digest"
    _assert_invalid(bad, schema)


def test_no_real_data_leaked_into_this_test_module() -> None:
    """Only the deliberately fake CPF (111.111.111-11) and phone (+5511999999999) appear."""

    raw = Path(__file__).read_text(encoding="utf-8")
    cpf_matches = set(re.findall(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", raw))
    phone_matches = set(re.findall(r"\+55\d{10,11}", raw))
    assert cpf_matches == {"111.111.111-11"}
    assert phone_matches == {"+5511999999999"}

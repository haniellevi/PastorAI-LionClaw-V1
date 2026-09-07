"""Documentary proof only: no production validator, runtime, network or database.

The existing project's small JSON Schema keyword interpreter validates the
structural schemas; semantic checks below validate closure and digest binding.
This is not a general JSON Schema or general JCS implementation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from tests import test_d2b2b2_decision_payload_schema as payload_contract

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/governance/consent/catalog"
EXAMPLE = CATALOG / "examples/igreja-exemplo.synthetic-example.json"
PINNED_ENTRY = "853af6d70c2aed392930aea4c7f2f2515518bbe2eb27c4d0055a17940bd32c43"
PINNED_CONTENT = "4e02e55ee583b75198afb2be57bf80e21161e892104742149709655196b9061b"
REF_PATTERN = re.compile(r"ref:[a-z0-9][a-z0-9:-]*", re.ASCII)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, "duplicate JSON key"
        result[key] = value
    return result


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)


def _canonical(value):
    """JCS subset: UTF-16 key order, UTF-8 strings, no numbers or surrogates.

    Fail closed on every numeric leaf, including nested numbers. No Unicode
    normalization is performed. Extending this profile needs separate review.
    """
    if value is None or type(value) is bool:
        return json.dumps(value)
    if type(value) is str:
        value.encode("utf-8", "strict")
        return json.dumps(value, ensure_ascii=False)
    if type(value) is list:
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    assert type(value) is dict, "unsupported canonical value"
    assert all(type(key) is str for key in value), "non-string JSON key"
    for key in value:
        key.encode("utf-8", "strict")
    keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
    return "{" + ",".join(_canonical(key) + ":" + _canonical(value[key]) for key in keys) + "}"


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _entry_digest(entry):
    return _digest({key: value for key, value in entry.items() if key != "entry_digest"})


def _refs(value):
    if type(value) is str:
        if "ref:" in value:
            assert REF_PATTERN.fullmatch(value), "embedded or malformed reference"
            return {value}
        return set()
    if type(value) is list:
        return set().union(*(_refs(item) for item in value))
    if type(value) is dict:
        assert all("ref:" not in key for key in value), "reference used as key"
        return set().union(*(_refs(item) for item in value.values()))
    return set()


def _replace_refs(value, bindings):
    if type(value) is str:
        return bindings.get(value, value)
    if type(value) is list:
        return [_replace_refs(item, bindings) for item in value]
    if type(value) is dict:
        return {key: _replace_refs(item, bindings) for key, item in value.items()}
    return value


def _validate(entry, *, anchor=None, previous=None):
    schema = _load(CATALOG / "catalog-entry.schema.json")
    payload_contract._assert_valid(entry, schema)
    payload_schema = payload_contract._load_schema()
    for payload in (entry["source_payload"], entry["decision_payload"]):
        payload_contract._assert_valid(payload, payload_schema)
        _canonical(payload)
        for key in ("tenant_binding", "purpose", "package_id", "package_version"):
            assert payload[key] == entry[key], "binding mismatch"

    source_refs = _refs(entry["source_payload"])
    rows = entry["resolved_refs"]
    assert 0 < len(rows) <= 128, "reference count outside design profile"
    assert len({row["source_ref"] for row in rows}) == len(rows), "duplicate source ref"
    assert [row["source_ref"] for row in rows] == sorted(row["source_ref"] for row in rows), "noncanonical ref order"
    assert source_refs == {row["source_ref"] for row in rows}, "dangling or extra reference"
    assert not any(ref.startswith("ref:catalog:") for ref in source_refs), "source aliases must be opaque"
    bindings = {}
    pending = False
    for row in rows:
        if row["state"] == "PENDING_EXTERNAL":
            pending = True
            bindings[row["source_ref"]] = row["source_ref"]
            continue
        assert not _refs(row["content"]), "nested ref/cycle forbidden"
        digest = _digest(row["content"])
        assert row["content_sha256"] == digest, "resolved content changed"
        assert row["bound_ref"] == "ref:catalog:sha256:" + digest, "content address mismatch"
        bindings[row["source_ref"]] = row["bound_ref"]
    assert entry["decision_payload"] == _replace_refs(entry["source_payload"], bindings), "payload resolution mismatch"
    if pending:
        assert entry["status"] == "DRAFT_PENDING_EXTERNAL", "pending ref cannot freeze"
        assert entry["content_digest"] is None and entry["entry_digest"] is None
        assert anchor is None, "pending draft cannot satisfy a frozen anchor"
    else:
        assert entry["status"] == "SYNTHETIC_FROZEN"
        assert entry["content_digest"] == _digest(entry["decision_payload"]), "payload digest mismatch"
        assert entry["entry_digest"] == _entry_digest(entry), "entry digest mismatch"
        if anchor is not None:
            assert entry["entry_digest"] == anchor, "immutable anchor changed"

    prior = entry["supersedes"]
    if prior is None:
        assert entry["decision_payload"]["supersedes_content_digest"] is None
        assert previous is None
    else:
        assert previous is not None, "missing predecessor"
        assert previous["status"] == "SYNTHETIC_FROZEN"
        assert previous["entry_digest"] == _entry_digest(previous)
        assert prior == {key: previous[key] for key in ("entry_id", "entry_digest", "content_digest")}
        assert entry["decision_payload"]["supersedes_content_digest"] == previous["content_digest"]
        assert entry["tenant_binding"] == previous["tenant_binding"]
        assert entry["purpose"] == previous["purpose"]
        assert entry["package_id"] == previous["package_id"]
        assert entry["entry_id"] != previous["entry_id"], "entry identity reused"
        assert tuple(map(int, entry["package_version"].split("."))) > tuple(map(int, previous["package_version"].split(".")))


def _append_only(previous_entries, candidate_entries):
    """Compare against a caller-provided trusted prior snapshot, not itself."""
    assert len({entry["entry_id"] for entry in candidate_entries}) == len(candidate_entries)
    by_id = {entry["entry_id"]: entry for entry in candidate_entries}
    for prior in previous_entries:
        assert prior["entry_id"] in by_id, "frozen entry removed"
        current = by_id[prior["entry_id"]]
        assert _canonical(current) == _canonical(prior), "frozen entry modified"


def test_catalog_schema_and_complete_synthetic_example():
    schema = _load(CATALOG / "catalog-entry.schema.json")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    entry = _load(EXAMPLE)
    _validate(entry, anchor=PINNED_ENTRY)
    assert entry["content_digest"] == PINNED_CONTENT
    assert len(entry["resolved_refs"]) == 31
    assert entry["source_payload"]["controller_identity_and_institutional_contact"]["controller_legal_name"] == "Igreja Exemplo"


def test_existing_payload_digest_contract_is_not_redefined():
    template = _load(CATALOG.parent / "d2b2b2-decision-packet.template.json")
    assert template["digest_contract"]["scope"] == "single_purpose_packet_decision_payload_only"
    assert template["digest_contract"]["governance_envelope_is_excluded"] is True
    entry = _load(EXAMPLE)
    assert _digest(entry["source_payload"]) != entry["content_digest"]
    assert _digest(entry["decision_payload"]) == entry["content_digest"]
    assert _entry_digest(entry) != entry["content_digest"]


@pytest.mark.parametrize("field", ["controller_approved", "human_packet_complete", "catalog_ready", "writer_eligible", "operational_authorization", "next_stage_authorized"])
@pytest.mark.parametrize("value", [True, 1, "true"])
def test_approval_and_authority_indicators_cannot_be_enabled(field, value):
    entry = _load(EXAMPLE)
    entry[field] = value
    with pytest.raises(AssertionError):
        _validate(entry)


@pytest.mark.parametrize("mutation", ["content", "payload", "tenant", "purpose", "digest", "address", "unknown_field"])
def test_tampering_invalidates_frozen_entry(mutation):
    entry = _load(EXAMPLE)
    if mutation == "content":
        entry["resolved_refs"][0]["content"]["text"] += " altered"
    elif mutation == "payload":
        entry["decision_payload"]["notice_texts_by_channel_and_language"]["painel"]["pt-BR"] += " altered"
    elif mutation in {"tenant", "purpose"}:
        entry[{"tenant": "tenant_binding", "purpose": "purpose"}[mutation]] = "00000000-0000-4000-8000-000000000999" if mutation == "tenant" else "comunicados"
    elif mutation == "digest":
        entry["content_digest"] = "0" * 64
    elif mutation == "address":
        entry["resolved_refs"][0]["bound_ref"] = "ref:catalog:sha256:" + "0" * 64
    else:
        entry["unrecognized"] = False
    with pytest.raises(AssertionError):
        _validate(entry, anchor=PINNED_ENTRY)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "cycle", "embedded"])
def test_dangling_ambiguous_or_nested_references_are_rejected(mutation):
    entry = _load(EXAMPLE)
    if mutation == "missing":
        entry["resolved_refs"].pop()
    elif mutation in {"extra", "duplicate"}:
        row = copy.deepcopy(entry["resolved_refs"][0])
        if mutation == "extra":
            row["source_ref"] = "ref:unknown:synthetic"
        entry["resolved_refs"].append(row)
    elif mutation == "cycle":
        entry["resolved_refs"][0]["content"]["text"] = entry["resolved_refs"][0]["source_ref"]
    else:
        entry["source_payload"]["ai_memory_and_tenant_isolation"] = "Veja ref:missing:synthetic"
    with pytest.raises(AssertionError):
        _validate(entry)


def test_external_pending_reference_is_explicit_and_cannot_freeze():
    entry = _load(EXAMPLE)
    row = entry["resolved_refs"][0]
    row.update(state="PENDING_EXTERNAL", bound_ref=None, content=None, content_sha256=None, pending_reason="Custodia externa ainda nao materializada.")
    bindings = {item["source_ref"]: item["bound_ref"] or item["source_ref"] for item in entry["resolved_refs"]}
    entry["decision_payload"] = _replace_refs(entry["source_payload"], bindings)
    entry.update(status="DRAFT_PENDING_EXTERNAL", content_digest=None, entry_digest=None)
    _validate(entry)
    entry["status"] = "SYNTHETIC_FROZEN"
    with pytest.raises(AssertionError, match="pending ref cannot freeze"):
        _validate(entry)


def test_reference_order_is_canonical_even_if_rehashed():
    entry = _load(EXAMPLE)
    entry["resolved_refs"].reverse()
    entry["entry_digest"] = _entry_digest(entry)
    with pytest.raises(AssertionError, match="noncanonical ref order"):
        _validate(entry)


def test_edit_and_rehash_cannot_replace_trusted_frozen_entry():
    original = _load(EXAMPLE)
    altered = copy.deepcopy(original)
    row = altered["resolved_refs"][0]
    row["content"]["text"] += " different synthetic revision"
    row["content_sha256"] = _digest(row["content"])
    row["bound_ref"] = "ref:catalog:sha256:" + row["content_sha256"]
    altered["decision_payload"] = _replace_refs(altered["source_payload"], {r["source_ref"]: r["bound_ref"] for r in altered["resolved_refs"]})
    altered["content_digest"] = _digest(altered["decision_payload"])
    altered["entry_digest"] = _entry_digest(altered)
    _validate(altered)  # Self-consistency is not trusted immutability.
    with pytest.raises(AssertionError, match="immutable anchor changed"):
        _validate(altered, anchor=PINNED_ENTRY)
    with pytest.raises(AssertionError, match="frozen entry modified"):
        _append_only([original], [altered])


def test_superseding_version_appends_without_replacing_history():
    prior = _load(EXAMPLE)
    successor = copy.deepcopy(prior)
    successor["entry_id"] = "00000000-0000-4000-8000-000000000404"
    successor["package_version"] = "1.0.1"
    successor["supersedes"] = {key: prior[key] for key in ("entry_id", "entry_digest", "content_digest")}
    for key in ("source_payload", "decision_payload"):
        successor[key]["package_version"] = "1.0.1"
        successor[key]["supersedes_content_digest"] = prior["content_digest"]
    successor["content_digest"] = _digest(successor["decision_payload"])
    successor["entry_digest"] = _entry_digest(successor)
    _validate(successor, previous=prior)
    _append_only([prior], [prior, successor])
    with pytest.raises(AssertionError, match="frozen entry removed"):
        _append_only([prior], [successor])
    with pytest.raises(AssertionError, match="missing predecessor"):
        _validate(successor)


def test_canonicalization_orders_utf16_and_rejects_numbers_and_duplicate_keys():
    assert _digest({"a": True, "b": None}) == _digest({"b": None, "a": True})
    # UTF-16 order differs from Unicode code-point order for these keys.
    assert _canonical({"\ue000": None, "\U00010000": True}) == '{"\U00010000":true,"\ue000":null}'
    for bad in (1, 1.5, float("nan"), {"nested": [1]}, {1: "key"}):
        with pytest.raises(AssertionError):
            _canonical(bad)
    with pytest.raises(UnicodeError):
        _canonical("\ud800")
    with pytest.raises(AssertionError, match="duplicate JSON key"):
        json.loads('{"a":false,"a":true}', object_pairs_hook=_pairs)


def test_contract_documents_external_boundaries_and_no_real_data():
    contract = (CATALOG / "CONTRACT.md").read_text(encoding="utf-8")
    for phrase in ("PENDING_EXTERNAL", "content_digest", "entry_digest", "supersedes", "catalog_ready=false", "writer_eligible=false", "DRAFT_NOT_APPROVED"):
        assert phrase in contract
    example = EXAMPLE.read_text(encoding="utf-8")
    assert "Filad" not in example
    assert not re.search(r"\+\d{8,}|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|[\w.+-]+@[\w.-]+", example)

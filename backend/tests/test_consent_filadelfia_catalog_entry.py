"""Read-only documentary entry checks; never load vault, signature or payload.

RESOLVED_FROZEN hashes exact UTF-8 section bytes, including heading and trailing
whitespace, up to the next heading of equal/higher level. Frozen source:
94df2ff1fa803754dddf8469d45889ba14f9d6f4, identical at base 05b7e2a.
Only policy text is bound: these tests do not attest factual completeness,
custody manifests, signature authenticity or the approved payload digest.
"""

import hashlib
import re

import pytest

from tests import test_consent_immutable_catalog as catalog

ENTRY = catalog.CATALOG / "entries/filadelfia-tarefas-operacionais-v1.json"
DOCUMENT = catalog.ROOT / "docs/governance/consent/d2b2b2-decision-packet-tarefas-operacionais.md"
ENTRY_ANCHOR = "bef0ba54ee9252ca6219396271f478f99d9e568efaf24a85051bc984092a8011"
DOCUMENT_ANCHOR = "749f425921b154bd42d69abf04dae647fffe138ec09dbc9065ef6971ecfec0ad"
APPROVED_DIGEST = "17f260b24528508899a17dffbc49099e82ece7bf7d26c72dd966694b3c377a7f"
SOURCE_PREFIX = "ref:git:94df2ff1fa803754dddf8469d45889ba14f9d6f4:d2b2b2-decision-packet-tarefas-operacionais:section-"
SECTIONS = ("4", "5", "6", "7", "10", "11", "12", "12-1", "13", "14",
            "15", "16", "16-3", "17", "18-1", "18-2", "18-3", "19", "20")
EXTERNAL = "ref:governanca-local:filadelfia-registro-externo"


def test_real_entry_schema_bindings_and_pinned_entry_digest():
    entry = catalog._load(ENTRY)
    catalog.payload_contract._assert_valid(
        entry, catalog._load(catalog.CATALOG / "catalog-entry.schema.json"))
    assert catalog._entry_digest(entry) == entry["entry_digest"] == ENTRY_ANCHOR
    assert entry["content_digest"] == APPROVED_DIGEST  # Compare only; do not rehash payload.
    assert entry["source_payload"] == entry["decision_payload"] == {
        "custody_ref": "ref:sha256:113f53f631703a734f3cda1f95dd1ef86c9470a837b1c1f5aa9e9fb0b603a919",
        "content_digest": APPROVED_DIGEST,
    }
    assert entry["approval_custody_ref"] == "ref:sha256:ec1573f6170b212c1148f35bd13e3a952908d376d04cca09360b78b1280e4d5e"
    assert entry["tenant_binding"] == "228ebda0-92c1-422c-8ab4-78fdc06c1b8e"
    assert entry["package_id"] == "d47ae9ec-f438-47c6-b915-d4f96fdb7301"
    assert entry["package_version"] == "1.0.0"
    assert entry["purpose"] == "tarefas_operacionais"
    assert entry["synthetic_only"] is False and entry["controller_approved"] is True
    assert entry["supersedes"] is None
    assert entry["status"] == "APPROVED_PAYLOAD_PENDING_EXTERNAL"


@pytest.mark.parametrize("field", [
    "human_packet_complete", "catalog_ready", "writer_eligible",
    "operational_authorization", "next_stage_authorized",
])
def test_real_entry_technical_gates_remain_closed(field):
    entry = catalog._load(ENTRY)
    assert entry[field] is False
    entry[field] = True
    with pytest.raises(AssertionError):
        catalog.payload_contract._assert_valid(
            entry, catalog._load(catalog.CATALOG / "catalog-entry.schema.json"))


def test_real_entry_exact_reference_inventory_and_explicit_pending():
    rows = catalog._load(ENTRY)["resolved_refs"]
    assert [r["source_ref"] for r in rows] == sorted(
        [SOURCE_PREFIX + section for section in SECTIONS] + [EXTERNAL])
    pending = [r for r in rows if r["state"] == "PENDING_EXTERNAL"]
    assert len(pending) == 1 and pending[0]["source_ref"] == EXTERNAL
    assert pending[0]["pending_reason"].strip()
    assert all(pending[0][k] is None for k in ("content", "content_sha256", "bound_ref"))


def test_real_entry_resolved_sections_match_frozen_document_bytes():
    raw = DOCUMENT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DOCUMENT_ANCHOR
    headings = list(re.finditer(rb"^(#{1,6}) ([0-9]+(?:\.[0-9]+)*)\.? ", raw, re.M))
    for row in catalog._load(ENTRY)["resolved_refs"]:
        if row["state"] == "PENDING_EXTERNAL":
            continue
        assert row["state"] == "RESOLVED_FROZEN"
        section = row["source_ref"][len(SOURCE_PREFIX):].replace("-", ".").encode()
        matches = [(i, h) for i, h in enumerate(headings) if h.group(2) == section]
        assert len(matches) == 1
        i, start = matches[0]
        end = next((h.start() for h in headings[i+1:]
                    if len(h.group(1)) <= len(start.group(1))), len(raw))
        digest = hashlib.sha256(raw[start.start():end]).hexdigest()
        assert row["content_sha256"] == digest
        assert row["content_ref"] == "ref:sha256:" + digest
        assert row["pending_reason"] is None


def test_real_entry_contains_only_pointers_and_no_contact_values():
    raw = ENTRY.read_text()
    assert not re.search(r"[\w.+-]+@[\w.-]+|\+\d{8,}|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", raw)
    entry = catalog._load(ENTRY)
    assert set(entry["source_payload"]) == {"custody_ref", "content_digest"}
    assert set(entry["decision_payload"]) == {"custody_ref", "content_digest"}
    assert all("content" not in r for r in entry["resolved_refs"] if r["state"] == "RESOLVED_FROZEN")

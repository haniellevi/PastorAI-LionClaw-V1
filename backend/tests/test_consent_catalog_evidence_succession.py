"""Offline append-only proof; never reads vault or hashes approved payload."""
import copy
import hashlib
import pytest
from tests import test_consent_immutable_catalog as c

V1 = c.CATALOG / "entries/filadelfia-tarefas-operacionais-v1.json"
V2 = c.CATALOG / "entries/filadelfia-tarefas-operacionais-v2.json"
V1_ANCHOR = "bef0ba54ee9252ca6219396271f478f99d9e568efaf24a85051bc984092a8011"
V1_BYTES = "a69f29274d0f882fbaef9131c79252f0b5d3e94ec9cc71fc8d51502e53bc5755"
V2_ANCHOR = "0d09c0017c8c6aa82e2acb7c547c8071bb8740960f0e32eaa4e4e131f895a802"
APPROVED = "17f260b24528508899a17dffbc49099e82ece7bf7d26c72dd966694b3c377a7f"
CONTENT_ANCHORS = {
    "ref:governanca-local:filadelfia-registro-externo": "aae55a92aeb964e282b0dca116498f5788eaa10ce9670f7495d6cd361349f7fd",
    "ref:governanca-local:filadelfia-avaliacao-melhor-interesse": "d5ac93200af11fb46cfbace09aa95a964fb4f5f693425094c1b56ef67bcf8abb",
    "ref:governanca-local:filadelfia-avaliacao-risco-impacto": "055b6afad8ea04d47f7a5e8d13dee81ae9cd4d90356ab12bdcb227483625a700",
    "ref:governanca-local:filadelfia-manifesto-vinculo-custodia": "12dad79787d3cd88b04a9bd7b452f49b1d2078e0aba5936c0ecf665ade2299d6"
}
EXTERNAL = "ref:governanca-local:filadelfia-registro-externo"
ADDITIONAL = frozenset(CONTENT_ANCHORS) - {EXTERNAL}
LIMITATIONS = ["APPROVED_PAYLOAD_MINOR_REFS_UNCHANGED_NULL","SUPPLEMENTAL_EVIDENCE_OUTSIDE_APPROVED_PAYLOAD","NO_TECHNICAL_OR_OPERATIONAL_AUTHORITY"]


def _validate_successor(entry, *, previous, previous_anchor, approved_digest,
                        allowed_new_evidence, content_anchors, anchor=None):
    """Inputs must come from independent trusted snapshots, not candidate."""
    schema = c._load(c.CATALOG / "catalog-entry.schema.json")
    c.payload_contract._assert_valid(entry, schema)
    c.payload_contract._assert_valid(previous, schema)
    assert entry["schema_version"] == "consent-catalog/evidence-succession-v1"
    assert previous["schema_version"] in {
        "consent-catalog/frozen-payload-v2", "consent-catalog/evidence-succession-v1"}
    assert c._entry_digest(previous) == previous["entry_digest"] == previous_anchor, "untrusted predecessor"
    assert entry["supersedes"] == {k: previous[k] for k in (
        "entry_id", "entry_digest", "content_digest")}, "predecessor mismatch"
    assert entry["entry_id"] != previous["entry_id"], "identity reused"
    assert int(entry["catalog_revision"]) == int(previous.get("catalog_revision", "1")) + 1
    for key in ("tenant_binding", "purpose", "package_id", "package_version",
                "content_digest", "source_payload", "decision_payload",
                "approval_custody_ref", "synthetic_only", "controller_approved"):
        assert entry[key] == previous[key], "approved binding changed"
    assert entry["content_digest"] == approved_digest
    assert entry["source_payload"] == entry["decision_payload"]
    assert entry["source_payload"]["content_digest"] == approved_digest
    assert entry["limitations"] == LIMITATIONS
    old_rows = previous["resolved_refs"]
    old_refs = [r["source_ref"] for r in old_rows]
    assert old_refs == sorted(set(old_refs))
    rows = entry["resolved_refs"]
    refs = [r["source_ref"] for r in rows]
    assert 0 < len(refs) <= 128
    assert refs == sorted(set(refs))
    added = set(refs) - set(old_refs)
    assert added == set(allowed_new_evidence), "unapproved evidence"
    assert set(old_refs) <= set(refs), "ref removed"
    assert entry["evidence_only_refs"] == sorted(
        set(previous.get("evidence_only_refs", [])) | added)
    by_ref = {r["source_ref"]: r for r in rows}
    pending = set()
    for old in old_rows:
        if old["state"] == "RESOLVED_FROZEN":
            assert by_ref[old["source_ref"]] == old, "frozen content changed"
        else:
            assert old["state"] == "PENDING_EXTERNAL"
            pending.add(old["source_ref"])
    assert added or pending, "empty succession"
    for row in rows:
        assert row["state"] == "RESOLVED_FROZEN"
        assert row["content_ref"] == "ref:sha256:" + row["content_sha256"]
        if row["source_ref"] in added | pending:
            assert content_anchors.get(row["source_ref"]) == row["content_sha256"], "unverified content"
    assert c._entry_digest(entry) == entry["entry_digest"]
    if anchor is not None:
        assert entry["entry_digest"] == anchor, "immutable anchor changed"


def _check(entry, **overrides):
    args = dict(previous=c._load(V1), previous_anchor=V1_ANCHOR,
                approved_digest=APPROVED, allowed_new_evidence=ADDITIONAL,
                content_anchors=CONTENT_ANCHORS)
    args.update(overrides)
    _validate_successor(entry, **args)


def test_real_succession_has_23_resolved_refs_and_preserves_v1_bytes():
    assert hashlib.sha256(V1.read_bytes()).hexdigest() == V1_BYTES
    v1, v2 = c._load(V1), c._load(V2)
    _check(v2, anchor=V2_ANCHOR)
    assert len(v2["resolved_refs"]) == 23
    assert all(r["state"] == "RESOLVED_FROZEN" for r in v2["resolved_refs"])
    assert len(v2["evidence_only_refs"]) == 3
    c._append_only([v1], [v1, v2])
    with pytest.raises(AssertionError):
        c._append_only([v1], [v2])


@pytest.mark.parametrize("field", [
    "human_packet_complete", "catalog_ready", "writer_eligible",
    "operational_authorization", "next_stage_authorized",
])
@pytest.mark.parametrize("value", [True, 1, "true"])
def test_succession_never_opens_technical_gates(field, value):
    entry = c._load(V2)
    assert entry[field] is False
    entry[field] = value
    with pytest.raises(AssertionError):
        _check(entry)


@pytest.mark.parametrize("mutation", [
    "tenant", "purpose", "package", "package_version", "payload_pointer",
    "content_digest", "custody", "id_reuse", "revision_repeat", "revision_skip",
    "supersedes_null", "supersedes_hash", "supersedes_content", "supersedes_id",
    "remove_ref", "duplicate_ref", "ref_order", "alter_frozen", "new_hash",
    "extra_ref", "hide_supplemental", "hide_limitation", "pending_again",
    "extra_private_field",
])
def test_tampering_is_rejected_even_after_entry_rehash(mutation):
    e, p = c._load(V2), c._load(V1)
    if mutation in {"tenant", "package"}:
        e[{"tenant": "tenant_binding", "package": "package_id"}[mutation]] = "00000000-0000-4000-8000-000000000999"
    elif mutation == "purpose":
        e["purpose"] = "comunicados"
    elif mutation == "package_version":
        e["package_version"] = "9.0.0"
    elif mutation == "payload_pointer":
        e["source_payload"]["custody_ref"] = "ref:sha256:" + "0" * 64
    elif mutation == "content_digest":
        e["content_digest"] = "0" * 64
    elif mutation == "custody":
        e["approval_custody_ref"] = "ref:sha256:" + "0" * 64
    elif mutation == "id_reuse":
        e["entry_id"] = p["entry_id"]
    elif mutation.startswith("revision_"):
        e["catalog_revision"] = "1" if mutation == "revision_repeat" else "3"
    elif mutation == "supersedes_null":
        e["supersedes"] = None
    elif mutation.startswith("supersedes_"):
        key = {"supersedes_hash": "entry_digest", "supersedes_content": "content_digest",
               "supersedes_id": "entry_id"}[mutation]
        e["supersedes"][key] = "0" * 64 if key != "entry_id" else e["entry_id"]
    elif mutation == "remove_ref":
        e["resolved_refs"].pop(0)
    elif mutation == "duplicate_ref":
        e["resolved_refs"].append(copy.deepcopy(e["resolved_refs"][0]))
    elif mutation == "ref_order":
        e["resolved_refs"].reverse()
    elif mutation in {"alter_frozen", "new_hash"}:
        row = next(r for r in e["resolved_refs"] if
                   r["source_ref"].startswith("ref:git:") == (mutation == "alter_frozen"))
        row["content_sha256"] = "0" * 64
        row["content_ref"] = "ref:sha256:" + "0" * 64
    elif mutation == "extra_ref":
        row = copy.deepcopy(e["resolved_refs"][-1])
        row["source_ref"] = "ref:unexpected:evidence"
        e["resolved_refs"].append(row)
        e["resolved_refs"].sort(key=lambda r: r["source_ref"])
        e["evidence_only_refs"] = sorted(e["evidence_only_refs"] + [row["source_ref"]])
    elif mutation == "hide_supplemental":
        e["evidence_only_refs"] = []
    elif mutation == "hide_limitation":
        e["limitations"] = LIMITATIONS[:-1]
    elif mutation == "pending_again":
        e["resolved_refs"][0]["state"] = "PENDING_EXTERNAL"
    else:
        e["signature_pdf"] = "forbidden"
    e["entry_digest"] = c._entry_digest(e)
    with pytest.raises(AssertionError):
        _check(e)


def test_prior_trust_anchor_and_new_content_anchors_are_required():
    entry, prior = c._load(V2), c._load(V1)
    prior["entry_id"] = entry["entry_id"]
    prior["entry_digest"] = c._entry_digest(prior)
    with pytest.raises(AssertionError, match="untrusted predecessor"):
        _check(entry, previous=prior)
    with pytest.raises(AssertionError, match="unverified content"):
        _check(entry, content_anchors={})
    with pytest.raises(AssertionError):
        _check(entry, approved_digest="0" * 64)


def test_later_succession_appends_fictional_evidence_without_editing_prior():
    v1, v2 = c._load(V1), c._load(V2)
    v3 = copy.deepcopy(v2)
    ref, digest = "ref:synthetic:additional-review", "1" * 64
    v3.update(entry_id="00000000-0000-4000-8000-000000000999", catalog_revision="3",
              supersedes={k: v2[k] for k in ("entry_id", "entry_digest", "content_digest")})
    v3["resolved_refs"].append(dict(source_ref=ref, state="RESOLVED_FROZEN",
                                   content_ref="ref:sha256:" + digest,
                                   content_sha256=digest, pending_reason=None))
    v3["resolved_refs"].sort(key=lambda r: r["source_ref"])
    v3["evidence_only_refs"] = sorted(v2["evidence_only_refs"] + [ref])
    v3["entry_digest"] = c._entry_digest(v3)
    _validate_successor(v3, previous=v2, previous_anchor=V2_ANCHOR,
                        approved_digest=APPROVED, allowed_new_evidence={ref},
                        content_anchors={ref: digest})
    c._append_only([v1, v2], [v1, v2, v3])


def test_entry_rehash_cannot_replace_independent_anchor():
    entry = c._load(V2)
    entry["entry_id"] = "00000000-0000-4000-8000-000000000999"
    entry["entry_digest"] = c._entry_digest(entry)
    _check(entry)
    with pytest.raises(AssertionError, match="immutable anchor changed"):
        _check(entry, anchor=V2_ANCHOR)
    with pytest.raises(AssertionError, match="frozen entry removed"):
        c._append_only([c._load(V2)], [entry])
    modified = c._load(V2)
    modified["catalog_revision"] = "3"
    modified["entry_digest"] = c._entry_digest(modified)
    with pytest.raises(AssertionError, match="frozen entry modified"):
        c._append_only([c._load(V2)], [modified])


def test_documented_limits_and_reference_only_shape():
    entry = c._load(V2)
    assert set(entry["source_payload"]) == {"custody_ref", "content_digest"}
    assert all("content" not in r for r in entry["resolved_refs"])
    contract = " ".join((c.CATALOG / "CONTRACT.md").read_text().split())
    for phrase in ("evidence_only_refs", "catalog_revision", "sem recalcular",
                   "campos nulos", "23", "evidence-succession-v1"):
        assert phrase in contract

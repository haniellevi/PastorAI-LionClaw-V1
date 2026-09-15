"""Synthetic initial-state fixtures, distinct from the evolving current head."""

import copy
import hashlib
import json


def historical_initial_head(current):
    head = copy.deepcopy(current)
    prefix = head["historical_prefix"]
    assert prefix["migration_count"] == 75
    head["append_only_batches"] = []
    head["previous_approved_head_sha256"] = None
    head["current_head"] = {
        "digest_sha256": prefix["digest_sha256"],
        "last_basename": prefix["entries"][-1]["name"],
        "migration_count": prefix["migration_count"],
    }
    return head


def historical_initial_bytes(current_content):
    """Reconstruct frozen initial bytes and validate the first append anchor."""
    current = json.loads(current_content)
    content = _serialized_head_with_batches(current_content, 0)
    batches = current["append_only_batches"]
    if batches:
        first_append = _serialized_head_with_batches(current_content, 1)
        first_head = json.loads(first_append)
        assert hashlib.sha256(content).hexdigest() == (
            first_head["previous_approved_head_sha256"]
        )
    else:
        assert current["previous_approved_head_sha256"] is None
    return content


def immediate_approved_prior_bytes(current_content):
    """Reconstruct the exact immediate approved prior of an evolving head."""
    current = json.loads(current_content)
    batches = current["append_only_batches"]
    assert batches
    content = _serialized_head_with_batches(current_content, len(batches) - 1)
    assert hashlib.sha256(content).hexdigest() == (
        current["previous_approved_head_sha256"]
    )
    return content


def _serialized_head_with_batches(current_content, batch_count):
    """Render a historical head suffix through the canonical authoring helper."""
    from scripts import new_migration

    current = json.loads(current_content)
    prefix = current["historical_prefix"]
    batches = current["append_only_batches"]
    assert 0 <= batch_count <= len(batches)
    selected_batches = batches[:batch_count]
    if selected_batches:
        prior_content = _serialized_head_with_batches(
            current_content,
            batch_count - 1,
        )
        entries = [
            entry
            for batch in selected_batches
            for entry in batch["entries"]
        ]
        assert entries
        current_head = {
            "digest_sha256": selected_batches[-1]["resulting_catalog_digest_sha256"],
            "last_basename": entries[-1]["name"],
            "migration_count": prefix["migration_count"] + len(entries),
        }
        previous_approved_head_sha256 = hashlib.sha256(prior_content).hexdigest()
    else:
        current_head = {
            key: prefix[key]
            for key in ("migration_count", "last_basename", "digest_sha256")
        }
        previous_approved_head_sha256 = None
    head = {
        "append_only_batches": selected_batches,
        "current_head": current_head,
        "previous_approved_head_sha256": previous_approved_head_sha256,
        "operational_authorization": False,
        "next_stage_authorized": False,
    }
    return new_migration._serialize_head(head, current_content)

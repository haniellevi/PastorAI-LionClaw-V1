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
    """Reconstruct frozen initial bytes and verify the declared prior hash."""
    current = json.loads(current_content)
    initial = historical_initial_head(current)
    prefix = initial["historical_prefix"]
    tail = {
        "append_only_batches": [],
        "current_head": {key: prefix[key] for key in ("migration_count", "last_basename", "digest_sha256")},
        "previous_approved_head_sha256": None,
        "operational_authorization": False,
        "next_stage_authorized": False,
    }
    content = current_content.split(b'  "append_only_batches":', 1)[0] + (json.dumps(tail, indent=2)[2:] + "\n").encode()
    assert hashlib.sha256(content).hexdigest() == current["previous_approved_head_sha256"]
    return content

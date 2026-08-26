from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTION_REFERENCE = re.compile(
    r"uses:\s+(actions/[a-z-]+)@([^\s#]+)(?:\s+#\s+(v\S+))?"
)
# Each immutable SHA below is an official release whose action.yml declares
# runs.using: node24. A new official action must be reviewed and added here.
NODE24_ACTIONS = {
    "actions/checkout": (
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "v7.0.1",
    ),
    "actions/github-script": (
        "3a2844b7e9c422d3c10d287c895573f7108da1b3",
        "v9.0.0",
    ),
    "actions/setup-node": (
        "820762786026740c76f36085b0efc47a31fe5020",
        "v7.0.0",
    ),
    "actions/setup-python": (
        "5fda3b95a4ea91299a34e894583c3862153e4b97",
        "v7.0.0",
    ),
    "actions/upload-artifact": (
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
}


def _workflow_contents() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


def test_all_official_javascript_actions_are_reviewed_node24_releases() -> None:
    seen: dict[str, set[tuple[str, str]]] = {}

    for content in _workflow_contents().values():
        for action, sha, release in ACTION_REFERENCE.findall(content):
            seen.setdefault(action, set()).add((sha, release))

    assert set(seen) == set(NODE24_ACTIONS)
    for action, expected in NODE24_ACTIONS.items():
        assert seen[action] == {expected}


def test_workflows_cannot_opt_back_into_node20() -> None:
    combined = "\n".join(_workflow_contents().values())

    assert "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" not in combined
    assert re.search(r"node-version:\s*[\"']?20(?:[.\"']|$)", combined) is None


def test_repository_node24_contract_is_consistent() -> None:
    pinned_node = (REPO_ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    root_package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    frontend_package = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert pinned_node == "24.19.0"
    assert root_package["engines"]["node"] == pinned_node
    assert frontend_package["engines"]["node"] == "24.x"
    assert frontend_package["devDependencies"]["@types/node"].startswith("24.")

    workflows = _workflow_contents()
    workflow_node_versions = re.findall(
        r"node-version:\s*[\"']?([^\s\"']+)",
        "\n".join(workflows.values()),
    )
    assert workflow_node_versions
    assert set(workflow_node_versions) == {pinned_node}

    for path, content in workflows.items():
        if "actions/setup-node@" in content:
            assert f'node-version: "{pinned_node}"' in content, path

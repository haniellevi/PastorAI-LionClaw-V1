"""Redis heartbeat contract shared by all long-running workers."""

from __future__ import annotations

import pytest

from app.services.worker_health import (
    heartbeat_key,
    publish_worker_heartbeat,
    worker_heartbeat_alive,
    worker_heartbeat_states,
)


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.expiries[key] = ex

    def get(self, key: str):
        return self.values.get(key)

    def mget(self, keys):
        return [self.values.get(key) for key in keys]

    def close(self) -> None:
        pass


def test_publish_and_read_all_worker_states() -> None:
    client = _Redis()
    for worker, state in (
        ("queue-worker", "ready"),
        ("cron-worker", "running"),
        ("broadcast-worker", "idle"),
    ):
        publish_worker_heartbeat(
            None,
            worker_name=worker,
            state=state,
            ttl_seconds=30,
            client=client,
        )

    assert worker_heartbeat_states(None, client=client) == {
        "queue-worker": "ready",
        "cron-worker": "running",
        "broadcast-worker": "idle",
    }
    assert all(value == 30 for value in client.expiries.values())


@pytest.mark.parametrize("state", ["ready", "running", "idle"])
def test_alive_states_are_container_healthy(monkeypatch, state) -> None:
    import app.services.worker_health as health

    monkeypatch.setattr(health, "worker_heartbeat_state", lambda *_args: state)
    assert worker_heartbeat_alive("redis://unused", "queue-worker") is True


@pytest.mark.parametrize("state", [None, "error", "stopped"])
def test_missing_and_terminal_states_are_container_unhealthy(
    monkeypatch, state
) -> None:
    import app.services.worker_health as health

    monkeypatch.setattr(health, "worker_heartbeat_state", lambda *_args: state)
    assert worker_heartbeat_alive("redis://unused", "queue-worker") is False


def test_worker_names_and_states_are_closed_sets() -> None:
    client = _Redis()

    with pytest.raises(ValueError, match="invalid worker name"):
        heartbeat_key("../../secret")
    with pytest.raises(ValueError, match="invalid worker heartbeat state"):
        publish_worker_heartbeat(
            None,
            worker_name="queue-worker",
            state="secret=value",
            ttl_seconds=30,
            client=client,
        )

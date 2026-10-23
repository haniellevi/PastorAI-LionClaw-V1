"""Bounded, payload-free metadata view over synthetic webhook queues."""
import json

from app.workers.queue_worker import (
    DEAD_LETTER_QUEUE,
    PROCESSING_QUEUE,
    SCHEDULED_RETRY_QUEUE,
    WEBHOOK_QUEUE,
    WEBHOOK_METRICS_MAX_ITEMS,
    WORKER_REGISTRY,
    WebhookQueue,
    _Envelope,
)


class MetricsRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.lrange_calls: list[tuple[str, int, int]] = []

    def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        self.lrange_calls.append((key, start, stop))
        items = self.lists.get(key, [])
        if stop == -1:
            return items[start:]
        return items[start : stop + 1]

    def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.zsets.setdefault(key, {}).update(mapping)

    def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    def zrange(self, key: str, start: int, stop: int) -> list[str]:
        values = sorted(
            self.zsets.get(key, {}).items(), key=lambda item: (item[1], item[0])
        )
        if stop == -1:
            return [value for value, _score in values[start:]]
        return [value for value, _score in values[start : stop + 1]]


def test_queue_snapshot_reads_all_unacked_states_and_omits_payload() -> None:
    redis = MetricsRedis()
    queue = WebhookQueue(redis_client=redis, clock=lambda: 500.0)
    queue.enqueue(
        {"instance": "synthetic-instance", "message": "SYNTHETIC_PRIVATE_TEXT"}
    )
    queued = redis.lists[WEBHOOK_QUEUE][0]
    envelope = _Envelope.from_json(queued)
    assert envelope.received_at == 500.0

    redis.sadd(WORKER_REGISTRY, "worker-1")
    redis.lpush(f"{PROCESSING_QUEUE}:worker-1", queued)
    retry = _Envelope(
        payload={"instance": "synthetic-instance", "message": "PRIVATE_RETRY"},
        claim_id="retry-claim",
        received_at=300.0,
    ).to_json()
    redis.zadd(SCHEDULED_RETRY_QUEUE, {retry: 600.0})
    legacy = json.dumps(
        {
            "payload": {"instance": "synthetic-instance", "message": "PRIVATE_OLD"},
            "attempts": 1,
            "claim_id": "legacy-claim",
        }
    )
    redis.lpush(DEAD_LETTER_QUEUE, legacy)

    metadata, complete = queue.pending_metadata()
    dead_letters, dead_letters_complete = queue.dead_letter_metadata()

    assert complete is True
    assert len(metadata) == 2  # the same claim in ready and processing counts once
    assert {item.claim_id for item in metadata} == {
        envelope.claim_id,
        "retry-claim",
    }
    assert dead_letters_complete is True
    assert [item.claim_id for item in dead_letters] == ["legacy-claim"]
    assert all(item.instance == "synthetic-instance" for item in metadata)
    assert "SYNTHETIC_PRIVATE_TEXT" not in repr(metadata)
    assert not hasattr(metadata[0], "payload")
    assert queue.pending_metadata(max_items=2)[1] is False


def test_queue_snapshot_refuses_to_read_payloads_above_item_cap() -> None:
    redis = MetricsRedis()
    queue = WebhookQueue(redis_client=redis)
    cap = WEBHOOK_METRICS_MAX_ITEMS
    for index in range(cap + 1):
        redis.lpush(
            WEBHOOK_QUEUE,
            _Envelope(
                payload={"instance": "synthetic-instance", "body": "x" * 2048},
                claim_id=f"claim-{index}",
                received_at=500.0,
            ).to_json(),
        )

    metadata, complete = queue.pending_metadata()

    assert metadata == []
    assert complete is False
    assert redis.lrange_calls == []


def test_dead_letter_backlog_does_not_make_active_snapshot_incomplete() -> None:
    redis = MetricsRedis()
    queue = WebhookQueue(redis_client=redis)
    cap = WEBHOOK_METRICS_MAX_ITEMS
    active = _Envelope(
        payload={"instance": "synthetic-instance", "body": "active"},
        claim_id="active-claim",
        received_at=500.0,
    ).to_json()
    redis.lpush(WEBHOOK_QUEUE, active)
    for index in range(cap + 1):
        redis.lpush(
            DEAD_LETTER_QUEUE,
            _Envelope(
                payload={"instance": "synthetic-instance", "body": "x" * 2048},
                claim_id=f"dead-{index}",
                received_at=500.0,
            ).to_json(),
        )

    active_metadata, active_complete = queue.pending_metadata()
    dead_letters, dead_letters_complete = queue.dead_letter_metadata()

    assert active_complete is True
    assert [item.claim_id for item in active_metadata] == ["active-claim"]
    assert dead_letters == []
    assert dead_letters_complete is False
    assert all(key != DEAD_LETTER_QUEUE for key, _start, _stop in redis.lrange_calls)


def test_queue_snapshot_marks_malformed_items_incomplete() -> None:
    redis = MetricsRedis()
    redis.lpush(WEBHOOK_QUEUE, "not-json")

    metadata, complete = WebhookQueue(redis_client=redis).pending_metadata()

    assert metadata == []
    assert complete is False

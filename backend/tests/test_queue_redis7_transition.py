"""Adversarial Redis 7 coverage for failed webhook claim transitions.

These checks deliberately use a disposable Redis 7 container instead of the
in-memory worker fake.  A Lua script is atomic between commands, but Redis does
not roll back an earlier command when a later command errors; the tests prove
that every uncertain path keeps either the source claim or one durable
replacement.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator

import pytest
import redis

from app.workers.queue_worker import (
    _ACK_CLAIM_SCRIPT,
    _MOVE_DUE_RETRIES_SCRIPT,
    _MOVE_FAILED_CLAIM_SCRIPT,
    _RECONCILE_RETRY_CLAIM_SCRIPT,
    RETRY_STATE_TTL_SECONDS,
    _retry_state_key,
)


pytestmark = pytest.mark.redis7


@pytest.fixture(scope="module")
def redis7() -> Iterator[redis.Redis]:
    """Start an isolated Redis 7 that is always removed after this module."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is required for Redis 7 transition coverage")
    available = subprocess.run(
        [docker, "info"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    if available.returncode != 0:
        pytest.skip("Docker daemon is unavailable for Redis 7 transition coverage")

    name = f"pastorai-m08-redis7-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    started = subprocess.run(
        [
            docker,
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--publish",
            "127.0.0.1::6379",
            "redis:7.4-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if started.returncode != 0:
        pytest.skip("Redis 7 container could not start")

    try:
        port_result = subprocess.run(
            [
                docker,
                "inspect",
                "--format",
                "{{(index (index .NetworkSettings.Ports \"6379/tcp\") 0).HostPort}}",
                name,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        client = redis.Redis(
            host="127.0.0.1",
            port=int(port_result.stdout.strip()),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        for _ in range(50):
            try:
                client.ping()
                break
            except redis.RedisError:
                time.sleep(0.1)
        else:
            pytest.skip("Redis 7 did not become ready")
        yield client
    finally:
        subprocess.run(
            [docker, "rm", "--force", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )


def _seed(
    client: redis.Redis,
    *,
    suffix: str,
    owner: str = "owner-a",
) -> tuple[str, str, str, str, str]:
    client.flushdb()
    lease = f"m08:lease:{suffix}"
    processing = f"m08:processing:{suffix}"
    target = f"m08:target:{suffix}"
    raw = f'{{"claim_id":"claim-{suffix}","attempts":0}}'
    replacement = f'{{"claim_id":"claim-{suffix}","attempts":1}}'
    client.set(lease, owner)
    client.rpush(processing, raw)
    return lease, processing, target, raw, replacement


def _move(
    client: redis.Redis,
    *,
    lease: str,
    processing: str,
    target: str,
    owner: str,
    raw: str,
    replacement: str,
    failure: str = "",
    scheduled_at: float | None = None,
) -> int:
    args: list[str | int] = [
        _MOVE_FAILED_CLAIM_SCRIPT,
        3,
        lease,
        processing,
        target,
        owner,
        raw,
        replacement,
        failure,
    ]
    if scheduled_at is not None:
        args.append(str(scheduled_at))
    return int(
        client.eval(*args)
    )


def _move_with_state(
    client: redis.Redis,
    *,
    lease: str,
    processing: str,
    target: str,
    state_key: str,
    owner: str,
    raw: str,
    replacement: str,
    attempts: int = 1,
    status: str = "scheduled",
    failure: str = "",
    scheduled_at: float | None = None,
) -> int:
    """Exercise the production transition shape, including its claim state."""
    retry_at = "" if scheduled_at is None else str(scheduled_at)
    return int(
        client.eval(
            _MOVE_FAILED_CLAIM_SCRIPT,
            4,
            lease,
            processing,
            target,
            state_key,
            owner,
            raw,
            replacement,
            failure,
            retry_at,
            str(attempts),
            status,
            str(RETRY_STATE_TTL_SECONDS),
        )
    )


def _reconcile(
    client: redis.Redis,
    *,
    lease: str,
    processing: str,
    state_key: str,
    scheduled: str,
    ready: str,
    dead: str,
    owner: str,
    raw: str,
    now: float,
) -> int:
    return int(
        client.eval(
            _RECONCILE_RETRY_CLAIM_SCRIPT,
            6,
            lease,
            processing,
            state_key,
            scheduled,
            ready,
            dead,
            owner,
            raw,
            str(now),
            str(RETRY_STATE_TTL_SECONDS),
        )
    )


def _ack(
    client: redis.Redis,
    *,
    lease: str,
    processing: str,
    state_key: str,
    owner: str,
    raw: str,
) -> int:
    return int(
        client.eval(
            _ACK_CLAIM_SCRIPT,
            3,
            lease,
            processing,
            state_key,
            owner,
            raw,
            str(RETRY_STATE_TTL_SECONDS),
        )
    )


def _promote(
    client: redis.Redis,
    *,
    scheduled: str,
    ready: str,
    now: float,
) -> int:
    return int(client.eval(_MOVE_DUE_RETRIES_SCRIPT, 2, scheduled, ready, str(now)))


@pytest.mark.parametrize(
    "failure",
    [
        "before_destination",
        "target_write_error",
        "after_destination",
        "before_source",
        "after_source",
    ],
)
def test_real_redis7_failure_points_never_lose_the_claim(
    redis7: redis.Redis, failure: str
) -> None:
    """Each command-boundary failure is recoverable across 50 repetitions."""
    for attempt in range(50):
        lease, processing, target, raw, replacement = _seed(
            redis7, suffix=f"{failure}-{attempt}"
        )
        result = _move(
            redis7,
            lease=lease,
            processing=processing,
            target=target,
            owner="owner-a",
            raw=raw,
            replacement=replacement,
            failure=failure,
        )

        assert result < 0
        source = redis7.lrange(processing, 0, -1)
        destination = redis7.lrange(target, 0, -1)
        assert raw in source or replacement in destination

        if raw in source:
            assert _move(
                redis7,
                lease=lease,
                processing=processing,
                target=target,
                owner="owner-a",
                raw=raw,
                replacement=replacement,
            ) == 1

        assert redis7.lrange(processing, 0, -1) == []
        assert redis7.lrange(target, 0, -1) == [replacement]


def test_real_redis7_rejects_invalid_destination_type_without_losing_claim(
    redis7: redis.Redis,
) -> None:
    lease, processing, target, raw, replacement = _seed(redis7, suffix="wrongtype")
    redis7.set(target, "not-a-list")

    assert _move(
        redis7,
        lease=lease,
        processing=processing,
        target=target,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
    ) == -1
    assert redis7.lrange(processing, 0, -1) == [raw]
    assert redis7.get(target) == "not-a-list"


def test_real_redis7_oom_before_destination_never_loses_claim(
    redis7: redis.Redis,
) -> None:
    """A real no-eviction write failure leaves the original claim intact."""
    lease, processing, target, raw, replacement = _seed(redis7, suffix="oom")
    original_maxmemory = redis7.config_get("maxmemory").get("maxmemory", "0")
    original_policy = redis7.config_get("maxmemory-policy").get(
        "maxmemory-policy", "noeviction"
    )
    try:
        redis7.config_set("maxmemory-policy", "noeviction")
        # The running Redis process already uses more than one byte, so every
        # allocating command must fail before LPUSH can mutate the target.
        redis7.config_set("maxmemory", "1")
        assert _move(
            redis7,
            lease=lease,
            processing=processing,
            target=target,
            owner="owner-a",
            raw=raw,
            replacement=replacement,
        ) == -11
        assert redis7.lrange(processing, 0, -1) == [raw]
        assert redis7.exists(target) == 0
    finally:
        redis7.config_set("maxmemory", original_maxmemory)
        redis7.config_set("maxmemory-policy", original_policy)
        redis7.flushdb()


def test_real_redis7_expired_or_transferred_lease_fences_stale_owner(
    redis7: redis.Redis,
) -> None:
    lease, processing, target, raw, replacement = _seed(redis7, suffix="expired")
    redis7.delete(lease)
    assert _move(
        redis7,
        lease=lease,
        processing=processing,
        target=target,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
    ) == 0
    assert redis7.lrange(processing, 0, -1) == [raw]
    assert redis7.lrange(target, 0, -1) == []

    old_lease, old_processing, target, raw, replacement = _seed(
        redis7, suffix="transferred", owner="owner-a"
    )
    new_lease = "m08:lease:transferred:new"
    new_processing = "m08:processing:transferred:new"
    redis7.set(old_lease, "owner-b")
    assert _move(
        redis7,
        lease=old_lease,
        processing=old_processing,
        target=target,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
    ) == 0
    assert redis7.lrange(target, 0, -1) == []
    assert redis7.lrem(old_processing, 1, raw) == 1
    redis7.rpush(new_processing, raw)
    redis7.set(new_lease, "owner-b")
    assert _move(
        redis7,
        lease=new_lease,
        processing=new_processing,
        target=target,
        owner="owner-b",
        raw=raw,
        replacement=replacement,
    ) == 1
    assert redis7.lrange(target, 0, -1) == [replacement]


def test_real_redis7_concurrent_calls_produce_one_valid_transition(
    redis7: redis.Redis,
) -> None:
    for attempt in range(50):
        lease, processing, target, raw, replacement = _seed(
            redis7, suffix=f"race-{attempt}"
        )

        def move_once() -> int:
            return _move(
                redis7,
                lease=lease,
                processing=processing,
                target=target,
                owner="owner-a",
                raw=raw,
                replacement=replacement,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _unused: move_once(), range(2)))

        assert sorted(results) == [0, 1]
        assert redis7.lrange(processing, 0, -1) == []
        assert redis7.lrange(target, 0, -1) == [replacement]


@pytest.mark.parametrize(
    "failure",
    [
        "before_destination",
        "target_write_error",
        "after_destination",
        "before_source",
        "after_source",
    ],
)
def test_real_redis7_scheduled_failure_points_preserve_source_or_retry(
    redis7: redis.Redis, failure: str
) -> None:
    """The delayed destination has the same no-loss contract as the ready list."""
    for attempt in range(50):
        lease, processing, scheduled, raw, replacement = _seed(
            redis7, suffix=f"scheduled-{failure}-{attempt}"
        )
        due_at = 10_000.0 + attempt
        result = _move(
            redis7,
            lease=lease,
            processing=processing,
            target=scheduled,
            owner="owner-a",
            raw=raw,
            replacement=replacement,
            failure=failure,
            scheduled_at=due_at,
        )

        assert result < 0
        source = redis7.lrange(processing, 0, -1)
        persisted_retry = redis7.zscore(scheduled, replacement)
        assert raw in source or persisted_retry == due_at

        if raw in source:
            assert _move(
                redis7,
                lease=lease,
                processing=processing,
                target=scheduled,
                owner="owner-a",
                raw=raw,
                replacement=replacement,
                scheduled_at=due_at,
            ) == 1

        assert redis7.lrange(processing, 0, -1) == []
        assert redis7.zscore(scheduled, replacement) == due_at


@pytest.mark.parametrize(
    "failure",
    [
        "before_destination",
        "target_write_error",
        "after_destination",
        "before_source",
        "after_source",
    ],
)
def test_real_redis7_stateful_schedule_failure_is_recoverable(
    redis7: redis.Redis, failure: str
) -> None:
    """Canonical state repairs every partial scheduled transition without a spin."""
    suffix = f"stateful-scheduled-{failure}"
    lease, processing, scheduled, raw, replacement = _seed(redis7, suffix=suffix)
    claim_id = f"claim-{suffix}"
    state_key = _retry_state_key(claim_id)
    due_at = 11_000.0

    assert _move_with_state(
        redis7,
        lease=lease,
        processing=processing,
        target=scheduled,
        state_key=state_key,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
        failure=failure,
        scheduled_at=due_at,
    ) < 0
    assert redis7.hgetall(state_key) == {
        "raw": replacement,
        "attempts": "1",
        "retry_at": str(due_at),
        "status": "scheduled",
    }

    if raw in redis7.lrange(processing, 0, -1):
        recovered_lease = f"m08:lease:{suffix}:recovered"
        recovered_processing = f"m08:processing:{suffix}:recovered"
        ready = f"m08:ready:{suffix}"
        dead = f"m08:dead:{suffix}"
        assert redis7.rpoplpush(processing, recovered_processing) == raw
        redis7.set(recovered_lease, "owner-b")
        assert _reconcile(
            redis7,
            lease=recovered_lease,
            processing=recovered_processing,
            state_key=state_key,
            scheduled=scheduled,
            ready=ready,
            dead=dead,
            owner="owner-b",
            raw=raw,
            now=due_at - 0.001,
        ) == 1
        assert redis7.lrange(recovered_processing, 0, -1) == []

    assert redis7.lrange(processing, 0, -1) == []
    assert redis7.zscore(scheduled, replacement) == due_at


def test_real_redis7_scheduled_retry_waits_then_promotes_once(redis7: redis.Redis) -> None:
    """A future retry stays outside the ready list until its persisted deadline."""
    lease, processing, scheduled, raw, replacement = _seed(redis7, suffix="scheduled-due")
    ready = "m08:ready:scheduled-due"
    due_at = 12_345.0

    assert _move(
        redis7,
        lease=lease,
        processing=processing,
        target=scheduled,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
        scheduled_at=due_at,
    ) == 1
    assert redis7.lrange(processing, 0, -1) == []
    assert _promote(redis7, scheduled=scheduled, ready=ready, now=due_at - 0.001) == 0
    assert redis7.lrange(ready, 0, -1) == []
    assert redis7.zscore(scheduled, replacement) == due_at

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _unused: _promote(
                    redis7, scheduled=scheduled, ready=ready, now=due_at
                ),
                range(2),
            )
        )

    assert sorted(results) == [0, 1]
    assert redis7.zrange(scheduled, 0, -1) == []
    assert redis7.lrange(ready, 0, -1) == [replacement]


def test_real_redis7_recovered_partial_schedule_keeps_its_deadline(
    redis7: redis.Redis,
) -> None:
    """The recovered source cannot outrun a retry persisted before source removal."""
    lease, processing, scheduled, raw, replacement = _seed(
        redis7, suffix="scheduled-partial"
    )
    due_at = 20_000.0
    state_key = _retry_state_key("claim-scheduled-partial")
    assert _move_with_state(
        redis7,
        lease=lease,
        processing=processing,
        target=scheduled,
        state_key=state_key,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
        failure="after_destination",
        scheduled_at=due_at,
    ) == -12
    recovered_lease = "m08:lease:scheduled-partial:recovered"
    recovered_processing = "m08:processing:scheduled-partial:recovered"
    ready = "m08:ready:partial"
    dead = "m08:dead:partial"
    redis7.rpoplpush(processing, recovered_processing)
    redis7.set(recovered_lease, "owner-b")

    assert _reconcile(
        redis7,
        lease=recovered_lease,
        processing=recovered_processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-b",
        raw=raw,
        now=due_at - 0.001,
    ) == 1
    assert redis7.lrange(recovered_processing, 0, -1) == []
    assert _promote(
        redis7, scheduled=scheduled, ready=ready, now=due_at - 0.001
    ) == 0
    redis7.lpush(ready, raw)
    assert _promote(
        redis7, scheduled=scheduled, ready=ready, now=due_at
    ) == 1
    redis7.rpoplpush(ready, recovered_processing)
    assert _reconcile(
        redis7,
        lease=recovered_lease,
        processing=recovered_processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-b",
        raw=raw,
        now=due_at,
    ) == 1
    assert redis7.lrange(recovered_processing, 0, -1) == []
    assert redis7.lrange(ready, 0, -1) == [replacement]


def test_real_redis7_newer_retry_survives_old_raw_left_ready_in_inverse_order(
    redis7: redis.Redis,
) -> None:
    """A ready stale source cannot discard the newer raw claimed ahead of it."""
    lease, processing, scheduled, raw, replacement = _seed(
        redis7, suffix="state-order-inverted"
    )
    claim_id = "claim-state-order-inverted"
    state_key = _retry_state_key(claim_id)
    ready = "m08:ready:state-order-inverted"
    dead = "m08:dead:state-order-inverted"
    due_at = 21_000.0

    assert _move_with_state(
        redis7,
        lease=lease,
        processing=processing,
        target=scheduled,
        state_key=state_key,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
        scheduled_at=due_at,
    ) == 1
    assert _promote(redis7, scheduled=scheduled, ready=ready, now=due_at) == 1
    # LPUSH leaves the old source at the head and the newer retry at the tail,
    # where RPOPLPUSH claims the newer retry first.
    redis7.lpush(ready, raw)
    assert redis7.rpoplpush(ready, processing) == replacement
    assert _reconcile(
        redis7,
        lease=lease,
        processing=processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-a",
        raw=replacement,
        now=due_at,
    ) == 0
    assert redis7.hget(state_key, "attempts") == "1"

    assert _ack(
        redis7,
        lease=lease,
        processing=processing,
        state_key=state_key,
        owner="owner-a",
        raw=replacement,
    ) == 1
    assert redis7.rpoplpush(ready, processing) == raw
    assert _reconcile(
        redis7,
        lease=lease,
        processing=processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-a",
        raw=raw,
        now=due_at,
    ) == 1
    assert redis7.lrange(processing, 0, -1) == []
    assert redis7.lrange(ready, 0, -1) == []
    assert redis7.hget(state_key, "attempts") == "1"


def test_real_redis7_stale_source_cannot_run_while_retry_is_processing_elsewhere(
    redis7: redis.Redis,
) -> None:
    """A state in processing still rejects an older raw claimed by another worker."""
    lease, processing, scheduled, raw, replacement = _seed(
        redis7, suffix="state-processing-other-worker"
    )
    claim_id = "claim-state-processing-other-worker"
    state_key = _retry_state_key(claim_id)
    ready = "m08:ready:state-processing-other-worker"
    dead = "m08:dead:state-processing-other-worker"
    second_lease = "m08:lease:state-processing-other-worker:second"
    second_processing = "m08:processing:state-processing-other-worker:second"
    due_at = 22_000.0

    assert _move_with_state(
        redis7,
        lease=lease,
        processing=processing,
        target=scheduled,
        state_key=state_key,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
        scheduled_at=due_at,
    ) == 1
    assert _promote(redis7, scheduled=scheduled, ready=ready, now=due_at) == 1

    redis7.set(second_lease, "owner-b")
    assert redis7.rpoplpush(ready, second_processing) == replacement
    assert _reconcile(
        redis7,
        lease=second_lease,
        processing=second_processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-b",
        raw=replacement,
        now=due_at,
    ) == 0

    redis7.lpush(ready, raw)
    assert redis7.rpoplpush(ready, processing) == raw
    assert _reconcile(
        redis7,
        lease=lease,
        processing=processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-a",
        raw=raw,
        now=due_at,
    ) == 1
    assert redis7.lrange(processing, 0, -1) == []
    assert redis7.lrange(second_processing, 0, -1) == [replacement]
    assert redis7.hget(state_key, "attempts") == "1"


def test_real_redis7_canonical_owner_fences_duplicate_and_recovers_after_expiry(
    redis7: redis.Redis,
) -> None:
    """The canonical raw has one live owner, then transfers after lease expiry."""

    suffix = "canonical-owner-fence"
    lease, processing, scheduled, raw, replacement = _seed(redis7, suffix=suffix)
    claim_id = f"claim-{suffix}"
    state_key = _retry_state_key(claim_id)
    ready = f"m08:ready:{suffix}"
    dead = f"m08:dead:{suffix}"
    owner_b = "owner-b"
    owner_c = "owner-c"
    lease_b = f"m08:lease:{suffix}:b"
    processing_b = f"m08:processing:{suffix}:b"
    stale_lease = f"m08:lease:{suffix}:stale"
    stale_processing = f"m08:processing:{suffix}:stale"
    lease_c = f"m08:lease:{suffix}:c"
    processing_c = f"m08:processing:{suffix}:c"
    duplicate_processing = f"m08:processing:{suffix}:duplicate"
    duplicate_lease = f"m08:lease:{suffix}:duplicate"
    due_at = 23_000.0

    assert _move_with_state(
        redis7,
        lease=lease,
        processing=processing,
        target=scheduled,
        state_key=state_key,
        owner="owner-a",
        raw=raw,
        replacement=replacement,
        failure="after_destination",
        scheduled_at=due_at,
    ) == -12
    assert _promote(redis7, scheduled=scheduled, ready=ready, now=due_at) == 1

    # B moves the canonical retry before its reconcile. A recovered stale raw
    # can therefore rebuild the due ZSET member, exactly as the R4 race did.
    redis7.delete(lease)
    redis7.set(lease_b, owner_b)
    assert redis7.rpoplpush(ready, processing_b) == replacement
    redis7.set(stale_lease, "owner-stale")
    assert redis7.rpoplpush(processing, stale_processing) == raw
    assert _reconcile(
        redis7,
        lease=stale_lease,
        processing=stale_processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-stale",
        raw=raw,
        now=due_at,
    ) == 1
    assert redis7.zscore(scheduled, replacement) == due_at
    assert _reconcile(
        redis7,
        lease=lease_b,
        processing=processing_b,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner=owner_b,
        raw=replacement,
        now=due_at,
    ) == 0
    assert redis7.hgetall(state_key) == {
        "raw": replacement,
        "attempts": "1",
        "retry_at": str(due_at),
        "status": "processing",
        "owner": owner_b,
        "owner_lease": lease_b,
        "owner_processing": processing_b,
    }

    # A partial source can leave a second exact canonical raw. Its private
    # lease/list is not an ownership proof once B owns the state hash.
    assert _promote(redis7, scheduled=scheduled, ready=ready, now=due_at) == 1
    redis7.set(duplicate_lease, "owner-duplicate")
    assert redis7.rpoplpush(ready, duplicate_processing) == replacement
    assert _reconcile(
        redis7,
        lease=duplicate_lease,
        processing=duplicate_processing,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner="owner-duplicate",
        raw=replacement,
        now=due_at,
    ) == 1
    assert redis7.lrange(duplicate_processing, 0, -1) == []
    assert redis7.lrange(processing_b, 0, -1) == [replacement]

    # Once B's Redis lease truly disappears, C can recover the same canonical
    # raw without rewinding the persisted attempt or its original deadline.
    redis7.delete(lease_b)
    redis7.set(lease_c, owner_c)
    redis7.rpush(processing_c, replacement)
    assert _reconcile(
        redis7,
        lease=lease_c,
        processing=processing_c,
        state_key=state_key,
        scheduled=scheduled,
        ready=ready,
        dead=dead,
        owner=owner_c,
        raw=replacement,
        now=due_at,
    ) == 0
    assert redis7.hgetall(state_key) == {
        "raw": replacement,
        "attempts": "1",
        "retry_at": str(due_at),
        "status": "processing",
        "owner": owner_c,
        "owner_lease": lease_c,
        "owner_processing": processing_c,
    }

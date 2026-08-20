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

from app.workers.queue_worker import _MOVE_FAILED_CLAIM_SCRIPT


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
) -> int:
    return int(
        client.eval(
            _MOVE_FAILED_CLAIM_SCRIPT,
            3,
            lease,
            processing,
            target,
            owner,
            raw,
            replacement,
            failure,
        )
    )


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

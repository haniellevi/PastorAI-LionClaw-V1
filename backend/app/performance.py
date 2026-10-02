"""Bounded, process-local performance measurements with no domain payloads.

SQL timing covers DBAPI execute, including RLS commands, but excludes row fetch
and pre-ping. Acquisition measures Session.execute entry to successful checkout
(ORM dispatch, pool wait, connection and ping); it is not pure pool queue wait.
Explicit Connection access and flush have SQL/hold coverage, but no acquisition
start event. Sample counts expose that coverage instead of inventing durations.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import DBAPIError, DisconnectionError, TimeoutError
from starlette.datastructures import Headers, MutableHeaders

logger = logging.getLogger("pastorai")
_SPANS = frozenset({"auth", "provider", "storage"})
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_DURATION_BUCKETS = (50, 100, 200, 400, 800, 1500, 3000, 6000, 12000)
_COUNT_BUCKETS = (0, 1, 2, 4, 8, 16, 32, 64)
_LEASE_KEY = "pastorai_performance_lease"


def release_sha() -> str:
    """Only an explicit image revision can identify a backend release."""
    value = os.environ.get("PASTORAI_RELEASE_SHA", "")
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else "unknown"


def should_sample() -> bool:
    # Independent of the client-controlled correlation ID, approximately 1/16.
    return random.getrandbits(4) == 0


@dataclass
class RequestTiming:
    sampled: bool
    values: dict[str, float] = field(default_factory=dict)
    closed: bool = False
    lock: Any = field(default_factory=Lock, repr=False)

    def add(self, name: str, value: float = 1) -> None:
        with self.lock:
            if not self.closed:
                self.values[name] = self.values.get(name, 0) + max(0, value)

    def snapshot(self, *, close: bool = False) -> dict[str, float]:
        with self.lock:
            if close:
                self.closed = True
            return dict(self.values)


_current: ContextVar[RequestTiming | None] = ContextVar("performance_request", default=None)
_acquisition: ContextVar[dict[str, Any] | None] = ContextVar("performance_acquire", default=None)


@contextmanager
def capture_request(*, sampled: bool) -> Iterator[RequestTiming]:
    timing = RequestTiming(sampled)
    token = _current.set(timing)
    try:
        yield timing
    finally:
        timing.snapshot(close=True)
        _current.reset(token)


@contextmanager
def timed_span(name: str) -> Iterator[None]:
    """Measure a fixed span label; never accept identifiers, URLs or payloads."""
    if name not in _SPANS:
        raise ValueError("unsupported performance span")
    timing = _current.get()
    if timing is None or not timing.sampled or timing.closed:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    except BaseException:
        timing.add(f"{name}_errors")
        raise
    finally:
        timing.add(f"{name}_ms", (time.perf_counter() - started) * 1000)
        timing.add(f"{name}_count")


def instrument_engine(engine: Any) -> None:
    """Use public per-engine events, never patch DBAPI or global Engine APIs."""
    def before_execute(_conn, _cursor, _statement, _parameters, context, _many):
        timing = _current.get()
        if timing is not None and timing.sampled and not timing.closed:
            context._pastorai_query_timing = (timing, time.perf_counter())
            timing.add("sql_count")

    def finish_query(context, *, failed=False):
        measurement = getattr(context, "_pastorai_query_timing", None)
        if measurement is not None:
            context._pastorai_query_timing = None
            timing, started = measurement
            timing.add("sql_ms", (time.perf_counter() - started) * 1000)
            if failed:
                timing.add("sql_errors")

    def after_execute(_conn, _cursor, _statement, _parameters, context, _many):
        finish_query(context)

    def handle_error(context):
        finish_query(context.execution_context, failed=True)

    def checkout(_dbapi, record, _proxy):
        timing = _current.get()
        if timing is None or not timing.sampled or timing.closed:
            return
        now = time.perf_counter()
        attempt = _acquisition.get()
        if attempt is not None and attempt["timing"] is timing and not attempt["acquired"]:
            attempt["acquired"] = True
            timing.add("db_acquire_ms", (now - attempt["started"]) * 1000)
            timing.add("db_acquire_count")
        record.info[_LEASE_KEY] = (timing, now)
        timing.add("db_checkout_count")

    def finish_lease(_dbapi, record, *_extra):
        measurement = record.info.pop(_LEASE_KEY, None)
        if measurement is not None:
            timing, started = measurement
            timing.add("db_hold_ms", (time.perf_counter() - started) * 1000)
            timing.add("db_hold_count")

    for name, callback in (
        ("before_cursor_execute", before_execute),
        ("after_cursor_execute", after_execute),
        ("handle_error", handle_error),
        ("checkout", checkout),
        ("checkin", finish_lease),
        ("invalidate", finish_lease),
        ("detach", finish_lease),
    ):
        event.listen(engine, name, callback)


def instrument_session_factory(factory: Any) -> None:
    def execute(state):
        timing = _current.get()
        if timing is None or not timing.sampled or timing.closed:
            return None
        attempt = {"timing": timing, "started": time.perf_counter(), "acquired": False}
        token = _acquisition.set(attempt)
        try:
            return state.invoke_statement()
        except (TimeoutError, DBAPIError, DisconnectionError):
            if not attempt["acquired"]:
                timing.add("db_acquire_ms", (time.perf_counter() - attempt["started"]) * 1000)
                timing.add("db_acquire_count")
                timing.add("db_acquire_errors")
            raise
        finally:
            _acquisition.reset(token)

    event.listen(factory, "do_orm_execute", execute, retval=True)


class PerformanceRegistry:
    """Finite histogram buckets/labels, including errors in request durations.

    Detailed SQL/pool/provider histograms describe sampled requests only. Budget
    violations are observations, never timeouts or authorization decisions.
    Snapshots remain internal; sanitized cumulative rows emit at most once per
    route/method/status class per minute for an existing log collector.
    """
    def __init__(self) -> None:
        self.release = release_sha()
        self._rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._last_emitted: dict[tuple[str, str, str], float] = {}
        self._lock = Lock()

    def observe(self, route: str, method: str, status: int, duration_ms: float,
                timing: RequestTiming) -> None:
        method = method if method in _METHODS else "<other>"
        status_class = f"{status // 100}xx" if 100 <= status <= 599 else "5xx"
        key = (route, method, status_class)
        values = timing.snapshot(close=True) if timing.sampled else {}
        measurements = {"request_ms": duration_ms}
        if timing.sampled:
            for name in ("sql_count", "sql_ms", "db_acquire_ms", "db_hold_ms"):
                # No start event or no completed lease is missing coverage, not 0.
                if name == "db_acquire_ms" and not values.get("db_acquire_count"):
                    continue
                if name == "db_hold_ms" and values.get("db_hold_count", 0) != values.get("db_checkout_count", 0):
                    continue
                measurements[name] = values.get(name, 0)
            for name in _SPANS:
                if values.get(f"{name}_count"):
                    measurements[f"{name}_ms"] = values[f"{name}_ms"]
        now = time.monotonic()
        emit = None
        with self._lock:
            row = self._rows.setdefault(key, {
                "schema": 1, "release": self.release, "route": route,
                "method": method, "status_class": status_class,
                "sample_count": 0, "read_budget_exceeded": 0,
                "sql_errors": 0, "db_acquire_errors": 0,
                "db_checkout_count": 0, "db_acquire_count": 0, "db_hold_count": 0,
            })
            row["sample_count"] += int(timing.sampled)
            for name in ("sql_errors", "db_acquire_errors", "db_checkout_count", "db_acquire_count", "db_hold_count"):
                row[name] += int(values.get(name, 0))
            for name in _SPANS:
                if values.get(f"{name}_count"):
                    row[f"{name}_count"] = row.get(f"{name}_count", 0) + int(values[f"{name}_count"])
                    row[f"{name}_errors"] = row.get(f"{name}_errors", 0) + int(values.get(f"{name}_errors", 0))
            if method == "GET" and route not in {"/health", "/ready", "/docs", "/openapi.json", "<unmatched>"}:
                row["read_budget_exceeded"] += int(duration_ms > 800)
            for name, value in measurements.items():
                bounds = _COUNT_BUCKETS if name == "sql_count" else _DURATION_BUCKETS
                histogram = row.setdefault(name, {
                    "bounds": list(bounds), "buckets": [0] * (len(bounds) + 1),
                    "count": 0, "sum": 0.0,
                })
                bucket = next((i for i, bound in enumerate(bounds) if value <= bound), len(bounds))
                histogram["buckets"][bucket] += 1
                histogram["count"] += 1
                histogram["sum"] += value
            if now - self._last_emitted.get(key, float("-inf")) >= 60:
                self._last_emitted[key] = now
                emit = json.dumps(row, separators=(",", ":"))
        if emit is not None:
            logger.info("performance_histogram %s", emit)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(list(self._rows.values())))


class RequestTelemetryMiddleware:
    """ASGI completion includes yield-dependency cleanup and pool check-in."""
    def __init__(self, app, *, registry: PerformanceRegistry, routes: list,
                 request_id_factory: Callable[[str | None], str]) -> None:
        self.app = app
        self.registry = registry
        self.allowed_routes = frozenset(route.path for route in routes if hasattr(route, "path"))
        self.request_id_factory = request_id_factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        request_id = self.request_id_factory(Headers(scope=scope).get("X-Request-ID"))
        state = scope.setdefault("state", {})
        state.update(request_id=request_id, request_started=started)
        status = 500
        response_finished = None
        with capture_request(sampled=should_sample()) as timing:
            async def timed_send(message):
                nonlocal status, response_finished
                if message["type"] == "http.response.start":
                    status = message["status"]
                    headers = MutableHeaders(scope=message)
                    headers["X-Request-ID"] = request_id
                    headers["X-Backend-Release"] = self.registry.release
                    duration = (time.perf_counter() - started) * 1000
                    headers["Server-Timing"] = f"app;dur={duration:.2f}"
                    if timing.sampled:
                        headers["Server-Timing"] += f", sql;dur={timing.snapshot().get('sql_ms', 0):.2f}"
                await send(message)
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    response_finished = time.perf_counter()

            try:
                await self.app(scope, receive, timed_send)
            finally:
                duration = ((response_finished or time.perf_counter()) - started) * 1000
                template = getattr(scope.get("route"), "path", "<unmatched>")
                route = template if template in self.allowed_routes else "<unmatched>"
                self.registry.observe(route, scope.get("method", "<other>"), status, duration, timing)
                method = scope.get("method", "<other>")
                method = method if method in _METHODS else "<other>"
                logger.info("http_request request_id=%s method=%s route=%s status=%d duration_ms=%.2f release=%s",
                            request_id, method, route, status, duration, self.registry.release)

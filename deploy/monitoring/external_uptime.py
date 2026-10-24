"""Probe public uptime endpoints without logging response bodies or URLs."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


CHECKS = (
    ("https://api.igreja12.com.br/health", "ok"),
    ("https://api.igreja12.com.br/ready", "ready"),
    ("https://app.igreja12.com.br/", None),
)
SAFE_STATUSES = {"ok", "ready", "degraded"}


def probe(url: str) -> tuple[int, str | None]:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            http_status = response.status
            body = response.read(16384)
    except urllib.error.HTTPError as error:
        http_status = error.code
        try:
            body = error.read(16384)
        except Exception:
            body = b""
    except Exception:
        http_status = 0
        body = b""

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    value = payload.get("status") if isinstance(payload, dict) else None
    status = value if isinstance(value, str) and value in SAFE_STATUSES else None
    logged_status = status or ("other" if value is not None else "none")
    print(f"http_status={http_status:03d} status={logged_status}")
    return http_status, status


def main() -> int:
    failed = False
    for url, expected_status in CHECKS:
        healthy = False
        for attempt in range(3):
            http_status, status = probe(url)
            if http_status == 200 and (
                expected_status is None or status == expected_status
            ):
                healthy = True
                break
            if attempt < 2:
                time.sleep(10)
        if not healthy:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

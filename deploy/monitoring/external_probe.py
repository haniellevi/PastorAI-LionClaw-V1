#!/usr/bin/env python3
"""Credential-free probe executed outside the VPS by GitHub Actions."""

from __future__ import annotations

import datetime as dt
import json
import socket
import ssl
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

UTC = dt.timezone.utc
ENDPOINTS = (
    ("api-liveness", "https://api.igreja12.com.br/health", "health"),
    ("api-readiness", "https://api.igreja12.com.br/ready", "ready"),
    ("app-public", "https://app.igreja12.com.br", "page"),
    ("admin-public", "https://admin.igreja12.com.br", "page"),
    ("painel-public", "https://painel.igreja12.com.br", "page"),
)


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str


def endpoint(name: str, url: str, kind: str) -> Result:
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json,text/html",
            "user-agent": "PastorAI-Probe/1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            final_url = response.geturl()
            raw = response.read(131072)
    except Exception as exc:  # noqa: BLE001
        return Result(name, False, f"indisponivel ({type(exc).__name__})")
    if not 200 <= status < 300:
        return Result(name, False, f"HTTP {status}")
    if urllib.parse.urlsplit(final_url).scheme != "https":
        return Result(name, False, "redirecionamento sem HTTPS")
    if kind in {"health", "ready"}:
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Result(name, False, "JSON invalido")
        expected = "ok" if kind == "health" else "ready"
        if not isinstance(body, dict) or body.get("status") != expected:
            status_name = (
                body.get("status", "unknown")
                if isinstance(body, dict)
                else "unknown"
            )
            return Result(name, False, f"status={status_name}")
    elif len(raw.strip()) < 100:
        return Result(name, False, "pagina vazia")
    return Result(name, True, f"HTTP {status} HTTPS")


def certificate(host: str, minimum_days: int = 21) -> Result:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                expires = tls.getpeercert()["notAfter"]
        expiry = dt.datetime.strptime(
            expires, "%b %d %H:%M:%S %Y %Z"
        ).replace(tzinfo=UTC)
        days = (expiry - dt.datetime.now(UTC)).days
    except Exception as exc:  # noqa: BLE001
        return Result(
            f"tls-{host}",
            False,
            f"indisponivel ({type(exc).__name__})",
        )
    return Result(
        f"tls-{host}",
        days >= minimum_days,
        f"validade_days={days}",
    )


def run() -> list[Result]:
    results = [endpoint(*item) for item in ENDPOINTS]
    hosts = dict.fromkeys(urllib.parse.urlsplit(item[1]).hostname for item in ENDPOINTS)
    results.extend(certificate(str(host)) for host in hosts if host)
    return results


def main() -> int:
    results = run()
    report = {
        "checked_at": dt.datetime.now(UTC).isoformat(),
        "ok": all(item.ok for item in results),
        "checks": [asdict(item) for item in results],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(output, end="")
    Path("production-monitor-report.json").write_text(output, encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

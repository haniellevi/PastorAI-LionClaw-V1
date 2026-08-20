from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import external_probe as probe  # noqa: E402


class _Response:
    def __init__(self, final_url: str, body: bytes) -> None:
        self.status = 200
        self._final_url = final_url
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self, _limit: int) -> bytes:
        return self._body


def _probe_health(monkeypatch: pytest.MonkeyPatch, final_url: str) -> probe.Result:
    monkeypatch.setattr(
        probe.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(final_url, b'{"status":"ok"}'),
    )
    return probe.endpoint(
        "api-liveness",
        "https://api.igreja12.com.br/health",
        "health",
    )


@pytest.mark.parametrize(
    "final_url",
    [
        "https://other.example.invalid/health",
        "https://api.igreja12.com.br:444/health",
    ],
)
def test_endpoint_rejects_cross_origin_https_redirect(
    monkeypatch: pytest.MonkeyPatch, final_url: str
) -> None:
    result = _probe_health(monkeypatch, final_url)

    assert result.ok is False
    assert result.detail == "redirecionamento inesperado"


def test_endpoint_allows_same_origin_https_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _probe_health(monkeypatch, "https://api.igreja12.com.br:443/health/")

    assert result.ok is True
    assert result.detail == "HTTP 200 HTTPS"

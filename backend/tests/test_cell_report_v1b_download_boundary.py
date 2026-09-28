"""Bound transport before decompression/allocation and across streamed chunks."""
import gzip
import time

import httpx
import pytest

from app.services.evolution import EvolutionClient, EvolutionError


def _client(monkeypatch, response_factory):
    client = EvolutionClient.__new__(EvolutionClient)
    http = httpx.Client(transport=httpx.MockTransport(lambda request: response_factory()), base_url="https://synthetic.invalid")
    monkeypatch.setattr(client, "_require_config", lambda: ("https://synthetic.invalid", "synthetic-key"))
    monkeypatch.setattr(client, "_http_client", lambda _base: http)
    return client, http


def test_v1b_rejects_compressed_response_before_expansion(monkeypatch):
    from httpx._decoders import GZipDecoder
    compressed = gzip.compress(b"x" * (1024 * 1024))
    allocations = []
    original = GZipDecoder.decode
    def observed_decode(self, data):
        value = original(self, data)
        allocations.append(len(value))
        return value
    monkeypatch.setattr(GZipDecoder, "decode", observed_decode)
    client, http = _client(monkeypatch, lambda: httpx.Response(200,
        headers={"content-encoding": "gzip", "content-length": str(len(compressed))},
        stream=httpx.ByteStream(compressed)))
    try:
        with pytest.raises(EvolutionError):
            client.get_audio_media_bytes_limited("synthetic", {"id": "synthetic"}, max_bytes=16, timeout_seconds=1)
    finally:
        http.close()
    assert allocations == []


def test_v1b_download_deadline_is_not_restarted_by_each_chunk(monkeypatch):
    class SlowBytes(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b'{"base64":', b'"YQ==","mimetype":"audio/ogg"}'):
                time.sleep(.025)
                yield chunk
    client, http = _client(monkeypatch, lambda: httpx.Response(200, stream=SlowBytes()))
    try:
        with pytest.raises(EvolutionError):
            client.get_audio_media_bytes_limited("synthetic", {"id": "synthetic"}, max_bytes=16, timeout_seconds=.03)
    finally:
        http.close()


def test_v1b_download_normalizes_excessive_json_nesting(monkeypatch):
    raw = b"[" * 10000 + b"]" * 10000
    client, http = _client(monkeypatch, lambda: httpx.Response(200, stream=httpx.ByteStream(raw)))
    try:
        with pytest.raises(EvolutionError):
            client.get_audio_media_bytes_limited("synthetic", {"id": "synthetic"}, max_bytes=32768, timeout_seconds=1)
    finally:
        http.close()

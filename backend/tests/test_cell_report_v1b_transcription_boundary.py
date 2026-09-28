"""Provider facts must be legible before settling the shared audio budget."""
from types import SimpleNamespace

import pytest

from app.services import llm


def _client(monkeypatch, *, duration, transcript="presentes: 10"):
    state = SimpleNamespace(closed=False)
    def close():
        state.closed = True
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(text=transcript, duration=duration))), close=close)
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(llm, "_build_openai_client", lambda *_a, **_kw: client)
    return state


@pytest.mark.parametrize("duration", (None, 0, True, False, float("nan"), float("inf"), -1))
def test_strict_audio_rejects_missing_or_unusable_usage(monkeypatch, duration):
    state = _client(monkeypatch, duration=duration)
    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio("openai", "synthetic-key", audio_bytes=b"synthetic",
            mime_type="audio/wav", timeout_seconds=180, max_retries=0, require_real_result=True)
    assert state.closed


def test_strict_audio_closes_provider_client_after_success(monkeypatch):
    state = _client(monkeypatch, duration=1.0)
    result = llm.transcribe_audio("openai", "synthetic-key", audio_bytes=b"synthetic",
        mime_type="audio/wav", timeout_seconds=180, max_retries=0, require_real_result=True)
    assert result.duracao_segundos == 1.0
    assert state.closed

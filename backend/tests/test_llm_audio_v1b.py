"""V1b-only strict controls layered over legacy audio transcription."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.services import llm


def test_v1b_transcription_refuses_simulated_result_when_egress_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: False)
    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_args, **_kwargs: pytest.fail("provider must not be built"),
    )

    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio(
            "openai",
            "synthetic-key",
            audio_bytes=b"audio",
            mime_type="audio/ogg",
            timeout_seconds=179.0,
            max_retries=0,
            require_real_result=True,
        )


def test_v1b_transcription_passes_hard_timeout_and_zero_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)

    class _Transcriptions:
        def create(self, **kwargs):
            seen["request"] = kwargs
            return SimpleNamespace(text="10 presentes", duration=12.5)

    def fake_client(_key: str, *, timeout: float, max_retries: int):
        seen["client"] = (timeout, max_retries)
        return SimpleNamespace(audio=SimpleNamespace(transcriptions=_Transcriptions()))

    monkeypatch.setattr(llm, "_build_openai_client", fake_client)

    result = llm.transcribe_audio(
        "openai",
        "synthetic-key",
        audio_bytes=b"audio",
        mime_type="audio/ogg",
        timeout_seconds=179.0,
        max_retries=0,
        require_real_result=True,
    )

    assert result.texto == "10 presentes"
    assert seen["client"] == (179.0, 0)
    assert seen["request"]["timeout"] == 179.0


@pytest.mark.parametrize("duration", [None, 0.0, True, math.inf, math.nan, -1.0])
def test_v1b_transcription_rejects_nonfinite_or_negative_duration(
    monkeypatch: pytest.MonkeyPatch,
    duration: float,
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_args, **_kwargs: SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(text="ok", duration=duration)
                )
            )
        ),
    )

    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio(
            "openai",
            "synthetic-key",
            audio_bytes=b"audio",
            mime_type="audio/ogg",
            timeout_seconds=179.0,
            max_retries=0,
            require_real_result=True,
        )


def test_transcription_closes_provider_client_after_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    closed: list[bool] = []

    class _Client:
        audio = SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(text="ok", duration=1.0)
            )
        )

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(llm, "_build_openai_client", lambda *_args, **_kwargs: _Client())

    llm.transcribe_audio(
        "openai", "synthetic-key", audio_bytes=b"audio", mime_type="audio/ogg"
    )

    assert closed == [True]

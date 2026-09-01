"""transcribe_audio: type/size validation, external-sends gate and provider errors."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import llm

_SMALL_OGG = b"\x00" * 16


def test_rejects_unsupported_mime_type_before_any_provider_call(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: pytest.fail("provider must not be called"),
    )

    with pytest.raises(llm.UnsupportedAudioTypeError):
        llm.transcribe_audio(
            "openai",
            "sk-test",
            audio_bytes=_SMALL_OGG,
            mime_type="video/mp4",
        )


def test_rejects_oversized_audio_before_any_provider_call(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: pytest.fail("provider must not be called"),
    )
    oversized = b"\x00" * (llm.MAX_AUDIO_BYTES + 1)

    with pytest.raises(llm.AudioTooLargeError):
        llm.transcribe_audio(
            "openai",
            "sk-test",
            audio_bytes=oversized,
            mime_type="audio/ogg",
        )


def test_rejects_empty_audio(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)

    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio(
            "openai", "sk-test", audio_bytes=b"", mime_type="audio/ogg"
        )


def test_rejects_missing_credential_before_type_or_gate_checks() -> None:
    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio(
            "openai", "  ", audio_bytes=_SMALL_OGG, mime_type="audio/ogg"
        )


def test_unsupported_provider_is_rejected() -> None:
    with pytest.raises(llm.UnsupportedProviderError):
        llm.transcribe_audio(
            "gemini", "sk-test", audio_bytes=_SMALL_OGG, mime_type="audio/ogg"
        )


def test_closed_gate_returns_simulated_result_without_calling_provider(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: False)
    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: pytest.fail("provider must not be called"),
    )

    result = llm.transcribe_audio(
        "openai", "sk-test", audio_bytes=_SMALL_OGG, mime_type="audio/ogg"
    )

    assert result.duracao_segundos == 0.0
    assert result.custo == 0.0
    assert "simulada" in result.texto.lower()


def test_transcribes_and_estimates_cost_from_duration(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    calls: list[dict[str, object]] = []

    class _Transcriptions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text="10 presentes, 2 visitantes", duration=90.0)

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: SimpleNamespace(
            audio=SimpleNamespace(transcriptions=_Transcriptions())
        ),
    )

    result = llm.transcribe_audio(
        "openai",
        "sk-test",
        audio_bytes=_SMALL_OGG,
        mime_type="audio/ogg",
        filename="relatorio",
    )

    assert result.texto == "10 presentes, 2 visitantes"
    assert result.duracao_segundos == 90.0
    # 90s = 1.5 min * $0.006/min
    assert result.custo == pytest.approx(0.009)
    assert len(calls) == 1
    assert calls[0]["model"] == llm.TRANSCRIPTION_MODEL
    assert calls[0]["file"] == ("relatorio.ogg", _SMALL_OGG, "audio/ogg")


def test_negative_duration_from_provider_is_clamped_to_zero_cost(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)

    class _Transcriptions:
        def create(self, **_kwargs):
            return SimpleNamespace(text="ok", duration=-1.0)

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: SimpleNamespace(
            audio=SimpleNamespace(transcriptions=_Transcriptions())
        ),
    )

    result = llm.transcribe_audio(
        "openai", "sk-test", audio_bytes=_SMALL_OGG, mime_type="audio/ogg"
    )

    assert result.duracao_segundos == 0.0
    assert result.custo == 0.0


def test_authentication_error_is_wrapped_as_llm_provider_error(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)

    from openai import AuthenticationError

    class _Transcriptions:
        def create(self, **_kwargs):
            raise AuthenticationError(
                message="bad key",
                response=SimpleNamespace(status_code=401, headers={}, request=None),
                body=None,
            )

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: SimpleNamespace(
            audio=SimpleNamespace(transcriptions=_Transcriptions())
        ),
    )

    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio(
            "openai", "sk-test", audio_bytes=_SMALL_OGG, mime_type="audio/ogg"
        )


def test_connection_error_is_wrapped_as_llm_provider_error(monkeypatch) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)

    from openai import APIConnectionError

    class _Transcriptions:
        def create(self, **_kwargs):
            raise APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: SimpleNamespace(
            audio=SimpleNamespace(transcriptions=_Transcriptions())
        ),
    )

    with pytest.raises(llm.LLMProviderError):
        llm.transcribe_audio(
            "openai", "sk-test", audio_bytes=_SMALL_OGG, mime_type="audio/ogg"
        )


@pytest.mark.parametrize(
    "mime_type,expected_extension",
    [
        ("audio/ogg", "ogg"),
        ("audio/opus", "ogg"),
        ("audio/mpeg", "mp3"),
        ("audio/mp4", "mp4"),
        ("audio/wav", "wav"),
        ("AUDIO/WAV", "wav"),
    ],
)
def test_supported_mime_types_map_to_expected_extension(
    monkeypatch, mime_type: str, expected_extension: str
) -> None:
    monkeypatch.setattr(llm, "external_sends_allowed", lambda: True)
    seen_files: list[tuple[str, bytes, str]] = []

    class _Transcriptions:
        def create(self, **kwargs):
            seen_files.append(kwargs["file"])
            return SimpleNamespace(text="", duration=0.0)

    monkeypatch.setattr(
        llm,
        "_build_openai_client",
        lambda *_a, **_k: SimpleNamespace(
            audio=SimpleNamespace(transcriptions=_Transcriptions())
        ),
    )

    llm.transcribe_audio(
        "openai", "sk-test", audio_bytes=_SMALL_OGG, mime_type=mime_type
    )

    assert seen_files[0][0].endswith(f".{expected_extension}")

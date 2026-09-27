"""Pure V1b audio gates and deterministic consent command boundaries."""

from __future__ import annotations

import math
import io
import time
import uuid
import wave
from pathlib import Path

import pytest

from app.services import cell_report_audio as audio


TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def test_audio_gate_is_inert_without_reviewed_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS", str(TENANT))
    monkeypatch.setattr(audio, "CELL_REPORT_AUDIO_APPROVED_RELEASE_ID", None)
    monkeypatch.setattr(audio, "cell_report_enabled_from_environment", lambda _tenant: True)

    assert audio.cell_report_audio_enabled_from_environment(TENANT) is False


def test_audio_gate_requires_v1a_and_exact_audio_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS", str(TENANT))
    monkeypatch.setattr(audio, "CELL_REPORT_AUDIO_APPROVED_RELEASE_ID", "v1b-reviewed")
    monkeypatch.setattr(audio, "cell_report_enabled_from_environment", lambda tenant: tenant == TENANT)

    assert audio.cell_report_audio_enabled_from_environment(TENANT) is True
    assert audio.cell_report_audio_enabled_from_environment(uuid.uuid4()) is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ACEITO AUDIO", audio.AudioConsentCommand.ACCEPT),
        ("aceito áudio!", audio.AudioConsentCommand.ACCEPT),
        (" PARAR ÁUDIO. ", audio.AudioConsentCommand.REVOKE),
        ("sim", None),
        ("aceito audio para sempre", None),
        ("parar audio e lembretes", None),
        (None, None),
    ],
)
def test_audio_consent_uses_only_exact_new_text_commands(
    value: object,
    expected: object,
) -> None:
    assert audio.parse_audio_consent_command(value) is expected


def test_audio_metadata_accepts_only_local_bounded_audio() -> None:
    validated = audio.validate_audio_metadata(
        mime_type="audio/ogg",
        byte_size=5 * 1024 * 1024,
        duration_seconds=120.0,
    )

    assert validated.mime_type == "audio/ogg"
    assert validated.byte_size == 5 * 1024 * 1024
    assert validated.duration_seconds == 120.0


def test_audio_mime_parameters_are_canonicalized_before_v1b_processing() -> None:
    assert audio.canonical_audio_mime("audio/ogg; codecs=opus") == "audio/ogg"
    assert audio.validate_audio_metadata(
        mime_type="Audio/OGG; codecs=opus",
        byte_size=12,
        duration_seconds=1.0,
    ).mime_type == "audio/ogg"


@pytest.mark.parametrize(
    ("mime_type", "byte_size", "duration_seconds"),
    [
        ("video/mp4", 12, 1.0),
        ("audio/ogg", 5 * 1024 * 1024 + 1, 1.0),
        ("audio/ogg", 12, 0.0),
        ("audio/ogg", 12, 120.1),
        ("audio/ogg", 12, math.inf),
        ("audio/ogg", 12, True),
    ],
)
def test_audio_metadata_fails_closed_before_transcription(
    mime_type: object,
    byte_size: object,
    duration_seconds: object,
) -> None:
    with pytest.raises(audio.CellReportAudioError):
        audio.validate_audio_metadata(
            mime_type=mime_type,
            byte_size=byte_size,
            duration_seconds=duration_seconds,
        )


def _synthetic_wav(duration_ms: int) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * (duration_ms * 16))
    return stream.getvalue()


def test_decoder_measures_real_decoded_samples_not_declared_duration() -> None:
    decoded = audio.decode_audio_bytes(
        _synthetic_wav(120_000),
        declared_mime="audio/wav",
    )

    assert decoded.mime_type == "audio/wav"
    assert decoded.duration_seconds == pytest.approx(120.0)
    assert len(decoded.content_sha256) == 64


def test_decoder_rejects_audio_with_one_extra_decoded_millisecond() -> None:
    with pytest.raises(audio.CellReportAudioError):
        audio.decode_audio_bytes(
            _synthetic_wav(120_001),
            declared_mime="audio/wav",
        )


def test_decoder_fails_closed_when_binary_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _name: None)

    with pytest.raises(audio.CellReportAudioError):
        audio.decode_audio_bytes(_synthetic_wav(1), declared_mime="audio/wav")


def test_decoder_uses_one_deadline_for_probe_and_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_deadlines: list[float] = []

    monkeypatch.setattr(audio, "_decoder_binary", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(audio.time, "monotonic", lambda: 500.0)

    def fake_run_decoder(
        command: list[str],
        *,
        deadline_at: float,
        max_stdout_bytes: int,
        input_bytes: bytes,
    ) -> bytes:
        observed_deadlines.append(deadline_at)
        assert max_stdout_bytes == audio._DECODE_MAX_BYTES
        assert command[:8] == [
            "/bin/ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "pipe",
            "-f",
            "wav",
        ]
        assert "pipe:0" in command
        assert input_bytes == _synthetic_wav(1)
        return b"\x00\x00" * 16

    monkeypatch.setattr(audio, "_run_decoder", fake_run_decoder)

    decoded = audio.decode_audio_bytes(
        _synthetic_wav(1),
        declared_mime="audio/wav",
        timeout_seconds=10.0,
    )

    assert decoded.duration_seconds == pytest.approx(0.001)
    assert observed_deadlines == [510.0]


def test_decoder_requires_native_launcher_not_python_preexec() -> None:
    source = Path(audio.__file__).read_text(encoding="utf-8")

    assert "preexec_fn" not in source
    assert 'shutil.which("prlimit")' in source
    assert "ffprobe" not in source
    assert '"pipe:0"' in source


def test_backend_image_installs_the_v1b_decoder() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"

    assert "apt-get install --no-install-recommends --yes ffmpeg" in dockerfile.read_text(
        encoding="utf-8"
    )

"""Independent decoder boundaries, with generated silence and fake slow tools."""
import math
import subprocess
import tempfile
import time

import pytest

from app.services import cell_report_audio as audio
from tests.cell_report_audio_samples import synthetic_wav


@pytest.mark.parametrize("payload,mime", (
    (b"", "audio/wav"),
    (b"x" * (5 * 1024 * 1024 + 1), "audio/wav"),
    (b"not an audio container", "audio/ogg"),
    (synthetic_wav(), "audio/mp3"),
    (synthetic_wav(), "video/mp4"),
))
def test_decoder_rejects_invalid_content_and_mime(payload, mime):
    with pytest.raises(audio.CellReportAudioError):
        audio.decode_audio_bytes(payload, declared_mime=mime)


@pytest.mark.parametrize("deadline", (0, -1, True, math.nan, math.inf, 11))
def test_decoder_rejects_illegible_or_unbounded_deadline(deadline):
    with pytest.raises(audio.CellReportAudioError):
        audio.decode_audio_bytes(synthetic_wav(), declared_mime="audio/wav", timeout_seconds=deadline)


@pytest.mark.parametrize("fail", (False, True))
def test_decoder_keeps_audio_in_pipes_without_temporary_files(monkeypatch, fail):
    def unexpected_file(*_args, **_kwargs):
        pytest.fail("The V1b decoder must not materialize private audio on disk")
    monkeypatch.setattr(tempfile, "TemporaryDirectory", unexpected_file)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", unexpected_file)
    if fail:
        with pytest.raises(audio.CellReportAudioError):
            audio.decode_audio_bytes(b"broken synthetic container", declared_mime="audio/wav")
    else:
        result = audio.decode_audio_bytes(synthetic_wav(), declared_mime="audio/wav")
        assert result.duration_seconds == pytest.approx(1.0)


def test_decoder_deadline_includes_process_setup(monkeypatch):
    calls = []
    class SlowProcess:
        returncode = 0
        def __init__(self, command, **kwargs):
            assert "preexec_fn" not in kwargs
            assert kwargs["start_new_session"] is True
            self.command = command
            time.sleep(.03)
        def communicate(self, input=None, timeout=None):
            if timeout is None:
                return b"", None  # Reaped after synthetic cancellation.
            calls.append(timeout)
            if timeout < .03:
                raise subprocess.TimeoutExpired(self.command, timeout)
            time.sleep(.03)
            return b'{"format":{"format_name":"wav"}}', None
    monkeypatch.setattr(audio.subprocess, "Popen", SlowProcess)
    monkeypatch.setattr(audio, "_terminate_decoder_process", lambda process: None)
    with pytest.raises(audio.CellReportAudioError):
        audio.decode_audio_bytes(synthetic_wav(), declared_mime="audio/wav", timeout_seconds=.05)
    assert len(calls) <= 2


@pytest.mark.parametrize("container,codec,mime", (
    ("ogg", "libopus", "audio/ogg"),
    ("ogg", "libopus", "audio/ogg; codecs=opus"),
    ("webm", "libopus", "audio/webm"),
    ("mp3", "libmp3lame", "audio/mp3"),
))
def test_decoder_accepts_synthetic_encoded_voice_containers(container, codec, mime):
    generated = subprocess.run([
        "/usr/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
        "-t", "0.25", "-c:a", codec, "-f", container, "pipe:1",
    ], capture_output=True, timeout=5, check=True)
    result = audio.decode_audio_bytes(generated.stdout, declared_mime=mime)
    assert .2 <= result.duration_seconds < .4
    assert result.mime_type == mime.split(";", 1)[0]

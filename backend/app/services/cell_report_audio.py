"""Closed V1b audio boundaries shared by the worker and maintenance paths.

This module contains no provider, storage or database I/O.  Its gate and
validation functions are intentionally usable before a session is opened so a
listed environment cannot cause an audio fetch by itself.
"""

from __future__ import annotations

import math
import os
import re
import hashlib
import signal
import shutil
import subprocess
import time
import unicodedata
import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.services.cell_report_whatsapp import cell_report_enabled_from_environment
from app.services.llm import SUPPORTED_AUDIO_MIME_TYPES


# A listed tenant stays inert until a reviewed V1b release is named in code.
CELL_REPORT_AUDIO_APPROVED_RELEASE_ID: str | None = None
CELL_REPORT_AUDIO_CONSENT_VERSION = "v1"
CELL_REPORT_AUDIO_MAX_BYTES = 5 * 1024 * 1024
CELL_REPORT_AUDIO_MAX_DURATION_SECONDS = 120.0
CELL_REPORT_AUDIO_MAX_PER_REPORT = 3
CELL_REPORT_AUDIO_TRANSCRIPTION_DEADLINE_SECONDS = 180.0
CELL_REPORT_AUDIO_DECODER_DEADLINE_SECONDS = 10.0
_DECODE_SAMPLE_RATE = 16_000
_DECODE_SAMPLE_WIDTH = 2
_DECODE_MAX_SECONDS = CELL_REPORT_AUDIO_MAX_DURATION_SECONDS + 1.0
_DECODE_MAX_BYTES = int(_DECODE_MAX_SECONDS * _DECODE_SAMPLE_RATE * _DECODE_SAMPLE_WIDTH)
_PROBE_MAX_BYTES = 8 * 1024

_COMMAND_WORDS = re.compile(r"^[a-z]+(?: [a-z]+)*(?:[.!?]+)?$")


class CellReportAudioError(ValueError):
    """Fail-closed V1b input or gate rejection without any I/O."""


class AudioConsentCommand(StrEnum):
    ACCEPT = "aceito"
    REVOKE = "revogado"


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    """Locally verified media facts, never a caller-provided URL or text."""

    mime_type: str
    byte_size: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class DecodedAudio(AudioMetadata):
    """A decoder-verified container with no retained binary or transcript."""

    content_sha256: str


def _reviewed_release() -> bool:
    return (
        type(CELL_REPORT_AUDIO_APPROVED_RELEASE_ID) is str
        and bool(CELL_REPORT_AUDIO_APPROVED_RELEASE_ID.strip())
    )


def _allowlisted_ids(raw: object) -> tuple[uuid.UUID, ...] | None:
    if type(raw) is not str or not raw.strip():
        return None
    pieces = raw.split(",")
    if any(not piece.strip() for piece in pieces):
        return None
    try:
        values = tuple(uuid.UUID(piece.strip()) for piece in pieces)
    except (AttributeError, ValueError):
        return None
    if len(values) != len(set(values)):
        return None
    return values


def cell_report_audio_enabled_from_environment(igreja_id: object) -> bool:
    """Require reviewed V1b, reviewed V1a/S3 and an exact audio allowlist."""

    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    if not _reviewed_release() or not cell_report_enabled_from_environment(igreja_id):
        return False
    allowed = _allowlisted_ids(os.environ.get("CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS", ""))
    return allowed is not None and igreja_id in allowed


def _normalize_command(value: object) -> str | None:
    if type(value) is not str:
        return None
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", value).casefold()
        if unicodedata.category(character) not in {"Mn", "Cf"}
    )
    normalized = " ".join(normalized.split())
    if not normalized or len(normalized) > 32 or not _COMMAND_WORDS.fullmatch(normalized):
        return None
    return normalized.rstrip(".!?")


def parse_audio_consent_command(value: object) -> AudioConsentCommand | None:
    """Recognize only explicit new-text V1b commands, never generic ``SIM``."""

    command = _normalize_command(value)
    if command == "aceito audio":
        return AudioConsentCommand.ACCEPT
    if command == "parar audio":
        return AudioConsentCommand.REVOKE
    return None


def canonical_audio_mime(value: object) -> str | None:
    """Return the closed MIME used by V1b, dropping harmless MIME parameters."""

    if type(value) is not str:
        return None
    base = value.split(";", 1)[0].strip().lower()
    return base if base in SUPPORTED_AUDIO_MIME_TYPES else None


def validate_audio_metadata(
    *,
    mime_type: object,
    byte_size: object,
    duration_seconds: object,
) -> AudioMetadata:
    """Validate only bounded facts measured from a private local decoder."""

    normalized_mime = canonical_audio_mime(mime_type)
    if normalized_mime is None:
        raise CellReportAudioError("mídia de áudio indisponível")
    if type(byte_size) is not int or byte_size <= 0 or byte_size > CELL_REPORT_AUDIO_MAX_BYTES:
        raise CellReportAudioError("mídia de áudio indisponível")
    if type(duration_seconds) not in (int, float):
        raise CellReportAudioError("mídia de áudio indisponível")
    try:
        duration = float(duration_seconds)
    except (OverflowError, ValueError):
        raise CellReportAudioError("mídia de áudio indisponível") from None
    if not math.isfinite(duration) or duration <= 0.0 or duration > CELL_REPORT_AUDIO_MAX_DURATION_SECONDS:
        raise CellReportAudioError("mídia de áudio indisponível")
    return AudioMetadata(
        mime_type=normalized_mime,
        byte_size=byte_size,
        duration_seconds=duration,
    )


_DEMUXER_FOR_MIME: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mov",
    "audio/m4a": "mov",
    "audio/x-m4a": "mov",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "matroska,webm",
}


def _decoder_binary() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if (
        type(ffmpeg) is not str
        or not os.path.isabs(ffmpeg)
        or not os.path.isfile(ffmpeg)
        or not os.access(ffmpeg, os.X_OK)
    ):
        raise CellReportAudioError("validador de áudio indisponível")
    return ffmpeg


def _decoder_launcher() -> str:
    """Return the native, process-safe resource-limit launcher."""

    launcher = shutil.which("prlimit")
    if (
        type(launcher) is not str
        or not os.path.isabs(launcher)
        or not os.path.isfile(launcher)
        or not os.access(launcher, os.X_OK)
    ):
        raise CellReportAudioError("validador de áudio indisponível")
    return launcher


def _bounded_decoder_command(command: list[str]) -> list[str]:
    """Wrap trusted decoder binaries without unsafe Python child hooks."""

    return [
        _decoder_launcher(),
        "--cpu=8:8",
        "--as=1073741824:1073741824",
        f"--fsize={_DECODE_MAX_BYTES + 1}:{_DECODE_MAX_BYTES + 1}",
        "--",
        *command,
    ]


def _remaining_decoder_seconds(deadline_at: float) -> float:
    remaining = deadline_at - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0.0:
        raise CellReportAudioError("mídia de áudio indisponível")
    return remaining


def _terminate_decoder_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - V1b image is Linux only.
            process.kill()
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _run_decoder(
    command: list[str],
    *,
    deadline_at: float,
    max_stdout_bytes: int,
    input_bytes: bytes,
) -> bytes:
    try:
        process = subprocess.Popen(
            _bounded_decoder_command(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except (CellReportAudioError, OSError, subprocess.SubprocessError):
        raise CellReportAudioError("mídia de áudio indisponível") from None
    try:
        stdout, _ = process.communicate(
            input=input_bytes,
            timeout=_remaining_decoder_seconds(deadline_at),
        )
    except subprocess.TimeoutExpired:
        _terminate_decoder_process(process)
        try:
            process.communicate()
        except OSError:
            pass
        raise CellReportAudioError("mídia de áudio indisponível") from None
    except (OSError, subprocess.SubprocessError, CellReportAudioError):
        _terminate_decoder_process(process)
        raise CellReportAudioError("mídia de áudio indisponível") from None
    if process.returncode != 0 or len(stdout) > max_stdout_bytes:
        raise CellReportAudioError("mídia de áudio indisponível")
    return stdout


def decode_audio_bytes(
    audio_bytes: object,
    *,
    declared_mime: object,
    timeout_seconds: object = CELL_REPORT_AUDIO_DECODER_DEADLINE_SECONDS,
) -> DecodedAudio:
    """Decode a private, bounded blob and measure real samples before OpenAI.

    The caller's MIME selects a closed demuxer and bytes reach FFmpeg only on
    ``pipe:0``. No auto-probe, filesystem input or non-pipe protocol can turn
    a forged container into a local playlist. Duration comes exclusively from
    actual s16le samples and therefore cannot be supplied by forged metadata.
    """

    if type(audio_bytes) is not bytes:
        raise CellReportAudioError("mídia de áudio indisponível")
    normalized_mime = canonical_audio_mime(declared_mime)
    if normalized_mime not in _DEMUXER_FOR_MIME:
        raise CellReportAudioError("mídia de áudio indisponível")
    if len(audio_bytes) <= 0 or len(audio_bytes) > CELL_REPORT_AUDIO_MAX_BYTES:
        raise CellReportAudioError("mídia de áudio indisponível")
    if type(timeout_seconds) not in (int, float):
        raise CellReportAudioError("mídia de áudio indisponível")
    try:
        deadline = float(timeout_seconds)
    except (OverflowError, ValueError):
        raise CellReportAudioError("mídia de áudio indisponível") from None
    if not math.isfinite(deadline) or deadline <= 0.0 or deadline > CELL_REPORT_AUDIO_DECODER_DEADLINE_SECONDS:
        raise CellReportAudioError("mídia de áudio indisponível")
    deadline_at = time.monotonic() + deadline
    ffmpeg = _decoder_binary()
    pcm = _run_decoder(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "pipe",
            "-f",
            _DEMUXER_FOR_MIME[normalized_mime],
            "-i",
            "pipe:0",
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(_DECODE_SAMPLE_RATE),
            "-t",
            str(_DECODE_MAX_SECONDS),
            "-f",
            "s16le",
            "pipe:1",
        ],
        deadline_at=deadline_at,
        max_stdout_bytes=_DECODE_MAX_BYTES,
        input_bytes=audio_bytes,
    )
    if not pcm or len(pcm) % _DECODE_SAMPLE_WIDTH:
        raise CellReportAudioError("mídia de áudio indisponível")
    duration = len(pcm) / (_DECODE_SAMPLE_RATE * _DECODE_SAMPLE_WIDTH)
    metadata = validate_audio_metadata(
        mime_type=normalized_mime,
        byte_size=len(audio_bytes),
        duration_seconds=duration,
    )
    return DecodedAudio(
        mime_type=metadata.mime_type,
        byte_size=metadata.byte_size,
        duration_seconds=metadata.duration_seconds,
        content_sha256=hashlib.sha256(audio_bytes).hexdigest(),
    )


__all__ = (
    "AudioConsentCommand",
    "AudioMetadata",
    "DecodedAudio",
    "CELL_REPORT_AUDIO_APPROVED_RELEASE_ID",
    "CELL_REPORT_AUDIO_CONSENT_VERSION",
    "CELL_REPORT_AUDIO_MAX_BYTES",
    "CELL_REPORT_AUDIO_MAX_DURATION_SECONDS",
    "CELL_REPORT_AUDIO_MAX_PER_REPORT",
    "CELL_REPORT_AUDIO_TRANSCRIPTION_DEADLINE_SECONDS",
    "CellReportAudioError",
    "canonical_audio_mime",
    "cell_report_audio_enabled_from_environment",
    "decode_audio_bytes",
    "parse_audio_consent_command",
    "validate_audio_metadata",
)

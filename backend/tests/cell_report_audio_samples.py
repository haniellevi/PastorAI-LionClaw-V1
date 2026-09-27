"""Synthetic silence only, for independent V1b decoder/privacy tests."""
import io
import wave


def synthetic_wav(duration_ms=1000, *, sample_rate=8000, channels=1):
    frames = duration_ms * sample_rate // 1000
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(b'\x00\x00' * frames * channels)
    return stream.getvalue()

import io
import wave


def wav_bytes(ms: int, rate: int = 24000) -> bytes:
    """A silent mono 16-bit WAV of the given length."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * (rate * ms // 1000))
    return buf.getvalue()

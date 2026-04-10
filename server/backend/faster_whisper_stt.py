from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WHISPER_MODEL = "large-v3"
DEFAULT_WHISPER_DEVICE = "cpu"
DEFAULT_WHISPER_COMPUTE_TYPE = "int8"
DEFAULT_BEAM_SIZE = 5

_MODEL_LOCK = threading.Lock()
_WHISPER_MODEL = None


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None = None


def get_whisper_model():
    global _WHISPER_MODEL

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Add it to the backend environment first."
        ) from exc

    with _MODEL_LOCK:
        if _WHISPER_MODEL is None:
            _WHISPER_MODEL = WhisperModel(
                DEFAULT_WHISPER_MODEL,
                device=DEFAULT_WHISPER_DEVICE,
                compute_type=DEFAULT_WHISPER_COMPUTE_TYPE,
            )
        return _WHISPER_MODEL


def transcribe_audio_file(
    audio_path: Path,
    *,
    beam_size: int = DEFAULT_BEAM_SIZE,
) -> TranscriptionResult:
    model = get_whisper_model()
    segments, info = model.transcribe(str(audio_path), beam_size=beam_size)

    text_parts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            text_parts.append(text)

    normalized_text = " ".join(" ".join(text_parts).split())
    return TranscriptionResult(
        text=normalized_text,
        language=getattr(info, "language", None),
    )

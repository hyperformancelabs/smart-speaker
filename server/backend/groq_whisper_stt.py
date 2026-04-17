from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .config import (
        GROQ_API_KEY,
        GROQ_STT_BASE_URL,
        GROQ_STT_LANGUAGE,
        GROQ_STT_MAX_RETRIES,
        GROQ_STT_MODEL,
        GROQ_STT_PROMPT,
        GROQ_STT_RESPONSE_FORMAT,
        GROQ_STT_TEMPERATURE,
        GROQ_STT_TIMEOUT_SECONDS,
        GROQ_STT_TIMESTAMP_GRANULARITIES,
    )
except ImportError:
    from config import (
        GROQ_API_KEY,
        GROQ_STT_BASE_URL,
        GROQ_STT_LANGUAGE,
        GROQ_STT_MAX_RETRIES,
        GROQ_STT_MODEL,
        GROQ_STT_PROMPT,
        GROQ_STT_RESPONSE_FORMAT,
        GROQ_STT_TEMPERATURE,
        GROQ_STT_TIMEOUT_SECONDS,
        GROQ_STT_TIMESTAMP_GRANULARITIES,
    )


DEFAULT_TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"
DEFAULT_RESPONSE_FORMAT = "verbose_json"

_CLIENT_LOCK = threading.Lock()
_GROQ_CLIENT = None


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None = None


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _extract_response_field(response: object, field_name: str) -> Any:
    if hasattr(response, field_name):
        return getattr(response, field_name)
    if isinstance(response, dict):
        return response.get(field_name)
    return None


def get_groq_client():
    global _GROQ_CLIENT

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing in server/backend/.env.")

    try:
        from groq import Groq
    except ImportError as exc:
        raise RuntimeError("groq is not installed. Add it to the backend environment first.") from exc

    with _CLIENT_LOCK:
        if _GROQ_CLIENT is None:
            client_kwargs: dict[str, Any] = {
                "api_key": GROQ_API_KEY,
                "timeout": GROQ_STT_TIMEOUT_SECONDS,
                "max_retries": GROQ_STT_MAX_RETRIES,
            }
            if GROQ_STT_BASE_URL:
                client_kwargs["base_url"] = GROQ_STT_BASE_URL
            _GROQ_CLIENT = Groq(**client_kwargs)
        return _GROQ_CLIENT


def _build_transcription_request(audio_path: Path) -> dict[str, Any]:
    request: dict[str, Any] = {
        "file": (audio_path.name, audio_path.read_bytes()),
        "model": GROQ_STT_MODEL or DEFAULT_TRANSCRIPTION_MODEL,
        "response_format": GROQ_STT_RESPONSE_FORMAT or DEFAULT_RESPONSE_FORMAT,
        "temperature": GROQ_STT_TEMPERATURE,
    }
    if GROQ_STT_LANGUAGE:
        request["language"] = GROQ_STT_LANGUAGE
    if GROQ_STT_PROMPT:
        request["prompt"] = GROQ_STT_PROMPT
    if (
        GROQ_STT_TIMESTAMP_GRANULARITIES
        and request["response_format"] == "verbose_json"
    ):
        request["timestamp_granularities"] = list(GROQ_STT_TIMESTAMP_GRANULARITIES)
    return request


def transcribe_audio_file(
    audio_path: Path,
    *,
    beam_size: int | None = None,
) -> TranscriptionResult:
    del beam_size  # Kept for backward compatibility with the old local Whisper adapter.

    client = get_groq_client()
    transcription = client.audio.transcriptions.create(**_build_transcription_request(audio_path))

    text = _extract_response_field(transcription, "text")
    if text is None and isinstance(transcription, str):
        text = transcription

    return TranscriptionResult(
        text=_normalize_text(text),
        language=_extract_response_field(transcription, "language"),
    )

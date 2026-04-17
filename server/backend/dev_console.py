from __future__ import annotations

from pathlib import Path
import json
import uuid
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from assistant_service import run_assistant_turn
from groq_whisper_stt import transcribe_audio_file


BASE_DIR = Path(__file__).resolve().parent
BROWSER_AUDIO_UPLOAD_DIR = BASE_DIR / "browser_audio_uploads"
DEFAULT_BROWSER_DEVICE_ID = "browser-lab"


def coerce_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def parse_json_object(value: object, *, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)

    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        return dict(parsed)

    raise ValueError(f"{field_name} must be a JSON object")


def save_browser_audio_upload(upload: FileStorage) -> Path:
    filename = secure_filename(upload.filename or "") or "input"
    suffix = Path(filename).suffix.lower() or ".webm"
    if not Path(filename).suffix:
        filename = f"{filename}{suffix}"

    request_dir = BROWSER_AUDIO_UPLOAD_DIR / uuid.uuid4().hex
    request_dir.mkdir(parents=True, exist_ok=True)
    destination = request_dir / filename
    upload.save(destination)
    return destination


def build_playback_sequence(result: dict[str, Any]) -> list[dict[str, Any]]:
    playback = result.get("playback", {})
    if not isinstance(playback, dict):
        return []

    sequence: list[dict[str, Any]] = []
    tts_payload = playback.get("tts")
    if isinstance(tts_payload, dict) and tts_payload.get("url"):
        sequence.append(
            {
                "kind": "tts",
                "url": str(tts_payload["url"]),
                "label": str(tts_payload.get("spoken_text") or tts_payload.get("text") or "Assistant reply"),
            }
        )

    media_payload = playback.get("media_after_tts")
    if isinstance(media_payload, dict) and media_payload.get("stream_url"):
        sequence.append(
            {
                "kind": "media",
                "url": str(media_payload["stream_url"]),
                "label": str(media_payload.get("title") or "Media stream"),
            }
        )

    return sequence


def run_browser_turn(
    *,
    text_input: str | None = None,
    audio_upload: FileStorage | None = None,
    user_id: str | None = None,
    nfc_tag_id: str | None = None,
    device_id: str | None = None,
    session_state: dict[str, Any] | None = None,
    public_base_url: str | None = None,
) -> dict[str, Any]:
    resolved_text = str(text_input or "").strip()
    transcription_payload: dict[str, Any] | None = None
    upload_payload: dict[str, Any] | None = None

    if audio_upload is not None:
        saved_path = save_browser_audio_upload(audio_upload)
        transcription = transcribe_audio_file(saved_path)
        resolved_text = transcription.text.strip()
        transcription_payload = {
            "text": resolved_text,
            "language": transcription.language,
            "file_path": str(saved_path),
        }
        upload_payload = {
            "filename": saved_path.name,
            "content_type": audio_upload.content_type or "",
            "size_bytes": saved_path.stat().st_size,
        }

    if not resolved_text:
        raise ValueError("Missing text input or empty audio transcript")

    request_payload: dict[str, Any] = {
        "user_id": user_id or "",
        "nfc_tag_id": nfc_tag_id or "",
        "device_id": device_id or DEFAULT_BROWSER_DEVICE_ID,
        "public_base_url": public_base_url or "",
        "text_input": resolved_text,
        "stt_text": resolved_text,
    }
    if isinstance(session_state, dict):
        request_payload["session_state"] = dict(session_state)

    result = dict(run_assistant_turn(request_payload))
    result["input"] = {
        "mode": "audio" if audio_upload is not None else "text",
        "text": resolved_text,
    }
    if transcription_payload is not None:
        result["transcription"] = transcription_payload
    if upload_payload is not None:
        result["uploaded_audio"] = upload_payload
    result["playback_sequence"] = build_playback_sequence(result)
    return result

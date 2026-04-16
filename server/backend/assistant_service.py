from __future__ import annotations

import json
import logging
from typing import Any

from assistant_core.runtime import run_pipeline
from asset_registry import asset_registry
from database_api import get_user_by_nfc_tag
from device_session_store import device_session_store
from logging_utils import log_kv
from session_control import AudioSessionDirective, DeviceAudioSessionState, build_audio_session_state_message
from tts_service import tts_service


ACTIONABLE_COMMAND_TYPES = {
    "audio_stream",
    "video_stream",
    "alarm",
    "timer",
}


logger = logging.getLogger(__name__)


def resolve_session_key(
    *,
    nfc_tag_id: str | None,
    user_id: str | None,
    device_id: str | None,
) -> str | None:
    if nfc_tag_id:
        return f"nfc:{nfc_tag_id}"
    if user_id:
        return f"user:{user_id}"
    if device_id:
        return f"device:{device_id}"
    return None


def clear_assistant_session(
    *,
    nfc_tag_id: str | None,
    user_id: str | None,
    device_id: str | None,
) -> str | None:
    session_key = resolve_session_key(
        nfc_tag_id=nfc_tag_id,
        user_id=user_id,
        device_id=device_id,
    )
    device_session_store.clear(session_key)
    return session_key


def _normalize_actionable_command(command: dict[str, Any]) -> dict[str, Any] | None:
    command_type = str(command.get("type", "") or "")
    if command_type not in ACTIONABLE_COMMAND_TYPES:
        return None
    return dict(command)


def _prepare_media_command(
    command: dict[str, Any],
    *,
    public_base_url: str | None,
) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
    source_url = str(
        command.get("proxy_url")
        or command.get("stream_url")
        or command.get("upstream_stream_url")
        or ""
    ).strip()
    if not source_url:
        return None, None

    record = asset_registry.register_media_source(
        source_url,
        metadata={
            "title": command.get("stream_name") or command.get("title") or "Media stream",
            "source": command.get("source") or "unknown",
            "content_type_hint": command.get("content_type_hint"),
        },
    )
    transcoded_url = asset_registry.build_media_url(record.asset_id, base_url=public_base_url)
    playback = {
        "asset_id": record.asset_id,
        "stream_url": transcoded_url,
        "source_url": source_url,
        "title": record.metadata.get("title") or "Media stream",
        "source": record.metadata.get("source") or "unknown",
        "content_type": "audio/wav",
    }
    return {**command, "transcoded_stream_url": transcoded_url}, playback


def run_assistant_turn(payload: dict[str, Any]) -> dict[str, Any]:
    request_payload = dict(payload or {})
    text_input = str(request_payload.get("text_input") or request_payload.get("stt_text") or "").strip()
    if not text_input:
        raise ValueError("Missing text_input or stt_text")
    capture_token = str(request_payload.get("capture_token") or "").strip() or None
    public_base_url = str(request_payload.get("public_base_url") or "").strip() or None

    nfc_tag_id = str(request_payload.get("nfc_tag_id") or "").strip() or None
    user_id = str(request_payload.get("user_id") or "").strip() or None
    device_id = str(request_payload.get("device_id") or request_payload.get("ws_host") or "").strip() or None

    log_kv(
        logger,
        logging.INFO,
        "assistant_turn_started",
        device_id=device_id,
        user_id=user_id,
        nfc_tag_id=nfc_tag_id,
        capture_token=capture_token,
        public_base_url=public_base_url,
        text_input=text_input,
    )

    if nfc_tag_id and not user_id:
        user_profile = get_user_by_nfc_tag(nfc_tag_id)
        if user_profile and user_profile.get("user_id"):
            user_id = str(user_profile["user_id"])
            request_payload["user_id"] = user_id

    session_key = resolve_session_key(
        nfc_tag_id=nfc_tag_id,
        user_id=user_id,
        device_id=device_id,
    )
    if "session_state" not in request_payload or not isinstance(request_payload.get("session_state"), dict):
        cached_session_state = device_session_store.get(session_key)
        if cached_session_state:
            request_payload["session_state"] = cached_session_state

    request_payload["text_input"] = text_input
    final_output = run_pipeline(request_payload)

    session_state = final_output.get("session_state")
    if isinstance(session_state, dict):
        device_session_store.set(session_key, session_state)

    playback: dict[str, Any] | None = None
    playback_error: str | None = None
    tts_text = str(final_output.get("tts_text") or "").strip()
    if tts_text:
        try:
            speech = tts_service.synthesize(tts_text)
            speech_record = asset_registry.register_tts_file(
                speech.file_path,
                metadata={
                    "text": speech.text,
                    "spoken_text": speech.spoken_text,
                    "voice_name": speech.voice_name,
                    "duration_seconds": round(speech.duration_seconds, 3),
                    "sample_rate": speech.sample_rate,
                    "channels": speech.channels,
                },
            )
            playback = {
                "tts": {
                    "asset_id": speech_record.asset_id,
                    "text": speech.text,
                    "spoken_text": speech.spoken_text,
                    "voice_name": speech.voice_name,
                    "duration_seconds": round(speech.duration_seconds, 3),
                    "content_type": "audio/wav",
                    "url": asset_registry.build_tts_url(speech_record.asset_id, base_url=public_base_url),
                }
            }
            log_kv(
                logger,
                logging.INFO,
                "assistant_tts_ready",
                capture_token=capture_token,
                asset_id=speech_record.asset_id,
                tts_url=playback["tts"]["url"],
                spoken_text=speech.spoken_text,
            )
        except Exception as exc:
            playback_error = str(exc)
            logger.exception("assistant_tts_failed")

    actionable_commands: list[dict[str, Any]] = []
    media_playback: dict[str, Any] | None = None
    for command in final_output.get("commands", []):
        normalized = _normalize_actionable_command(command)
        if normalized is None:
            continue

        if normalized.get("type") in {"audio_stream", "video_stream"}:
            normalized_media_command, playback_info = _prepare_media_command(
                normalized,
                public_base_url=public_base_url,
            )
            if normalized_media_command is None or playback_info is None:
                continue
            normalized = normalized_media_command
            media_playback = playback_info
            log_kv(
                logger,
                logging.INFO,
                "assistant_media_ready",
                capture_token=capture_token,
                asset_id=playback_info.get("asset_id"),
                media_url=playback_info.get("stream_url"),
                source_url=playback_info.get("source_url"),
                title=playback_info.get("title"),
            )

        actionable_commands.append(normalized)

    if playback is None and media_playback is not None:
        playback = {}
    if playback is not None and media_playback is not None:
        playback["media_after_tts"] = media_playback

    esp_messages: list[dict[str, Any]] = []
    if playback:
        esp_messages.append(
            json.loads(
                build_audio_session_state_message(
                    AudioSessionDirective(
                        state=DeviceAudioSessionState.SPEAKING,
                        reason="assistant_response_ready",
                        stop_capture=True,
                        capture_token=capture_token,
                    )
                )
            )
        )
        playback_message = {
            "type": "assistant_playback",
            "tts_url": playback.get("tts", {}).get("url"),
            "tts_text": tts_text,
            "media_url": playback.get("media_after_tts", {}).get("stream_url"),
            "media_title": playback.get("media_after_tts", {}).get("title"),
            "final_state": DeviceAudioSessionState.STREAMING.value,
        }
        if capture_token:
            playback_message["capture_token"] = capture_token
        esp_messages.append(playback_message)

    for command in actionable_commands:
        if command.get("type") in {"alarm", "timer"}:
            esp_messages.append({"type": "device_command", "command": command})

    enriched_output = dict(final_output)
    if playback:
        enriched_output["playback"] = playback
    if actionable_commands:
        enriched_output["commands_for_device"] = actionable_commands
    if esp_messages:
        enriched_output["esp_messages"] = esp_messages
    if playback_error:
        enriched_output["playback_error"] = playback_error

    log_kv(
        logger,
        logging.INFO,
        "assistant_turn_completed",
        capture_token=capture_token,
        assistant_status=final_output.get("status"),
        route_group=((final_output.get("route") or {}) if isinstance(final_output.get("route"), dict) else {}).get("group"),
        has_tts=bool(playback and isinstance(playback.get("tts"), dict) and playback.get("tts", {}).get("url")),
        has_media=bool(playback and isinstance(playback.get("media_after_tts"), dict) and playback.get("media_after_tts", {}).get("stream_url")),
        playback_error=playback_error,
        esp_message_count=len(esp_messages),
    )
    return enriched_output

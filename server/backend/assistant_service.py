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


def _resolve_media_history_stream_url(
    command: dict[str, Any],
    *,
    public_base_url: str | None,
) -> str | None:
    proxy_path = str(command.get("proxy_path") or "").strip()
    if proxy_path:
        normalized_proxy_path = proxy_path if proxy_path.startswith("/") else f"/{proxy_path}"
        if public_base_url:
            return f"{public_base_url.rstrip('/')}{normalized_proxy_path}"

        proxy_url = str(command.get("proxy_url") or "").strip()
        if proxy_url:
            return proxy_url

    for field_name in ("proxy_url", "stream_url", "upstream_stream_url"):
        value = str(command.get(field_name) or "").strip()
        if value:
            return value

    return None


def _save_media_history(
    *,
    nfc_tag_id: str | None,
    stream_url: str | None,
    title: str | None,
    source: str | None,
    webpage_url: str | None = None,
    thumbnail_url: str | None = None,
) -> None:
    if not nfc_tag_id or not stream_url:
        return
    try:
        from assistant_tools.common import backend_json

        payload: dict[str, Any] = {
            "public_stream_url": stream_url,
            "title": title,
            "source": source,
        }
        if webpage_url:
            payload["webpage_url"] = webpage_url
        if thumbnail_url:
            payload["thumbnail_url"] = thumbnail_url

        backend_json(
            "POST",
            f"/api/users/{nfc_tag_id}/media-history",
            json_payload=payload,
        )
    except Exception:
        logger.debug("media_history_log_failed | url=%s", stream_url, exc_info=True)


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


def _load_cached_session_state(
    *,
    nfc_tag_id: str | None,
    user_id: str | None,
    device_id: str | None,
) -> dict[str, Any] | None:
    session_keys: list[str] = []
    primary_key = resolve_session_key(
        nfc_tag_id=nfc_tag_id,
        user_id=user_id,
        device_id=device_id,
    )
    if primary_key:
        session_keys.append(primary_key)

    device_key = resolve_session_key(
        nfc_tag_id=None,
        user_id=None,
        device_id=device_id,
    )
    if device_key and device_key not in session_keys:
        session_keys.append(device_key)

    for session_key in session_keys:
        cached_session_state = device_session_store.get(session_key)
        if isinstance(cached_session_state, dict):
            return cached_session_state
    return None


def _recover_nfc_tag_id_from_session_state(session_state: dict[str, Any] | None) -> str | None:
    if not isinstance(session_state, dict):
        return None

    profile_cache = session_state.get("profile_cache")
    if not isinstance(profile_cache, dict):
        return None

    return str(profile_cache.get("nfc_tag_id") or "").strip() or None


def _store_session_state_aliases(
    *,
    session_state: dict[str, Any],
    nfc_tag_id: str | None,
    user_id: str | None,
    device_id: str | None,
) -> None:
    session_keys: list[str] = []
    primary_key = resolve_session_key(
        nfc_tag_id=nfc_tag_id,
        user_id=user_id,
        device_id=device_id,
    )
    if primary_key:
        session_keys.append(primary_key)

    device_key = resolve_session_key(
        nfc_tag_id=None,
        user_id=None,
        device_id=device_id,
    )
    if device_key and device_key not in session_keys:
        session_keys.append(device_key)

    for session_key in session_keys:
        device_session_store.set(session_key, session_state)


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
    upstream_source_url = str(command.get("upstream_stream_url") or "").strip()
    proxy_source_url = str(command.get("proxy_url") or command.get("stream_url") or "").strip()
    source_url = upstream_source_url or proxy_source_url
    if not source_url:
        return None, None

    record = asset_registry.register_media_source(
        source_url,
        metadata={
            "title": command.get("stream_name") or command.get("title") or "Media stream",
            "source": command.get("source") or "unknown",
            "content_type_hint": command.get("content_type_hint"),
            "transcode_source_type": "upstream" if upstream_source_url else "proxy",
            "proxy_source_url": proxy_source_url or None,
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
        "transcode_source_url": source_url,
        "transcode_source_type": record.metadata.get("transcode_source_type") or "proxy",
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

    if "session_state" not in request_payload or not isinstance(request_payload.get("session_state"), dict):
        cached_session_state = _load_cached_session_state(
            nfc_tag_id=nfc_tag_id,
            user_id=user_id,
            device_id=device_id,
        )
        if cached_session_state:
            request_payload["session_state"] = cached_session_state

    if not nfc_tag_id:
        recovered_nfc_tag_id = _recover_nfc_tag_id_from_session_state(request_payload.get("session_state"))
        if recovered_nfc_tag_id:
            nfc_tag_id = recovered_nfc_tag_id
            request_payload["nfc_tag_id"] = nfc_tag_id
            log_kv(
                logger,
                logging.INFO,
                "assistant_nfc_restored_from_session_cache",
                device_id=device_id,
                nfc_tag_id=nfc_tag_id,
            )

    if nfc_tag_id:
        user_profile = get_user_by_nfc_tag(nfc_tag_id)
        if user_profile and user_profile.get("user_id"):
            user_id = str(user_profile["user_id"])
            request_payload["user_id"] = user_id
            log_kv(
                logger,
                logging.INFO,
                "assistant_user_resolved_from_nfc",
                nfc_tag_id=nfc_tag_id,
                resolved_user_id=user_id,
            )

    request_payload["text_input"] = text_input
    final_output = run_pipeline(request_payload)

    session_state = final_output.get("session_state")
    if isinstance(session_state, dict):
        _store_session_state_aliases(
            session_state=session_state,
            nfc_tag_id=nfc_tag_id,
            user_id=user_id,
            device_id=device_id,
        )

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
                transcode_source_url=playback_info.get("transcode_source_url"),
                transcode_source_type=playback_info.get("transcode_source_type"),
                title=playback_info.get("title"),
            )

            history_stream_url = _resolve_media_history_stream_url(
                normalized,
                public_base_url=public_base_url,
            )
            _save_media_history(
                nfc_tag_id=nfc_tag_id,
                stream_url=history_stream_url,
                title=playback_info.get("title"),
                source=playback_info.get("source"),
                webpage_url=normalized.get("webpage_url"),
                thumbnail_url=normalized.get("thumbnail_url"),
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
        route_subtask=((final_output.get("route") or {}) if isinstance(final_output.get("route"), dict) else {}).get("subtask"),
        pending_kind=((final_output.get("dialog") or {}) if isinstance(final_output.get("dialog"), dict) else {}).get("pending_kind"),
        tool_output_count=len(final_output.get("tool_outputs", [])) if isinstance(final_output.get("tool_outputs"), list) else 0,
        tools_called=[
            item.get("tool")
            for item in final_output.get("tool_outputs", [])
            if isinstance(item, dict) and item.get("tool")
        ]
        if isinstance(final_output.get("tool_outputs"), list)
        else [],
        command_types=[
            item.get("type")
            for item in final_output.get("commands", [])
            if isinstance(item, dict) and item.get("type")
        ]
        if isinstance(final_output.get("commands"), list)
        else [],
        has_tts=bool(playback and isinstance(playback.get("tts"), dict) and playback.get("tts", {}).get("url")),
        has_media=bool(playback and isinstance(playback.get("media_after_tts"), dict) and playback.get("media_after_tts", {}).get("stream_url")),
        playback_error=playback_error,
        esp_message_count=len(esp_messages),
    )
    return enriched_output

from __future__ import annotations

import logging
from pathlib import Path
import os
import subprocess
import time
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
import requests

from assistant_service import clear_assistant_session, resolve_session_key, run_assistant_turn
from asset_registry import asset_registry
from config import (
    BACKEND_API_URL,
    FFMPEG_BIN,
    LOG_FILE_PATH,
    LOG_LEVEL,
    MEDIA_TRANSCODE_CHANNELS,
    MEDIA_TRANSCODE_SAMPLE_RATE,
    VOICE_BACKEND_PORT,
    VOICE_BACKEND_PUBLIC_BASE_URL,
)
from dev_console import DEFAULT_BROWSER_DEVICE_ID, parse_json_object, run_browser_turn
from device_session_store import device_session_store
from logging_utils import configure_logging, is_loopback_base_url, log_kv
from tts_service import tts_service
from youtube_stream_tool import resolve_youtube_stream

try:
    from .audio_receiver import (
        DEFAULT_NO_SPEECH_TIMEOUT_SECONDS,
        DEFAULT_OUTPUT_DIR,
        CaptureRequest,
        capture_manager,
    )
    from .session_control import DeviceAudioSessionState, parse_device_audio_session_state
except ImportError:
    from audio_receiver import (
        DEFAULT_NO_SPEECH_TIMEOUT_SECONDS,
        DEFAULT_OUTPUT_DIR,
        CaptureRequest,
        capture_manager,
    )
    from session_control import DeviceAudioSessionState, parse_device_audio_session_state


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TEST_NFC_TAG_ID = os.getenv("STEP3_TEST_NFC_TAG_ID", "15:CF:D0:06")
DEFAULT_TEST_USER_ID = os.getenv("STEP3_TEST_USER_ID", "server_test_user")

configure_logging(level=LOG_LEVEL, log_file=LOG_FILE_PATH)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.json.ensure_ascii = False

if is_loopback_base_url(VOICE_BACKEND_PUBLIC_BASE_URL):
    log_kv(
        logger,
        logging.WARNING,
        "voice_backend_public_base_url_loopback",
        configured_base_url=VOICE_BACKEND_PUBLIC_BASE_URL,
        guidance="ESP playback needs a LAN-reachable base URL; request host override will be used for live device sessions.",
    )


def normalize_path(value: str | None) -> str:
    if not value:
        return "/"
    return value if value.startswith("/") else f"/{value}"


def parse_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value '{value}'")


def _transcode_media_stream(source_url: str):
    command = [
        FFMPEG_BIN,
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        source_url,
        "-vn",
        "-ac",
        str(MEDIA_TRANSCODE_CHANNELS),
        "-ar",
        str(MEDIA_TRANSCODE_SAMPLE_RATE),
        "-sample_fmt",
        "s16",
        "-f",
        "wav",
        "pipe:1",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def generate():
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    return generate


def _request_payload() -> dict[str, Any]:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return payload if isinstance(payload, dict) else {}
    return request.form.to_dict(flat=True)


def resolve_request_public_base_url(*, fallback: str | None = None) -> str:
    request_base_url = str(getattr(request, "url_root", "") or "").strip()
    if request_base_url:
        return request_base_url.rstrip("/")
    return str(fallback or VOICE_BACKEND_PUBLIC_BASE_URL).rstrip("/")


def _build_debug_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    session_state = parse_json_object(payload.get("session_state"), field_name="session_state")
    return {
        "user_id": str(payload.get("user_id") or "").strip() or None,
        "nfc_tag_id": str(payload.get("nfc_tag_id") or "").strip() or None,
        "device_id": str(payload.get("device_id") or "").strip() or DEFAULT_BROWSER_DEVICE_ID,
        "session_state": session_state,
    }


@app.route("/health", methods=["GET"])
def health_check():
    return (
        jsonify(
            {
                "status": "ok",
                "service": "voice-ai-backend",
                "database_api_url": BACKEND_API_URL,
                "public_base_url": VOICE_BACKEND_PUBLIC_BASE_URL,
            }
        ),
        200,
    )


@app.route("/dev/assistant", methods=["GET"])
def assistant_lab():
    return render_template(
        "assistant_lab.html",
        public_base_url=VOICE_BACKEND_PUBLIC_BASE_URL.rstrip("/"),
        default_user_id=DEFAULT_TEST_USER_ID,
        default_nfc_tag_id=DEFAULT_TEST_NFC_TAG_ID,
        default_device_id=DEFAULT_BROWSER_DEVICE_ID,
        default_ws_host="",
        default_ws_port=81,
        default_ws_path="/",
    )


@app.route("/api/assets/tts/<asset_id>.wav", methods=["GET"])
def tts_asset(asset_id: str):
    record = asset_registry.get(asset_id)
    if record is None or record.kind != "tts" or not record.file_path:
        return jsonify({"error": "TTS asset not found"}), 404

    file_path = Path(record.file_path)
    if not file_path.exists():
        return jsonify({"error": "TTS asset file missing"}), 404
    return send_file(file_path, mimetype="audio/wav", as_attachment=False, download_name=f"{asset_id}.wav")


@app.route("/api/assets/media/<asset_id>.wav", methods=["GET"])
def media_asset(asset_id: str):
    record = asset_registry.get(asset_id)
    if record is None or record.kind != "media" or not record.source_url:
        return jsonify({"error": "Media asset not found"}), 404

    try:
        generator = _transcode_media_stream(record.source_url)
        return Response(
            stream_with_context(generator()),
            mimetype="audio/wav",
            headers={"X-Transcoded-By": "ffmpeg"},
        )
    except Exception as exc:
        return jsonify({"error": f"Failed to transcode media asset: {exc}"}), 502


@app.route("/api/media/youtube/stream", methods=["GET"])
def api_youtube_stream_proxy():
    query = str(request.args.get("query", "")).strip() or None
    video_id = str(request.args.get("video_id", "")).strip() or None
    url = str(request.args.get("url", "")).strip() or None
    mode = str(request.args.get("mode", "audio")).strip() or "audio"

    try:
        stream_info = resolve_youtube_stream(
            query=query,
            video_id=video_id,
            url=url,
            mode=mode,
        )
    except Exception as exc:
        return jsonify({"error": f"Cannot resolve YouTube stream: {exc}"}), 400

    upstream_headers: dict[str, str] = {}
    range_header = request.headers.get("Range")
    if range_header:
        upstream_headers["Range"] = range_header

    try:
        upstream = requests.get(
            stream_info["direct_stream_url"],
            headers=upstream_headers,
            stream=True,
            timeout=(10, 60),
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"Cannot connect to upstream YouTube media: {exc}"}), 502

    passthrough_headers = {}
    for header_name in (
        "Accept-Ranges",
        "Cache-Control",
        "Content-Length",
        "Content-Range",
        "Content-Type",
        "ETag",
        "Last-Modified",
    ):
        if upstream.headers.get(header_name):
            passthrough_headers[header_name] = upstream.headers[header_name]

    if "Content-Type" not in passthrough_headers and stream_info.get("content_type_hint"):
        passthrough_headers["Content-Type"] = str(stream_info["content_type_hint"])
    passthrough_headers["X-Proxy-Source"] = "youtube_yt_dlp"
    if stream_info.get("video_id"):
        passthrough_headers["X-YouTube-Video-Id"] = str(stream_info["video_id"])

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(
        stream_with_context(generate()),
        status=upstream.status_code,
        headers=passthrough_headers,
    )


@app.route("/api/process-command", methods=["POST"])
def process_command() -> tuple[dict[str, Any], int] | tuple[Response, int]:
    payload = request.get_json(silent=True) or {}
    payload["public_base_url"] = resolve_request_public_base_url(
        fallback=str(payload.get("public_base_url") or "").strip() or None,
    )
    try:
        result = run_assistant_turn(payload)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        return {"error": f"Assistant turn failed: {exc}"}, 500

    return jsonify(result), 200


@app.route("/api/test", methods=["POST"])
def api_test() -> tuple[dict[str, Any], int] | tuple[Response, int]:
    payload = request.get_json(silent=True) or {}
    test_payload = {
        "user_id": str(payload.get("user_id") or DEFAULT_TEST_USER_ID).strip() or DEFAULT_TEST_USER_ID,
        "nfc_tag_id": str(payload.get("nfc_tag_id") or DEFAULT_TEST_NFC_TAG_ID).strip() or DEFAULT_TEST_NFC_TAG_ID,
        "device_id": str(payload.get("device_id") or DEFAULT_BROWSER_DEVICE_ID).strip() or DEFAULT_BROWSER_DEVICE_ID,
        "public_base_url": resolve_request_public_base_url(
            fallback=str(payload.get("public_base_url") or "").strip() or None,
        ),
        "text_input": str(payload.get("text_input") or "kể cho mình một câu chuyện vui").strip()
        or "kể cho mình một câu chuyện vui",
    }
    session_state = payload.get("session_state")
    if isinstance(session_state, dict):
        test_payload["session_state"] = session_state

    try:
        result = run_assistant_turn(test_payload)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        return {"error": f"Assistant test turn failed: {exc}"}, 500

    return {"input": test_payload["text_input"], "output": result}, 200


@app.route("/api/dev/assistant-turn", methods=["POST"])
def browser_assistant_turn() -> tuple[dict[str, Any], int] | tuple[Response, int]:
    payload = _request_payload()
    audio_upload = request.files.get("audio")

    try:
        debug_payload = _build_debug_session_payload(payload)
        result = run_browser_turn(
            text_input=str(payload.get("text_input") or "").strip() or None,
            audio_upload=audio_upload if audio_upload and audio_upload.filename else None,
            user_id=debug_payload["user_id"],
            nfc_tag_id=debug_payload["nfc_tag_id"],
            device_id=debug_payload["device_id"],
            session_state=debug_payload["session_state"],
            public_base_url=resolve_request_public_base_url(
                fallback=str(payload.get("public_base_url") or "").strip() or None,
            ),
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        return {"error": f"Browser assistant turn failed: {exc}"}, 500

    result["session_key"] = resolve_session_key(
        nfc_tag_id=debug_payload["nfc_tag_id"],
        user_id=debug_payload["user_id"],
        device_id=debug_payload["device_id"],
    )
    return jsonify(result), 200


@app.route("/api/dev/session/reset", methods=["POST"])
def reset_debug_session() -> tuple[dict[str, Any], int]:
    payload = _request_payload()
    debug_payload = _build_debug_session_payload(payload)
    session_key = clear_assistant_session(
        nfc_tag_id=debug_payload["nfc_tag_id"],
        user_id=debug_payload["user_id"],
        device_id=debug_payload["device_id"],
    )
    return {
        "status": "cleared",
        "session_key": session_key,
        "active_sessions": device_session_store.dump(),
    }, 200


@app.route("/api/dev/sessions", methods=["GET"])
def list_debug_sessions() -> tuple[dict[str, Any], int]:
    return {
        "status": "ok",
        "sessions": device_session_store.dump(),
    }, 200


@app.route("/api/audio/start", methods=["POST"])
def start_audio_capture():
    payload = request.get_json(silent=True) or {}
    ws_host = str(payload.get("ws_host") or "").strip()
    if not ws_host:
        return jsonify({"error": "ws_host is required"}), 400

    try:
        first_utterance_state = parse_device_audio_session_state(
            payload.get("first_utterance_state"),
            default=DeviceAudioSessionState.THINKING,
        )
        enable_first_utterance_vad = parse_optional_bool(payload.get("enable_first_utterance_vad"))
        stop_after_first_utterance = parse_optional_bool(payload.get("stop_after_first_utterance"))
        no_speech_timeout_value = payload.get("no_speech_timeout_seconds")
        no_speech_timeout_seconds = (
            DEFAULT_NO_SPEECH_TIMEOUT_SECONDS
            if no_speech_timeout_value is None or str(no_speech_timeout_value).strip() == ""
            else float(no_speech_timeout_value)
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    output_dir_value = str(payload.get("output_dir") or "").strip()
    output_dir = Path(output_dir_value) if output_dir_value else DEFAULT_OUTPUT_DIR
    public_base_url = resolve_request_public_base_url(
        fallback=str(payload.get("public_base_url") or "").strip() or None,
    )

    capture_request = CaptureRequest(
        ws_host=ws_host,
        ws_port=int(payload.get("ws_port") or 81),
        ws_path=normalize_path(payload.get("ws_path")),
        prefix=str(payload.get("prefix") or "capture").strip() or "capture",
        sample_rate=int(payload.get("sample_rate") or 16000),
        output_dir=output_dir,
        segment_seconds=payload.get("segment_seconds"),
        timeout_seconds=float(payload.get("timeout_seconds") or 5.0),
        retry_seconds=float(payload.get("retry_seconds") or 1.0),
        enable_first_utterance_vad=True if enable_first_utterance_vad is None else enable_first_utterance_vad,
        first_utterance_state=first_utterance_state,
        stop_after_first_utterance=stop_after_first_utterance,
        no_speech_timeout_seconds=no_speech_timeout_seconds,
        public_base_url=public_base_url,
        nfc_tag_id=str(payload.get("nfc_tag_id") or "").strip() or None,
        user_id=str(payload.get("user_id") or "").strip() or None,
        device_id=str(payload.get("device_id") or ws_host).strip() or None,
        capture_token=str(payload.get("capture_token") or "").strip() or None,
    )

    log_kv(
        logger,
        logging.INFO,
        "audio_capture_start_requested",
        ws_host=ws_host,
        ws_port=capture_request.ws_port,
        first_utterance_state=capture_request.first_utterance_state.value,
        no_speech_timeout_seconds=no_speech_timeout_seconds,
        public_base_url=public_base_url,
        configured_public_base_url=VOICE_BACKEND_PUBLIC_BASE_URL,
        capture_token=capture_request.capture_token,
    )
    status = capture_manager.start(capture_request)
    return jsonify({"status": "started", "capture": status, "public_base_url": public_base_url}), 202


@app.route("/api/audio/status", methods=["GET"])
def audio_status():
    return jsonify(capture_manager.status()), 200


@app.route("/api/audio/stop", methods=["POST"])
def stop_audio_capture():
    return jsonify(capture_manager.stop()), 200


def main() -> None:
    prewarm_started_at = time.monotonic()
    try:
        tts_service.prewarm()
        log_kv(
            logger,
            logging.INFO,
            "tts_prewarm_completed",
            voice_name=tts_service.voice_name,
            elapsed_ms=round((time.monotonic() - prewarm_started_at) * 1000),
        )
    except Exception as exc:
        logger.exception("tts_prewarm_failed")
        log_kv(
            logger,
            logging.WARNING,
            "tts_prewarm_failed",
            error=str(exc),
            elapsed_ms=round((time.monotonic() - prewarm_started_at) * 1000),
        )

    log_kv(
        logger,
        logging.INFO,
        "voice_backend_starting",
        port=VOICE_BACKEND_PORT,
        configured_public_base_url=VOICE_BACKEND_PUBLIC_BASE_URL,
        log_file=LOG_FILE_PATH,
    )
    app.run(
        host="0.0.0.0",
        port=VOICE_BACKEND_PORT,
        debug=False,
    )


if __name__ == "__main__":
    main()

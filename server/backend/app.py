from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request

try:
    from .audio_receiver import DEFAULT_OUTPUT_DIR, CaptureRequest, capture_manager
except ImportError:
    from audio_receiver import DEFAULT_OUTPUT_DIR, CaptureRequest, capture_manager


DEFAULT_SERVER_PORT = 8387
BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.json.ensure_ascii = False


def normalize_path(value: str | None) -> str:
    if not value:
        return "/"
    return value if value.startswith("/") else f"/{value}"


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "service": "audio-backend"}), 200


@app.route("/api/audio/start", methods=["POST"])
def start_audio_capture():
    payload = request.get_json(silent=True) or {}
    ws_host = str(payload.get("ws_host") or "").strip()
    if not ws_host:
        return jsonify({"error": "ws_host is required"}), 400

    output_dir_value = str(payload.get("output_dir") or "").strip()
    output_dir = Path(output_dir_value) if output_dir_value else DEFAULT_OUTPUT_DIR

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
    )

    status = capture_manager.start(capture_request)
    return jsonify({"status": "started", "capture": status}), 202


@app.route("/api/audio/status", methods=["GET"])
def audio_status():
    return jsonify(capture_manager.status()), 200


@app.route("/api/audio/stop", methods=["POST"])
def stop_audio_capture():
    return jsonify(capture_manager.stop()), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=DEFAULT_SERVER_PORT, debug=False)

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from config import VOICE_BACKEND_PORT


DEFAULT_BASE_URL = os.getenv("VOICE_BACKEND_TEST_BASE_URL", f"http://127.0.0.1:{VOICE_BACKEND_PORT}")
DEFAULT_USER_ID = os.getenv("CLI_USER_ID", "server_cli_user")
DEFAULT_NFC_TAG_ID = os.getenv("STEP3_TEST_NFC_TAG_ID", "15:CF:D0:06")
DEFAULT_DEVICE_ID = os.getenv("CLI_DEVICE_ID", "server-cli")
CLI_STATE_FILE = Path(
    os.getenv(
        "SERVER_ASSISTANT_CLI_STATE_FILE",
        Path(__file__).resolve().parent / ".server_assistant_cli_state.json",
    )
)

QUIT_COMMANDS = {"/exit", "/quit", "/q"}
RESET_COMMANDS = {"/reset", "/clear"}
FORGET_COMMANDS = {"/forget", "/new-chat", "/forget-context"}
HISTORY_COMMANDS = {"/history"}

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_BLUE = "\033[34m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"
ANSI_CYAN = "\033[36m"


@dataclass
class CliSession:
    user_id: str
    nfc_tag_id: str
    device_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    session_state: dict[str, Any] = field(default_factory=dict)


def _color(text: str, *styles: str) -> str:
    if not styles:
        return text
    return f"{''.join(styles)}{text}{ANSI_RESET}"


def _short_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _cache_key(session: CliSession) -> str:
    return f"{session.user_id}::{session.nfc_tag_id}::{session.device_id}"


def _read_cli_cache() -> dict[str, Any]:
    try:
        with CLI_STATE_FILE.open("r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_cli_cache(payload: dict[str, Any]) -> None:
    try:
        CLI_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CLI_STATE_FILE.open("w", encoding="utf-8") as cache_file:
            json.dump(payload, cache_file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_session_cache(session: CliSession) -> None:
    entry = _read_cli_cache().get(_cache_key(session), {})
    if not isinstance(entry, dict):
        return

    session_state = entry.get("session_state")
    messages = entry.get("messages")
    if isinstance(session_state, dict):
        session.session_state = dict(session_state)
    if isinstance(messages, list):
        normalized: list[dict[str, str]] = []
        for item in messages:
            if isinstance(item, dict):
                normalized.append(
                    {
                        "role": str(item.get("role", "assistant")),
                        "content": str(item.get("content", "")),
                    }
                )
        session.messages = normalized


def persist_session_cache(session: CliSession) -> None:
    payload = _read_cli_cache()
    payload[_cache_key(session)] = {
        "session_state": dict(session.session_state),
        "messages": list(session.messages),
    }
    _write_cli_cache(payload)


def clear_local_session(session: CliSession) -> None:
    session.messages.clear()
    session.session_state = {}
    persist_session_cache(session)


def update_local_session(session: CliSession, user_text: str, result: dict[str, Any]) -> None:
    cleaned_user_text = str(user_text or "").strip()
    if cleaned_user_text:
        session.messages.append({"role": "user", "content": cleaned_user_text})

    assistant_text = str(result.get("tts_text") or "").strip()
    if assistant_text:
        session.messages.append({"role": "assistant", "content": assistant_text})

    session.messages = session.messages[-24:]
    session_state = result.get("session_state")
    session.session_state = dict(session_state) if isinstance(session_state, dict) else {}
    persist_session_cache(session)


def print_session_history(session: CliSession) -> None:
    if not session.messages:
        print("Session history đang trống.")
        return

    print(_color("\n=== session_history ===", ANSI_BOLD, ANSI_BLUE))
    for index, message in enumerate(session.messages, start=1):
        print(
            f"{_color(str(index), ANSI_BOLD, ANSI_CYAN)}. "
            f"{message.get('role', 'unknown')}: {_short_text(message.get('content', ''), limit=260)}"
        )


def post_json(base_url: str, path: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    response = requests.post(
        f"{base_url.rstrip('/')}{path}",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def reset_remote_session(base_url: str, session: CliSession) -> dict[str, Any]:
    return post_json(
        base_url,
        "/api/dev/session/reset",
        {
            "user_id": session.user_id,
            "nfc_tag_id": session.nfc_tag_id,
            "device_id": session.device_id,
        },
        timeout=30,
    )


def build_text_turn_payload(session: CliSession, text_input: str) -> dict[str, Any]:
    return {
        "user_id": session.user_id,
        "nfc_tag_id": session.nfc_tag_id,
        "device_id": session.device_id,
        "text_input": text_input,
        "session_state": dict(session.session_state),
    }


def format_turn_summary(result: dict[str, Any]) -> str:
    route = result.get("route", {}) if isinstance(result.get("route"), dict) else {}
    dialog = result.get("dialog", {}) if isinstance(result.get("dialog"), dict) else {}
    playback = result.get("playback", {}) if isinstance(result.get("playback"), dict) else {}
    tts = playback.get("tts", {}) if isinstance(playback.get("tts"), dict) else {}
    media = playback.get("media_after_tts", {}) if isinstance(playback.get("media_after_tts"), dict) else {}

    lines = [
        _color(f"assistant: {_short_text(result.get('tts_text', ''), 400)}", ANSI_BOLD, ANSI_GREEN),
        f"status={result.get('status', 'unknown')} route={route.get('group', 'unknown')} subtask={route.get('subtask', 'unknown')}",
    ]

    pending_question = dialog.get("pending_question")
    if pending_question:
        lines.append(_color(f"pending: {_short_text(pending_question, 260)}", ANSI_YELLOW))

    tool_outputs = result.get("tool_outputs", [])
    if isinstance(tool_outputs, list) and tool_outputs:
        lines.append(f"tool_outputs={len(tool_outputs)} commands={len(result.get('commands', []))}")
        for item in tool_outputs[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"  - {item.get('tool')}: {item.get('status')} | {_short_text(item.get('message', ''), 120)}"
            )

    if tts.get("url"):
        lines.append(f"tts_url={tts.get('url')}")
    if media.get("stream_url"):
        lines.append(f"media_url={media.get('stream_url')}")

    commands_for_device = result.get("commands_for_device", [])
    if isinstance(commands_for_device, list) and commands_for_device:
        lines.append(f"commands_for_device={json.dumps(commands_for_device, ensure_ascii=False, indent=2)}")

    playback_error = result.get("playback_error")
    if playback_error:
        lines.append(_color(f"playback_error={playback_error}", ANSI_RED))

    return "\n".join(lines)

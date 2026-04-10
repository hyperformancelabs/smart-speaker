from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum


class DeviceAudioSessionState(str, Enum):
    WAIT_WAKEWORD = "wait_wakeword"
    STREAMING = "streaming"
    THINKING = "thinking"

    @classmethod
    def from_value(cls, value: object) -> "DeviceAudioSessionState":
        normalized = str(value or "").strip().lower()
        for member in cls:
            if normalized == member.value:
                return member
        allowed = ", ".join(member.value for member in cls)
        raise ValueError(f"invalid audio session state '{value}'. Expected one of: {allowed}")


def parse_device_audio_session_state(
    value: object,
    *,
    default: DeviceAudioSessionState = DeviceAudioSessionState.WAIT_WAKEWORD,
) -> DeviceAudioSessionState:
    if value is None:
        return default

    if isinstance(value, str) and not value.strip():
        return default

    return DeviceAudioSessionState.from_value(value)


def default_stop_after_first_utterance(state: DeviceAudioSessionState) -> bool:
    return state == DeviceAudioSessionState.WAIT_WAKEWORD


@dataclass(slots=True)
class AudioSessionDirective:
    state: DeviceAudioSessionState
    reason: str
    stop_capture: bool


def build_audio_session_state_message(directive: AudioSessionDirective) -> str:
    payload = {
        "type": "audio_session_state",
        "state": directive.state.value,
        "reason": directive.reason,
        "stop_capture": directive.stop_capture,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

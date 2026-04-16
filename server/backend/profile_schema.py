from __future__ import annotations

import copy
import json
from typing import Any


DEFAULT_PREFERENCES_TEMPLATE: dict[str, Any] = {
    "language": "vi-VN",
    "assistant_style": "friendly",
    "response_verbosity": "balanced",
    "favorite_music": {
        "genres": [],
        "artists": [],
        "songs": [],
    },
    "favorite_content_topics": [],
    "favorite_audio_sources": [],
    "daily_routine": {
        "wake_time": None,
        "sleep_time": None,
    },
    "quiet_hours": {
        "start": None,
        "end": None,
    },
    "location_context": {
        "home_city": None,
    },
    "device_settings": {
        "default_volume": None,
        "tts_speed": 1.0,
    },
    "personal_profile": {
        "age": None,
    },
    "likes": [],
    "dislikes": [],
}

DEFAULT_PREFERENCES_JSON = json.dumps(DEFAULT_PREFERENCES_TEMPLATE, ensure_ascii=True)
DEFAULT_PREFERENCES_JSON_SQL = DEFAULT_PREFERENCES_JSON.replace("'", "''")


def build_default_preferences() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_PREFERENCES_TEMPLATE)


def _merge_unique_list(base_values: list[Any], incoming_values: list[Any]) -> list[Any]:
    merged = list(base_values)
    for item in incoming_values:
        if item not in merged:
            merged.append(copy.deepcopy(item))
    return merged


def merge_preferences(base: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(incoming, dict):
        return merged

    for key, value in incoming.items():
        current_value = merged.get(key)
        if isinstance(current_value, dict) and isinstance(value, dict):
            merged[key] = merge_preferences(current_value, value)
        elif isinstance(current_value, list) and isinstance(value, list):
            merged[key] = _merge_unique_list(current_value, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def normalize_preferences(value: dict[str, Any] | None) -> dict[str, Any]:
    return merge_preferences(build_default_preferences(), value if isinstance(value, dict) else {})

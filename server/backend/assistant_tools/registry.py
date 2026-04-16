from __future__ import annotations

import inspect
from typing import Any

from assistant_tools.backend_tools import (
    add_list_item,
    cancel_timer,
    create_alarm,
    create_list,
    delete_list,
    delete_memory,
    delete_alarm,
    get_lists,
    get_memory,
    get_user_profile,
    list_alarms,
    list_items,
    list_timers,
    rename_list,
    remove_list_item,
    save_memory,
    start_timer,
    update_alarm,
    update_list_item,
    update_timer,
    update_user_profile,
)
from assistant_tools.information import calculator, fetch_content, web_search
from assistant_tools.media import play_audio, youtube_search, youtube_stream

TOOL_FUNCTIONS = {
    "play_audio": play_audio,
    "youtube_search": youtube_search,
    "youtube_stream": youtube_stream,
    "web_search": web_search,
    "fetch_content": fetch_content,
    "calculator": calculator,
    "create_alarm": create_alarm,
    "update_alarm": update_alarm,
    "delete_alarm": delete_alarm,
    "list_alarms": list_alarms,
    "start_timer": start_timer,
    "list_timers": list_timers,
    "update_timer": update_timer,
    "cancel_timer": cancel_timer,
    "create_list": create_list,
    "rename_list": rename_list,
    "delete_list": delete_list,
    "add_list_item": add_list_item,
    "update_list_item": update_list_item,
    "remove_list_item": remove_list_item,
    "get_lists": get_lists,
    "list_items": list_items,
    "get_user_profile": get_user_profile,
    "update_user_profile": update_user_profile,
    "save_memory": save_memory,
    "delete_memory": delete_memory,
    "get_memory": get_memory,
}


def _normalize_tool_parameters(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)

    if tool_name in {"play_audio", "youtube_search", "youtube_stream"}:
        if "query" not in normalized:
            for alias in ("title", "song", "track", "name", "keyword"):
                value = normalized.get(alias)
                if isinstance(value, str) and value.strip():
                    normalized["query"] = value.strip()
                    break

    if tool_name == "youtube_stream" and "mode" not in normalized:
        media_type = normalized.get("type") or normalized.get("media_type")
        if isinstance(media_type, str) and media_type.strip().lower() in {"audio", "video"}:
            normalized["mode"] = media_type.strip().lower()

    return normalized


def execute_tool(tool_name: str, parameters: dict[str, Any], nfc_tag_id: str = None) -> dict[str, Any]:
    """
    Execute a tool by name with parameters

    Args:
        tool_name: Name of tool to execute
        parameters: Tool parameters
        nfc_tag_id: User identifier (NFC tag)

    Returns:
        Tool result dict
    """
    if tool_name not in TOOL_FUNCTIONS:
        return {
            "status": "error",
            "message": f"Unknown tool: {tool_name}",
        }

    tool_func = TOOL_FUNCTIONS[tool_name]
    call_parameters = _normalize_tool_parameters(tool_name, parameters)

    signature = inspect.signature(tool_func)
    accepts_nfc_tag_id = "nfc_tag_id" in signature.parameters
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    if accepts_nfc_tag_id and nfc_tag_id and "nfc_tag_id" not in call_parameters:
        call_parameters["nfc_tag_id"] = nfc_tag_id

    if not accepts_var_kwargs:
        accepted_parameters = set(signature.parameters.keys())
        call_parameters = {
            key: value
            for key, value in call_parameters.items()
            if key in accepted_parameters
        }

    try:
        return tool_func(**call_parameters)
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Tool execution error: {str(exc)}",
        }

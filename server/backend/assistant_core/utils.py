from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from profile_schema import normalize_preferences
from config import MAX_CONTEXT_SUMMARY_CHARS


def _message_to_role_and_content(message: Any) -> tuple[str, str]:
    if isinstance(message, dict):
        role = str(message.get("role", "assistant"))
        content = message.get("content", "")
        return role, str(content if content is not None else "")

    role = str(getattr(message, "type", "assistant"))
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
            else:
                text_parts.append(str(item))
        content = " ".join(text_parts)

    return role, str(content if content is not None else "")


def format_user_profile(profile: dict[str, Any]) -> str:
    """Format user profile for prompts"""
    name = profile.get("name") or "Guest"
    traits = profile.get("traits", [])
    preferences = normalize_preferences(profile.get("preferences", {}))

    traits_str = ", ".join(traits) if traits else "chưa có thông tin"
    prefs_str = json.dumps(preferences, ensure_ascii=False, sort_keys=True)

    return f"Name: {name}\nTraits: {traits_str}\nPreferences JSON: {prefs_str}"


def build_response_preferences_text(profile: dict[str, Any]) -> str:
    preferences = normalize_preferences(profile.get("preferences", {}))
    language = preferences.get("language", "vi-VN")
    assistant_style = preferences.get("assistant_style", "friendly")
    response_verbosity = preferences.get("response_verbosity", "balanced")

    style_hints = {
        "friendly": "am ap, tu nhien, than thien",
        "cute": "dang yeu, mem mai, vui tuoi, nhe nhang",
        "playful": "vui ve, linh hoat, co chut tinh nghich",
        "calm": "binh tinh, nhe nha, on dinh",
        "professional": "ro rang, lich su, chuyen nghiep",
    }
    verbosity_hints = {
        "concise": "ngan gon, nhanh, it cau",
        "balanced": "ngan gon vua du, tu nhien",
        "detailed": "day du hon, giai thich ky hon khi can",
    }

    return (
        f"- preferred_output_language: {language}\n"
        f"- assistant_style: {assistant_style} ({style_hints.get(assistant_style, assistant_style)})\n"
        f"- response_verbosity: {response_verbosity} ({verbosity_hints.get(response_verbosity, response_verbosity)})\n"
        "- apply_these_preferences_to_every assistant_text unless the current user turn explicitly asks for a different language or style"
    )


def format_memory(memory_list: list[str]) -> str:
    """Format memory for prompts"""
    if not memory_list:
        return "Chưa có bộ nhớ"

    return "\n".join([f"- {memory}" for memory in memory_list[:10]])


def format_conversation_history(messages: list[Any], max_messages: int = 6) -> str:
    """
    Format conversation history for prompts

    Args:
        messages: List of {"role": "user|assistant", "content": "..."}
        max_messages: Max messages to include
    """
    if not messages:
        return "Bắt đầu cuộc trò chuyện mới"

    history = []
    for message in messages[-max_messages:]:
        raw_role, content = _message_to_role_and_content(message)
        role = "User" if raw_role in {"user", "human"} else "Assistant"
        history.append(f"{role}: {content}")

    return "\n".join(history)


def format_full_transcript(messages: list[Any]) -> str:
    """Format the full transcript of a task without top-K truncation."""
    if not messages:
        return "Chưa có lượt hội thoại nào trong task này."

    history = []
    for message in messages:
        raw_role, content = _message_to_role_and_content(message)
        if raw_role in {"user", "human"}:
            role = "User"
        elif raw_role in {"tool", "system"}:
            role = raw_role.capitalize()
        else:
            role = "Assistant"
        history.append(f"{role}: {content}")

    return "\n".join(history)


def summarize_transcript(messages: list[Any], *, pending_question: str = "") -> str:
    """
    Build a deterministic rolling summary for the current task/context.
    This is intentionally simple and stable so it does not depend on another LLM call.
    """
    if not messages:
        return "Chưa có ngữ cảnh task."

    user_messages = []
    assistant_messages = []
    for message in messages:
        raw_role, content = _message_to_role_and_content(message)
        cleaned = " ".join(content.split()).strip()
        if not cleaned:
            continue
        if raw_role in {"user", "human"}:
            user_messages.append(cleaned)
        elif raw_role not in {"tool", "system"}:
            assistant_messages.append(cleaned)

    latest_user = user_messages[-1] if user_messages else "không có"
    previous_user = user_messages[-2] if len(user_messages) >= 2 else "không có"
    latest_assistant = assistant_messages[-1] if assistant_messages else "không có"
    pending_line = pending_question or "không có"

    return (
        f"So luot user: {len(user_messages)}; "
        f"so luot assistant: {len(assistant_messages)}; "
        f"muc tieu gan nhat cua user: {latest_user}; "
        f"luot user truoc do: {previous_user}; "
        f"phan hoi gan nhat cua assistant: {latest_assistant}; "
        f"cau hoi dang cho: {pending_line}"
    )


def merge_context_summary(
    previous_summary: str,
    archived_messages: list[Any],
    *,
    max_chars: int = MAX_CONTEXT_SUMMARY_CHARS,
) -> str:
    """
    Merge trimmed older messages into a compact rolling summary.
    The summary is deterministic so we do not need an extra LLM call.
    """
    cleaned_previous = " ".join(str(previous_summary or "").split()).strip()
    if not archived_messages:
        return cleaned_previous

    user_messages = []
    assistant_messages = []
    for message in archived_messages:
        raw_role, content = _message_to_role_and_content(message)
        cleaned = " ".join(content.split()).strip()
        if not cleaned:
            continue
        if raw_role in {"user", "human"}:
            user_messages.append(cleaned)
        elif raw_role not in {"tool", "system"}:
            assistant_messages.append(cleaned)

    if not user_messages and not assistant_messages:
        return cleaned_previous

    latest_user = user_messages[-1] if user_messages else "không có"
    latest_assistant = assistant_messages[-1] if assistant_messages else "không có"
    recent_user_topics = " | ".join(user_messages[-3:]) if user_messages else "không có"
    new_digest = (
        f"Older context: user_turns={len(user_messages)}; "
        f"assistant_turns={len(assistant_messages)}; "
        f"latest_user_goal={latest_user}; "
        f"latest_assistant_reply={latest_assistant}; "
        f"notable_user_topics={recent_user_topics}"
    )

    if cleaned_previous:
        merged = f"{cleaned_previous}\n{new_digest}"
    else:
        merged = new_digest

    if len(merged) <= max_chars:
        return merged
    return merged[-max_chars:]


def get_current_time_string() -> str:
    """Get formatted current time"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extract_json_from_response(response_text: str) -> dict[str, Any] | None:
    """
    Extract JSON from LLM response
    Handles cases where LLM returns markdown code blocks
    """
    try:
        return json.loads(response_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    first_brace = response_text.find("{")
    if first_brace >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(first_brace, len(response_text)):
            character = response_text[index]
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    candidate = response_text[first_brace : index + 1]
                    try:
                        return json.loads(candidate)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        break

    return None


def validate_tool_call(tool_call: dict[str, Any]) -> bool:
    """Validate tool call structure"""
    required_fields = ["name", "parameters"]
    return all(field in tool_call for field in required_fields)


def build_tool_context_string(available_tools: list[str]) -> str:
    """Build tools description string for prompts"""
    from assistant_tools.schema import TOOLS_DEFINITIONS

    tool_descriptions = []
    for tool in TOOLS_DEFINITIONS:
        if tool["name"] in available_tools:
            input_schema = tool.get("input_schema", {}) if isinstance(tool.get("input_schema"), dict) else {}
            properties = input_schema.get("properties", {}) if isinstance(input_schema.get("properties"), dict) else {}
            required_fields = set(input_schema.get("required", [])) if isinstance(input_schema.get("required"), list) else set()

            tool_lines = [f"- {tool['name']}: {tool['description']}"]
            if not properties:
                tool_lines.append("  parameters: none")
            else:
                tool_lines.append("  parameters:")
                for field_name, field_schema in properties.items():
                    if not isinstance(field_schema, dict):
                        field_schema = {}
                    field_type = field_schema.get("type", "any")
                    if isinstance(field_type, list):
                        field_type = "|".join(str(item) for item in field_type)
                    enum_values = field_schema.get("enum")
                    enum_text = (
                        f"; enum={', '.join(str(item) for item in enum_values)}"
                        if isinstance(enum_values, list) and enum_values
                        else ""
                    )
                    required_text = "required" if field_name in required_fields else "optional"
                    description = str(field_schema.get("description", "") or "").strip() or "No description."
                    tool_lines.append(
                        f"    - {field_name} ({field_type}, {required_text}){enum_text}: {description}"
                    )
            tool_descriptions.append("\n".join(tool_lines))

    return "\n".join(tool_descriptions)

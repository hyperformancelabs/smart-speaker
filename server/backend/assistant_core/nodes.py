from __future__ import annotations

import logging
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Literal

import requests
from profile_schema import build_default_preferences, merge_preferences, normalize_preferences

from assistant_core.prompts import TASK_GROUPS
from assistant_core.state import LLMState
from assistant_core.utils import (
    build_response_preferences_text,
    format_full_transcript,
    format_memory,
    format_user_profile,
    get_current_time_string,
    merge_context_summary,
)
from assistant_core.wrapper import LLMWrapper
from assistant_tools.registry import execute_tool
from config import BACKEND_API_URL, EDGE_PAYLOAD_VERSION, MAX_CONVERSATION_HISTORY
from logging_utils import log_kv

logger = logging.getLogger(__name__)

CONFIRMATION_QUESTION_HINTS = (
    "bạn có chắc",
    "ban co chac",
    "bạn có muốn",
    "ban co muon",
    "xác nhận",
    "xac nhan",
    "are you sure",
    "do you want",
    "would you like",
    "confirm",
)
END_CONVERSATION_HINTS = {
    "dừng trò chuyện",
    "dung tro chuyen",
    "kết thúc trò chuyện",
    "ket thuc tro chuyen",
    "kết thúc cuộc trò chuyện",
    "ket thuc cuoc tro chuyen",
    "thôi nhé",
    "thoi nhe",
    "tạm biệt",
    "tam biet",
    "bye",
    "bye nhé",
}
FORGET_CONTEXT_HINTS = {
    "/forget",
    "/new-chat",
    "forget everything",
    "forget all",
    "quên tất cả",
    "quen tat ca",
    "quên context",
    "quen context",
    "quên ngữ cảnh",
    "quen ngu canh",
    "xóa context",
    "xoa context",
    "clear context",
    "reset context",
    "reset chat",
    "chat mới",
    "chat moi",
    "new chat",
    "bắt đầu cuộc trò chuyện mới",
    "bat dau cuoc tro chuyen moi",
    "xóa lịch sử trò chuyện",
    "xoa lich su tro chuyen",
    "quên cuộc trò chuyện này",
    "quen cuoc tro chuyen nay",
}
MEDIA_ACTION_HINTS = {
    "phát",
    "phat",
    "mở",
    "mo",
    "bật",
    "bat",
    "nghe",
    "xem",
    "play",
    "stream",
}
MEDIA_TOPIC_HINTS = {
    "nhạc",
    "nhac",
    "bài hát",
    "bai hat",
    "video",
    "clip",
    "mv",
    "playlist",
    "podcast",
    "radio",
    "youtube",
    "audio",
}
PRODUCTIVITY_HINTS = {
    "báo thức",
    "bao thuc",
    "alarm",
    "hẹn giờ",
    "hen gio",
    "timer",
    "đếm ngược",
    "dem nguoc",
    "danh sách",
    "danh sach",
    "shopping list",
    "todo list",
    "to do list",
    "ghi chú",
    "ghi chu",
    "list",
}
INFORMATION_HINTS = {
    "tra cứu",
    "tra cuu",
    "tìm thông tin",
    "tim thong tin",
    "giải thích",
    "giai thich",
    "định nghĩa",
    "dinh nghia",
    "tin tức",
    "tin tuc",
    "giá",
    "bao nhiêu",
    "bao nhieu",
    "tỷ giá",
    "ty gia",
    "chuyển đổi",
    "chuyen doi",
    "thời tiết",
    "thoi tiet",
    "là gì",
    "la gi",
}
GENERIC_INFORMATION_REQUESTS = {
    "hãy tra",
    "hay tra",
    "tra cứu",
    "tra cuu",
    "hãy tìm",
    "hay tim",
    "tìm giúp",
    "tim giup",
    "search",
}
MEDIA_FILLER_WORDS = {
    "hãy",
    "hay",
    "phát",
    "phat",
    "mở",
    "mo",
    "nghe",
    "xem",
    "bật",
    "bat",
    "cho",
    "toi",
    "tôi",
    "mình",
    "minh",
    "video",
    "nhạc",
    "nhac",
    "bài",
    "bai",
    "của",
    "cua",
    "youtube",
}
PERSONAL_DISCLOSURE_PATTERNS = (
    r"\b(tôi|toi|mình|minh|em)\s+(tên|ten)\s+(?:(?:là|la)\s+)?(.+)",
    r"\b(tôi|toi|mình|minh|em)\s+(thích|thich|yeu|yêu|ghét|ghet)\b",
    r"\b(tôi|toi|mình|minh|em)\s+(sống ở|song o|ở|o|đến từ|den tu)\b",
    r"\b(tôi|toi|mình|minh|em)\s+\d{1,3}\s+(tuổi|tuoi)\b",
)
PERSONAL_INFO_REQUEST_HINTS = (
    "thông tin cá nhân",
    "thong tin ca nhan",
    "bạn biết gì về tôi",
    "ban biet gi ve toi",
    "ghi nhớ gì về tôi",
    "ghi nho gi ve toi",
    "memory của tôi",
    "memory cua toi",
    "tên của tôi",
    "ten cua toi",
    "tôi tên gì",
    "toi ten gi",
)
CLEAR_PERSONAL_DATA_HINTS = (
    "clear toàn bộ memory",
    "clear toan bo memory",
    "clear toàn bộ pref",
    "clear toan bo pref",
    "clear toàn bộ preference",
    "clear toan bo preference",
    "clear hết memory",
    "clear het memory",
    "quên toàn bộ memory",
    "quen toan bo memory",
    "quên toàn bộ preference",
    "quen toan bo preference",
    "quên toàn bộ pref",
    "quen toan bo pref",
    "xóa toàn bộ memory",
    "xoa toan bo memory",
    "xóa toàn bộ preference",
    "xoa toan bo preference",
    "xóa hết memory",
    "xoa het memory",
)
PERSONAL_DATA_RESET_VERBS = (
    "quên",
    "quen",
    "xóa",
    "xoa",
    "clear",
    "reset",
    "erase",
    "remove",
)
PERSONAL_DATA_MEMORY_HINTS = {
    "memory",
    "ghi nhớ",
    "ghi nho",
    "ký ức",
    "ky uc",
}
PERSONAL_DATA_PREFERENCE_HINTS = {
    "pref",
    "preference",
    "preferences",
    "sở thích",
    "so thich",
    "cá nhân hoá",
    "ca nhan hoa",
    "cá nhân hóa",
    "ca nhan hoa",
    "personalization",
    "personalized",
}
PERSONAL_DATA_PROFILE_HINTS = {
    "thông tin cá nhân",
    "thong tin ca nhan",
    "thông tin về tôi",
    "thong tin ve toi",
    "mọi thứ về tôi",
    "moi thu ve toi",
    "về tôi",
    "ve toi",
    "about me",
    "hồ sơ",
    "ho so",
    "profile",
    "tên",
    "ten",
    "traits",
}
FOLLOW_UP_OFFER_HINTS = (
    "co gi minh co the giup them",
    "co gi toi co the giup them",
    "ban co can minh giup them",
    "ban co muon minh giup them",
    "ban co muon biet them",
    "ban co muon xem them",
    "ban co muon nghe them",
    "ban co muon tim hieu them",
    "ban co muon tra cuu them",
    "ban co muon biet them thong tin gi khong",
    "co muon biet them gi khong",
    "co muon xem them gi khong",
    "co muon nghe them gi khong",
    "minh co the giup gi them",
    "can gi them khong",
    "anything else",
    "help with anything else",
)
READ_ONLY_PRODUCTIVITY_SUBTASKS = {
    "alarm.read",
    "timer.read",
    "list.read",
}
RECENT_QA_TURN_LIMIT = max(1, int(MAX_CONVERSATION_HISTORY))
RECENT_CONTEXT_MESSAGE_LIMIT = max(2, RECENT_QA_TURN_LIMIT * 2)
EMPTY_CONTEXT_SUMMARY = "Chưa có ngữ cảnh cũ trước recent window."


def _guest_profile() -> dict[str, Any]:
    return {
        "name": "Guest",
        "traits": [],
        "preferences": build_default_preferences(),
        "memory": [],
    }


def _empty_task_context(group: str = "", return_mode: str = "conversation", subtask: str = "") -> dict[str, Any]:
    return {
        "group": group,
        "return_mode": return_mode,
        "subtask": subtask,
        "transcript": [],
        "summary": EMPTY_CONTEXT_SUMMARY,
        "pending": None,
    }


def _empty_session_state() -> dict[str, Any]:
    return {
        "mode": "conversation",
        "active_task": None,
        "conversation_task": None,
        "profile_cache": {},
    }


def _fresh_session_state(
    profile_cache: dict[str, Any] | None = None,
    *,
    mode: str = "conversation",
) -> dict[str, Any]:
    state = _empty_session_state()
    state["mode"] = "router" if mode == "router" else "conversation"
    state["profile_cache"] = dict(profile_cache or {})
    return state


def _normalize_lookup_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return " ".join(stripped.strip().lower().split())


def _tokenize_text(text: str) -> list[str]:
    normalized = re.sub(r"[^\w\s]", " ", _normalize_lookup_text(text), flags=re.UNICODE)
    return [token for token in normalized.split() if token]


def _clean_context_summary(summary: Any) -> str:
    cleaned = " ".join(str(summary or "").split()).strip()
    return cleaned or EMPTY_CONTEXT_SUMMARY


def _compact_task_context(task: dict[str, Any]) -> dict[str, Any]:
    transcript = task.get("transcript", [])
    if not isinstance(transcript, list):
        task["transcript"] = []
        task["summary"] = _clean_context_summary(task.get("summary"))
        return task

    if len(transcript) <= RECENT_CONTEXT_MESSAGE_LIMIT:
        task["summary"] = _clean_context_summary(task.get("summary"))
        return task

    archived_messages = transcript[:-RECENT_CONTEXT_MESSAGE_LIMIT]
    recent_messages = transcript[-RECENT_CONTEXT_MESSAGE_LIMIT:]
    previous_summary = task.get("summary")
    if _clean_context_summary(previous_summary) == EMPTY_CONTEXT_SUMMARY:
        previous_summary = ""

    task["transcript"] = recent_messages
    task["summary"] = _clean_context_summary(
        merge_context_summary(str(previous_summary or ""), archived_messages)
    )
    return task


def _normalize_task_context(task: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return None
    group = str(task.get("group", "") or "")
    if group not in TASK_GROUPS and group != "conversation":
        return None
    normalized = _empty_task_context(
        group=group,
        return_mode="conversation" if task.get("return_mode") == "conversation" else "router",
        subtask=str(task.get("subtask", "") or ""),
    )
    transcript = task.get("transcript", [])
    if isinstance(transcript, list):
        normalized["transcript"] = [
            {
                "role": str(item.get("role", "assistant")),
                "content": str(item.get("content", "") or ""),
            }
            for item in transcript
            if isinstance(item, dict) and str(item.get("content", "") or "").strip()
        ]
    normalized["summary"] = _clean_context_summary(task.get("summary", ""))
    pending = task.get("pending")
    if isinstance(pending, dict):
        normalized["pending"] = {
            "kind": str(pending.get("kind", "") or ""),
            "question": str(pending.get("question", "") or ""),
            "original_user_input": str(pending.get("original_user_input", "") or ""),
            "subtask": str(pending.get("subtask", normalized["subtask"]) or normalized["subtask"]),
            "tool_plan": pending.get("tool_plan", []) if isinstance(pending.get("tool_plan"), list) else [],
            "missing_fields": pending.get("missing_fields", []) if isinstance(pending.get("missing_fields"), list) else [],
            "context": pending.get("context", {}) if isinstance(pending.get("context"), dict) else {},
        }
    return _compact_task_context(normalized)


def _normalize_session_state(session_state: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _empty_session_state()
    if not isinstance(session_state, dict):
        return normalized

    normalized["mode"] = "router" if session_state.get("mode") == "router" else "conversation"
    profile_cache = session_state.get("profile_cache")
    if isinstance(profile_cache, dict):
        normalized["profile_cache"] = dict(profile_cache)

    active_task = _normalize_task_context(session_state.get("active_task"))
    conversation_task = _normalize_task_context(session_state.get("conversation_task"))

    # Backward-compatible migration from the earlier {mode, pending} layout.
    legacy_pending = session_state.get("pending")
    if not active_task and isinstance(legacy_pending, dict) and legacy_pending.get("group"):
        active_task = _empty_task_context(
            group=str(legacy_pending.get("group")),
            return_mode="conversation" if normalized["mode"] == "conversation" else "router",
            subtask=str(legacy_pending.get("subtask", "") or ""),
        )
        active_task["pending"] = {
            "kind": str(legacy_pending.get("kind", "") or ""),
            "question": str(legacy_pending.get("question", "") or ""),
            "original_user_input": str(legacy_pending.get("original_user_input", "") or ""),
            "subtask": str(legacy_pending.get("subtask", "") or ""),
            "tool_plan": legacy_pending.get("tool_plan", []) if isinstance(legacy_pending.get("tool_plan"), list) else [],
            "missing_fields": legacy_pending.get("missing_fields", []) if isinstance(legacy_pending.get("missing_fields"), list) else [],
            "context": legacy_pending.get("context", {}) if isinstance(legacy_pending.get("context"), dict) else {},
        }

    normalized["active_task"] = active_task
    normalized["conversation_task"] = conversation_task
    return normalized


def _pending_summary(session_state: dict[str, Any]) -> str:
    active_task = session_state.get("active_task")
    pending = active_task.get("pending") if isinstance(active_task, dict) else None
    if not pending:
        return "không có"
    return (
        f"group={active_task.get('group')}, kind={pending.get('kind')}, "
        f"subtask={pending.get('subtask')}, question={pending.get('question', '')}"
    )


def _get_active_pending(session_state: dict[str, Any]) -> dict[str, Any] | None:
    active_task = session_state.get("active_task")
    if not isinstance(active_task, dict):
        return None
    pending = active_task.get("pending")
    return pending if isinstance(pending, dict) else None


def _resolve_confirmation_reply(
    state: LLMState,
    runtime,
    *,
    group: str,
    pending: dict[str, Any],
) -> dict[str, Any]:
    llm: LLMWrapper = runtime.context.llm
    session_state = _normalize_session_state(state.get("session_state"))
    context_strings = _build_context_strings(session_state, group)

    try:
        return llm.resolve_confirmation_reply(
            group=group,
            subtask=pending.get("subtask", ""),
            pending_question=pending.get("question", ""),
            original_user_input=pending.get("original_user_input", ""),
            tool_plan=pending.get("tool_plan", []),
            user_reply=state.get("text_input", ""),
            response_preferences=_response_preferences_text(state.get("user_profile", {})),
            task_summary=context_strings["task_summary"],
            task_transcript=context_strings["task_transcript"],
            conversation_summary=context_strings["conversation_summary"],
            conversation_transcript=context_strings["conversation_transcript"],
            session_mode=session_state.get("mode", "conversation"),
        )
    except Exception:
        return {
            "decision": "unclear",
            "assistant_text": "Mình cần bạn xác nhận là đồng ý, hủy, hoặc nói rõ muốn chỉnh gì.",
            "rewritten_user_input": "",
            "reason": "resolver_exception",
            "confidence": 0.0,
        }


def _resolve_clarification_reply(
    state: LLMState,
    runtime,
    *,
    group: str,
    pending: dict[str, Any],
) -> dict[str, Any]:
    llm: LLMWrapper = runtime.context.llm
    session_state = _normalize_session_state(state.get("session_state"))
    context_strings = _build_context_strings(session_state, group)

    try:
        return llm.resolve_clarification_reply(
            group=group,
            subtask=pending.get("subtask", ""),
            pending_question=pending.get("question", ""),
            original_user_input=pending.get("original_user_input", ""),
            user_reply=state.get("text_input", ""),
            response_preferences=_response_preferences_text(state.get("user_profile", {})),
            task_summary=context_strings["task_summary"],
            task_transcript=context_strings["task_transcript"],
            conversation_summary=context_strings["conversation_summary"],
            conversation_transcript=context_strings["conversation_transcript"],
            session_mode=session_state.get("mode", "conversation"),
        )
    except Exception:
        return {
            "decision": "unclear",
            "assistant_text": "Mình cần bạn nói rõ hơn một chút để mình hiểu đúng ý.",
            "rewritten_user_input": "",
            "reason": "resolver_exception",
            "confidence": 0.0,
        }

def _looks_like_question_text(text: str) -> bool:
    normalized = _normalize_lookup_text(text)
    if not normalized:
        return False
    return text.strip().endswith("?") or any(
        phrase in normalized
        for phrase in (
            "bạn muốn",
            "ban muon",
            "bạn cần",
            "ban can",
            "which",
            "what",
            "when",
            "where",
            "how",
            "would you",
            "do you",
            "are you sure",
        )
    )


def _looks_like_confirmation_question_text(text: str) -> bool:
    normalized = _normalize_lookup_text(text)
    if not normalized:
        return False
    return any(hint in normalized for hint in CONFIRMATION_QUESTION_HINTS)


def _looks_like_follow_up_offer(text: str) -> bool:
    normalized = _normalize_lookup_text(text)
    if not normalized:
        return False
    if any(hint in normalized for hint in FOLLOW_UP_OFFER_HINTS):
        return True
    generic_patterns = (
        r"\bban co muon (?:biet|xem|nghe|tim hieu|tra cuu) them\b",
        r"\b(?:co muon|muon) (?:biet|xem|nghe|tim hieu|tra cuu) them\b",
        r"\bco gi .*giup them\b",
        r"\bthong tin gi khong\b",
        r"\bban co muon minh (?:ke|noi|giai thich|phan tich).*(?:hon|them).*(?:khong|khong ne)\b",
    )
    return any(re.search(pattern, normalized) for pattern in generic_patterns)


def _trim_trailing_follow_up_offer(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""

    trailing_patterns = (
        r"\s*(?:[Bb]ạn|[Bb]an)\s+có\s+muốn\s+(?:(?:mình|minh)\s+)?(?:biết thêm|xem thêm|nghe thêm|tìm hiểu thêm|tra cứu thêm|kể|nói|giai thich|giải thích|phan tich|phân tích)[^.?!]*$",
        r"\s*(?:[Cc]ó|[Cc]o)\s+muốn\s+(?:(?:mình|minh)\s+)?(?:biết thêm|xem thêm|nghe thêm|kể|nói|giai thich|giải thích|phan tich|phân tích)[^.?!]*$",
    )
    for pattern in trailing_patterns:
        trimmed = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip(" ,;:-")
        if trimmed != cleaned:
            return trimmed

    segments = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", cleaned) if segment.strip()]
    if len(segments) <= 1:
        return cleaned
    if _looks_like_follow_up_offer(segments[-1]):
        trimmed = " ".join(segments[:-1]).strip()
        if trimmed:
            return trimmed
    return cleaned


def _looks_like_end_conversation(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    return normalized in END_CONVERSATION_HINTS or any(hint in normalized for hint in END_CONVERSATION_HINTS)


def _looks_like_context_reset_request(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    return normalized in FORGET_CONTEXT_HINTS or any(hint in normalized for hint in FORGET_CONTEXT_HINTS)


def _looks_like_math_query(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    math_keywords = ("tính", "sqrt", "sin", "cos", "tan", "log", "ln", "cộng", "trừ", "nhân", "chia")
    if any(keyword in normalized for keyword in math_keywords):
        return True
    return bool(re.fullmatch(r"[\d\s\+\-\*\/\^\(\)\.\,%x÷×=]+", normalized))


def _looks_like_personal_disclosure(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in PERSONAL_DISCLOSURE_PATTERNS)


def _looks_like_personal_info_request(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if _extract_personal_data_reset_request(normalized):
        return False
    return any(hint in normalized for hint in PERSONAL_INFO_REQUEST_HINTS)


def _extract_personal_data_reset_request(user_input: str) -> dict[str, Any] | None:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return None

    has_reset_verb = any(verb in normalized for verb in PERSONAL_DATA_RESET_VERBS)
    has_explicit_reset_hint = any(hint in normalized for hint in CLEAR_PERSONAL_DATA_HINTS)
    if not has_reset_verb and not has_explicit_reset_hint:
        return None

    wants_memory = any(token in normalized for token in PERSONAL_DATA_MEMORY_HINTS)
    wants_preferences = any(token in normalized for token in PERSONAL_DATA_PREFERENCE_HINTS)
    wants_profile = any(token in normalized for token in PERSONAL_DATA_PROFILE_HINTS)
    wants_everything = any(token in normalized for token in {"toàn bộ", "toan bo", "mọi", "moi", "everything", "all"})
    talks_about_me = any(token in normalized for token in {"về tôi", "ve toi", "about me", "của tôi", "cua toi"})

    if talks_about_me and has_reset_verb and not (wants_memory or wants_preferences or wants_profile):
        wants_memory = True
        wants_preferences = True
        wants_profile = True

    if wants_everything and (wants_preferences or wants_profile or wants_memory):
        wants_memory = True
        wants_preferences = True
        wants_profile = True

    if wants_profile and not (wants_memory or wants_preferences):
        wants_memory = True
        wants_preferences = True

    tool_plan: list[dict[str, Any]] = []
    pieces: list[str] = []

    if wants_memory:
        tool_plan.append(
            {
                "name": "update_user_profile",
                "parameters": {"field": "memory", "value": []},
            }
        )
        pieces.append("memory")
    if wants_preferences:
        tool_plan.append(
            {
                "name": "update_user_profile",
                "parameters": {
                    "field": "preferences",
                    "value": build_default_preferences(),
                    "replace": True,
                },
            }
        )
        pieces.append("preferences")
    if wants_profile:
        tool_plan.extend(
            [
                {
                    "name": "update_user_profile",
                    "parameters": {"field": "name", "value": None},
                },
                {
                    "name": "update_user_profile",
                    "parameters": {"field": "traits", "value": []},
                },
            ]
        )
        pieces.append("hồ sơ cá nhân")

    if tool_plan:
        seen_keys: set[tuple[str, str]] = set()
        deduped_tool_plan: list[dict[str, Any]] = []
        for tool_call in tool_plan:
            parameters = tool_call.get("parameters", {})
            field = str(parameters.get("field", ""))
            key = (str(tool_call.get("name", "")), field)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_tool_plan.append(tool_call)

        target_text = " và ".join(dict.fromkeys(pieces))
        return {
            "question": f"Bạn có chắc muốn xóa toàn bộ {target_text} của mình không?",
            "subtask": "personal_data.reset",
            "tool_plan": deduped_tool_plan,
        }
    return None


def _extract_name_from_statement(statement: str) -> str:
    normalized = " ".join((statement or "").split()).strip()
    patterns = (
        r"\b(?:tôi|toi|mình|minh|em)\s+tên\s+(?:là\s+)?(.+)$",
        r"\btên\s+của\s+(?:tôi|toi|mình|minh|em)\s+là\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return ""


def _extract_explicit_memory_statement(statement: str) -> str:
    normalized = " ".join((statement or "").split()).strip()
    if not normalized:
        return ""

    patterns = (
        r"^\s*(?:hãy\s+)?(?:ghi\s*nhớ|ghi\s*nho|nhớ|nho)\s+(?:rằng|rang|là|la)?\s*(.+)$",
        r"^\s*(?:please\s+)?remember\s+(?:that\s+)?(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return ""


def _append_unique_text(items: list[Any], value: str) -> list[str]:
    cleaned_value = " ".join((value or "").split()).strip()
    normalized_items = [str(item).strip() for item in items if str(item).strip()]
    if cleaned_value and cleaned_value not in normalized_items:
        normalized_items.append(cleaned_value)
    return normalized_items


def _extract_preference_update_from_statement(
    statement: str,
    current_preferences: dict[str, Any] | None,
) -> dict[str, Any] | None:
    normalized_statement = " ".join((statement or "").split()).strip()
    normalized_lookup = _normalize_lookup_text(normalized_statement)
    if not normalized_lookup:
        return None

    existing_preferences = normalize_preferences(current_preferences)

    def _build_preference_result(update: dict[str, Any], confirmation_text: str, description: str) -> dict[str, Any]:
        return {
            "update": update,
            "confirmation_text": confirmation_text,
            "description": description,
            "subtask": "preferences.update",
        }

    def _extract_response_preference(raw_value: str) -> dict[str, Any] | None:
        lower_value = _normalize_lookup_text(raw_value)
        if any(phrase in lower_value for phrase in {"tiếng anh", "tieng anh", "english"}):
            if any(
                phrase in lower_value
                for phrase in {"trả lời", "tra loi", "nói", "noi", "giao tiếp", "giao tiep", "reply", "answer"}
            ):
                return _build_preference_result(
                    {"language": "en-US"},
                    "Bạn có muốn từ giờ mình ưu tiên trả lời bằng tiếng Anh không?",
                    "rằng bạn muốn mình ưu tiên trả lời bằng tiếng Anh",
                )
        if any(phrase in lower_value for phrase in {"tiếng việt", "tieng viet", "vietnamese"}):
            if any(
                phrase in lower_value
                for phrase in {"trả lời", "tra loi", "nói", "noi", "giao tiếp", "giao tiep", "reply", "answer"}
            ):
                return _build_preference_result(
                    {"language": "vi-VN"},
                    "Bạn có muốn từ giờ mình ưu tiên trả lời bằng tiếng Việt không?",
                    "rằng bạn muốn mình ưu tiên trả lời bằng tiếng Việt",
                )
        if any(phrase in lower_value for phrase in {"cute", "dễ thương", "de thuong", "đáng yêu", "dang yeu", "nhí nhảnh", "nhi nhanh"}):
            if any(
                phrase in lower_value
                for phrase in {"trò chuyện", "tro chuyen", "nói chuyện", "noi chuyen", "trả lời", "tra loi", "giọng", "giong", "phong cách", "phong cach"}
            ):
                return _build_preference_result(
                    {"assistant_style": "cute"},
                    "Bạn có muốn mình trò chuyện theo phong cách dễ thương hơn từ bây giờ không?",
                    "rằng bạn muốn mình trò chuyện dễ thương hơn",
                )
        if any(phrase in lower_value for phrase in {"ngắn gọn", "ngan gon", "vắn tắt", "van tat", "brief", "concise"}):
            if any(phrase in lower_value for phrase in {"trả lời", "tra loi", "phản hồi", "phan hoi", "nói", "noi"}):
                return _build_preference_result(
                    {"response_verbosity": "concise"},
                    "Bạn có muốn mình ưu tiên trả lời ngắn gọn hơn từ bây giờ không?",
                    "rằng bạn muốn mình trả lời ngắn gọn hơn",
                )
        if any(phrase in lower_value for phrase in {"chi tiết", "chi tiet", "kỹ hơn", "ky hon", "detailed"}):
            if any(phrase in lower_value for phrase in {"trả lời", "tra loi", "phản hồi", "phan hoi", "giải thích", "giai thich"}):
                return _build_preference_result(
                    {"response_verbosity": "detailed"},
                    "Bạn có muốn mình trả lời chi tiết hơn khi phù hợp không?",
                    "rằng bạn muốn mình trả lời chi tiết hơn",
                )
        return None

    direct_response_preference = _extract_response_preference(normalized_statement)
    if direct_response_preference:
        return direct_response_preference

    like_match = re.search(r"\b(?:tôi|toi|mình|minh|em)\s+(thích|yêu|yeu)\s+(.+)$", normalized_statement, flags=re.IGNORECASE)
    if like_match:
        raw_value = like_match.group(2).strip(" .,!?:;")
        response_preference = _extract_response_preference(raw_value)
        if response_preference:
            return response_preference
        lower_value = _normalize_lookup_text(raw_value)
        music_genres = existing_preferences.get("favorite_music", {}).get("genres", [])
        if lower_value.startswith("nhạc ") or any(token in lower_value for token in {"jazz", "lofi", "rock", "pop", "rap", "ballad", "acoustic"}):
            genre_value = re.sub(r"^(nhạc|nhac)\s+", "", raw_value, flags=re.IGNORECASE).strip() or raw_value
            return _build_preference_result(
                {"favorite_music": {"genres": _append_unique_text(music_genres, genre_value)}},
                f"Bạn có muốn mình ghi nhớ là bạn thích nhạc {genre_value} không?",
                f"rằng bạn thích nhạc {genre_value}",
            )

        liked_values = existing_preferences.get("likes", [])
        return _build_preference_result(
            {"likes": _append_unique_text(liked_values, raw_value)},
            f"Bạn có muốn mình ghi nhớ là bạn thích {raw_value} không?",
            f"rằng bạn thích {raw_value}",
        )

    dislike_match = re.search(r"\b(?:tôi|toi|mình|minh|em)\s+(ghét|ghet|không thích|khong thich)\s+(.+)$", normalized_statement, flags=re.IGNORECASE)
    if dislike_match:
        raw_value = dislike_match.group(2).strip(" .,!?:;")
        disliked_values = existing_preferences.get("dislikes", [])
        return _build_preference_result(
            {"dislikes": _append_unique_text(disliked_values, raw_value)},
            f"Bạn có muốn mình ghi nhớ là bạn không thích {raw_value} không?",
            f"rằng bạn không thích {raw_value}",
        )

    location_match = re.search(r"\b(?:tôi|toi|mình|minh|em)\s+(?:sống ở|song o|ở|o|đến từ|den tu)\s+(.+)$", normalized_statement, flags=re.IGNORECASE)
    if location_match:
        raw_value = location_match.group(1).strip(" .,!?:;")
        return _build_preference_result(
            {"location_context": {"home_city": raw_value}},
            f"Bạn có muốn mình ghi nhớ là bạn đang ở {raw_value} không?",
            f"rằng bạn ở {raw_value}",
        )

    age_match = re.search(r"\b(?:tôi|toi|mình|minh|em)\s+(\d{1,3})\s+tuổi\b", normalized_statement, flags=re.IGNORECASE)
    if age_match:
        return _build_preference_result(
            {"personal_profile": {"age": int(age_match.group(1))}},
            f"Bạn có muốn mình ghi nhớ là bạn {age_match.group(1)} tuổi không?",
            f"rằng bạn {age_match.group(1)} tuổi",
        )

    return None


def _merge_followup_text(original_text: str, follow_up_text: str) -> str:
    original = " ".join((original_text or "").split()).strip()
    follow_up = " ".join((follow_up_text or "").split()).strip()
    if not original:
        return follow_up
    if not follow_up:
        return original
    normalized_original = _normalize_lookup_text(original)
    normalized_follow_up = _normalize_lookup_text(follow_up)
    if normalized_follow_up in normalized_original:
        return original
    if normalized_original in normalized_follow_up:
        return follow_up

    original_tokens = set(_tokenize_text(normalized_original))
    follow_up_tokens = set(_tokenize_text(normalized_follow_up))
    overlap_ratio = (
        len(original_tokens & follow_up_tokens) / max(1, min(len(original_tokens), len(follow_up_tokens)))
    )
    similarity = SequenceMatcher(None, normalized_original, normalized_follow_up).ratio()
    if len(follow_up_tokens) >= 2 and (overlap_ratio >= 0.67 or similarity >= 0.55):
        return follow_up
    return f"{original} {follow_up}".strip()


def _clean_media_query(text: str) -> str:
    tokens = [token for token in _tokenize_text(text) if token not in MEDIA_FILLER_WORDS]
    if not tokens:
        return " ".join((text or "").split()).strip()
    return " ".join(tokens)


def _media_mode_from_text(text: str) -> str:
    normalized = _normalize_lookup_text(text)
    if any(keyword in normalized for keyword in ("video", "clip", "mv", "xem")):
        return "video"
    return "audio"


def _media_candidate_score(query: str, result: dict[str, Any]) -> float:
    cleaned_query = _clean_media_query(query)
    query_text = _normalize_lookup_text(cleaned_query)
    title = _normalize_lookup_text(result.get("title", ""))
    channel = _normalize_lookup_text(result.get("channel", ""))
    if not query_text or not title:
        return 0.0

    title_ratio = SequenceMatcher(None, query_text, title).ratio()
    channel_ratio = SequenceMatcher(None, query_text, channel).ratio() * 0.25
    query_tokens = set(_tokenize_text(query_text))
    title_tokens = set(_tokenize_text(title))
    token_overlap = (len(query_tokens & title_tokens) / max(1, len(query_tokens))) if query_tokens else 0.0
    direct_containment = 0.2 if query_text in title or title in query_text else 0.0
    return min(1.0, title_ratio * 0.55 + token_overlap * 0.45 + channel_ratio + direct_containment)


def _task_requires_confirmation(group: str, subtask: str, tool_plan: list[dict[str, Any]]) -> bool:
    if group == "productivity":
        return False
    if group == "personalization":
        if any(tool.get("name") in {"update_user_profile", "save_memory", "delete_memory"} for tool in tool_plan):
            return True
    return False


def _profile_has_meaningful_data(profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    name = str(profile.get("name", "") or "").strip()
    memory = profile.get("memory", []) if isinstance(profile.get("memory"), list) else []
    traits = profile.get("traits", []) if isinstance(profile.get("traits"), list) else []
    preferences = normalize_preferences(profile.get("preferences", {}))
    return bool(
        (name and name.lower() != "guest")
        or memory
        or traits
        or preferences != build_default_preferences()
    )


def _profile_is_placeholder_response(profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict) or not profile:
        return True

    raw_name = str(profile.get("name", "") or "").strip().lower()
    memory = profile.get("memory", []) if isinstance(profile.get("memory"), list) else []
    traits = profile.get("traits", []) if isinstance(profile.get("traits"), list) else []
    raw_preferences = profile.get("preferences")
    has_identity = bool(str(profile.get("user_id", "") or "").strip()) or bool(
        str(profile.get("nfc_tag_id", "") or "").strip()
    )

    return (
        not has_identity
        and raw_name in {"", "guest"}
        and not memory
        and not traits
        and (not isinstance(raw_preferences, dict) or raw_preferences == {})
    )


def _merge_profile_with_cache(profile: dict[str, Any], cached_profile: dict[str, Any]) -> dict[str, Any]:
    if _profile_is_placeholder_response(profile) and _profile_has_meaningful_data(cached_profile):
        return dict(cached_profile)

    return dict(profile or {})


def _profile_summary(profile: dict[str, Any]) -> str:
    return f"{format_user_profile(profile)}\nMemory:\n{format_memory(profile.get('memory', []))}"


def _response_preferences_text(profile: dict[str, Any]) -> str:
    return build_response_preferences_text(profile)


def _display_name_from_profile(profile: dict[str, Any]) -> str:
    if not isinstance(profile, dict):
        return "Guest"
    for key in ("name", "user_name"):
        value = str(profile.get(key, "") or "").strip()
        if value:
            return value
    return "Guest"


def _personalization_success_response_from_tools(state: LLMState, tool_results: list[dict[str, Any]]) -> str | None:
    successful_results = [item for item in tool_results if item.get("result", {}).get("status") == "success"]
    if not successful_results:
        return None

    last_success = successful_results[-1]
    last_result = last_success.get("result", {})
    last_parameters = last_success.get("parameters", {})
    original_input = state.get("task_input") or state.get("text_input", "")

    if last_success.get("tool") == "save_memory":
        memory_text = str(last_parameters.get("memory") or last_result.get("memory") or "").strip()
        return (
            f"Mình đã ghi nhớ rằng {memory_text}."
            if memory_text
            else "Mình đã ghi nhớ điều đó cho bạn rồi."
        )

    if last_success.get("tool") == "delete_memory":
        memory_text = str(last_parameters.get("memory") or last_result.get("memory") or "").strip()
        return (
            f"Mình đã xóa ghi nhớ '{memory_text}'."
            if memory_text
            else "Mình đã xóa mục ghi nhớ đó cho bạn rồi."
        )

    if last_success.get("tool") != "update_user_profile":
        return None

    field = str(last_result.get("field") or last_parameters.get("field") or "")
    if field == "name":
        new_name = str(last_result.get("value") or last_parameters.get("value") or "").strip()
        return (
            f"Mình đã lưu tên của bạn là {new_name}."
            if new_name
            else "Mình đã cập nhật tên của bạn."
        )

    if field == "preferences":
        preference_result = _extract_preference_update_from_statement(original_input, {})
        update = preference_result.get("update", {}) if preference_result else {}
        if update.get("language") == "en-US":
            return "Mình đã ghi nhớ rằng từ giờ sẽ ưu tiên trả lời bạn bằng tiếng Anh."
        if update.get("language") == "vi-VN":
            return "Mình đã ghi nhớ rằng từ giờ sẽ ưu tiên trả lời bạn bằng tiếng Việt."
        if update.get("assistant_style") == "cute":
            return "Mình đã ghi nhớ rằng bạn muốn mình trò chuyện dễ thương hơn."
        if update.get("assistant_style") == "calm":
            return "Mình đã ghi nhớ rằng bạn muốn mình trò chuyện điềm tĩnh hơn."
        if update.get("response_verbosity") == "concise":
            return "Mình đã ghi nhớ rằng bạn muốn mình trả lời ngắn gọn hơn."
        if update.get("response_verbosity") == "detailed":
            return "Mình đã ghi nhớ rằng bạn muốn mình trả lời chi tiết hơn khi phù hợp."
        return "Mình đã cập nhật các tùy chọn cá nhân của bạn rồi."

    if field == "memory":
        return "Mình đã cập nhật bộ nhớ cá nhân của bạn rồi."

    return None


def _looks_like_media_request(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    has_action = any(hint in normalized for hint in MEDIA_ACTION_HINTS)
    has_topic = any(hint in normalized for hint in MEDIA_TOPIC_HINTS)
    return "youtube" in normalized or (has_action and has_topic)


def _looks_like_productivity_request(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    return any(hint in normalized for hint in PRODUCTIVITY_HINTS)


def _looks_like_information_request(user_input: str) -> bool:
    normalized = _normalize_lookup_text(user_input)
    if not normalized:
        return False
    if _looks_like_math_query(user_input):
        return True
    return any(hint in normalized for hint in INFORMATION_HINTS)


def _looks_like_preference_statement(user_input: str) -> bool:
    return _extract_preference_update_from_statement(user_input, {}) is not None


def _looks_like_explicit_memory_statement(user_input: str) -> bool:
    return bool(_extract_explicit_memory_statement(user_input))


def _looks_like_personal_data_reset_request(user_input: str) -> bool:
    return _extract_personal_data_reset_request(user_input) is not None


def _derive_return_mode(session_state: dict[str, Any], route_group: str) -> str:
    del session_state
    del route_group
    return "conversation"


def _heuristic_route_group(session_state: dict[str, Any], user_input: str) -> dict[str, Any] | None:
    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = _get_active_pending(session_state)
    if session_state.get("mode") == "conversation" and _looks_like_end_conversation(user_input):
        return {
            "group": "conversation",
            "confidence": 0.99,
            "reason": "explicit_end_conversation",
        }

    if _looks_like_context_reset_request(user_input):
        if _looks_like_personal_data_reset_request(user_input):
            return {
                "group": "personalization",
                "confidence": 0.99,
                "reason": "explicit_personal_data_reset",
            }
        return {
            "group": "conversation",
            "confidence": 0.99,
            "reason": "explicit_context_reset",
        }

    if active_task and active_task.get("group") != "conversation":
        return {
            "group": active_task["group"],
            "confidence": 0.99,
            "reason": "continue_active_task_until_complete",
        }

    if (
        _looks_like_personal_disclosure(user_input)
        or _looks_like_personal_info_request(user_input)
        or _looks_like_preference_statement(user_input)
        or _looks_like_explicit_memory_statement(user_input)
    ):
        return {
            "group": "personalization",
            "confidence": 0.95,
            "reason": "detected_personal_information_intent",
        }

    if _looks_like_productivity_request(user_input):
        return {
            "group": "productivity",
            "confidence": 0.92,
            "reason": "detected_productivity_intent",
        }

    if _looks_like_media_request(user_input):
        return {
            "group": "media",
            "confidence": 0.92,
            "reason": "detected_media_intent",
        }

    if _looks_like_information_request(user_input):
        return {
            "group": "information_query",
            "confidence": 0.9,
            "reason": "detected_information_intent",
        }

    return None


def _ensure_conversation_task(session_state: dict[str, Any]) -> dict[str, Any]:
    task = _normalize_task_context(session_state.get("conversation_task"))
    if not task:
        task = _empty_task_context(group="conversation", return_mode="conversation", subtask="chat")
    session_state["conversation_task"] = task
    return task


def _ensure_active_task(
    session_state: dict[str, Any],
    *,
    group: str,
    return_mode: str,
    subtask: str,
) -> dict[str, Any]:
    task = _normalize_task_context(session_state.get("active_task"))
    if not task or task.get("group") != group:
        task = _empty_task_context(group=group, return_mode=return_mode, subtask=subtask)
    task["return_mode"] = return_mode
    if subtask:
        task["subtask"] = subtask
    session_state["active_task"] = task
    return task


def _set_active_pending(
    session_state: dict[str, Any],
    *,
    group: str,
    return_mode: str,
    kind: str,
    question: str,
    original_user_input: str,
    subtask: str,
    tool_plan: list[dict[str, Any]] | None = None,
    missing_fields: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = _ensure_active_task(session_state, group=group, return_mode=return_mode, subtask=subtask)
    task["pending"] = {
        "kind": kind,
        "question": question,
        "original_user_input": original_user_input,
        "subtask": subtask,
        "tool_plan": tool_plan or [],
        "missing_fields": missing_fields or [],
        "context": context or {},
    }
    return session_state


def _clear_active_pending(session_state: dict[str, Any]) -> dict[str, Any]:
    task = _normalize_task_context(session_state.get("active_task"))
    if task:
        task["pending"] = None
        session_state["active_task"] = task
    return session_state


def _build_context_strings(session_state: dict[str, Any], group: str) -> dict[str, str]:
    active_task = _normalize_task_context(session_state.get("active_task"))
    conversation_task = _normalize_task_context(session_state.get("conversation_task"))
    task_context = conversation_task if group == "conversation" else active_task

    if task_context and task_context.get("group") == group:
        task_summary = _clean_context_summary(task_context.get("summary"))
        task_transcript = format_full_transcript(task_context.get("transcript", []))
    else:
        task_summary = EMPTY_CONTEXT_SUMMARY
        task_transcript = "Chưa có recent transcript trước đó cho task này."

    if conversation_task:
        conversation_summary = _clean_context_summary(conversation_task.get("summary"))
        conversation_transcript = format_full_transcript(conversation_task.get("transcript", []))
    else:
        conversation_summary = EMPTY_CONTEXT_SUMMARY
        conversation_transcript = "Không có recent transcript conversation đang mở."

    return {
        "task_summary": task_summary,
        "task_transcript": task_transcript,
        "conversation_summary": conversation_summary,
        "conversation_transcript": conversation_transcript,
    }


def _append_turn(transcript: list[dict[str, str]], role: str, content: str) -> None:
    cleaned = " ".join((content or "").split()).strip()
    if not cleaned:
        return
    if transcript and transcript[-1].get("role") == role and transcript[-1].get("content") == cleaned:
        return
    transcript.append({"role": role, "content": cleaned})


def _refresh_task_summary(task: dict[str, Any]) -> None:
    _compact_task_context(task)


def _clear_completed_task_contexts(
    session_state: dict[str, Any],
    *,
    group: str,
    task_status: str,
    return_mode: str,
) -> dict[str, Any]:
    if group == "conversation":
        if task_status == "completed":
            session_state["mode"] = "router"
            session_state["active_task"] = None
            session_state["conversation_task"] = None
        else:
            session_state["mode"] = "conversation"
        return session_state

    if task_status in {"needs_clarification", "needs_confirmation"}:
        return session_state

    session_state["active_task"] = None
    if return_mode == "conversation":
        session_state["mode"] = "conversation"
    else:
        session_state["mode"] = "router"
    return session_state


def _record_turn_in_context(
    session_state: dict[str, Any],
    *,
    user_input: str,
    assistant_text: str,
    group: str,
    subtask: str,
    return_mode: str,
    task_status: str,
) -> dict[str, Any]:
    if group == "conversation":
        conversation_task = _ensure_conversation_task(session_state)
        conversation_task["subtask"] = subtask or "chat"
        _append_turn(conversation_task["transcript"], "user", user_input)
        _append_turn(conversation_task["transcript"], "assistant", assistant_text)
        _refresh_task_summary(conversation_task)
        session_state["conversation_task"] = conversation_task
        return _clear_completed_task_contexts(
            session_state,
            group=group,
            task_status=task_status,
            return_mode=return_mode,
        )

    active_task = _normalize_task_context(session_state.get("active_task"))
    should_record_in_conversation = return_mode == "conversation" or session_state.get("mode") == "conversation"
    if task_status in {"needs_clarification", "needs_confirmation"}:
        if not active_task or active_task.get("group") != group:
            active_task = _ensure_active_task(session_state, group=group, return_mode=return_mode, subtask=subtask)
        _append_turn(active_task["transcript"], "user", user_input)
        _append_turn(active_task["transcript"], "assistant", assistant_text)
        _refresh_task_summary(active_task)
        session_state["active_task"] = active_task

    if should_record_in_conversation:
        conversation_task = _ensure_conversation_task(session_state)
        _append_turn(conversation_task["transcript"], "user", user_input)
        _append_turn(conversation_task["transcript"], "assistant", assistant_text)
        _refresh_task_summary(conversation_task)
        session_state["conversation_task"] = conversation_task

    return _clear_completed_task_contexts(
        session_state,
        group=group,
        task_status=task_status,
        return_mode=return_mode,
    )


def _sync_profile_cache_from_profile(session_state: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return session_state
    if not _profile_is_placeholder_response(profile):
        session_state["profile_cache"] = dict(profile)
    return session_state


def _sync_profile_cache_from_tool_results(session_state: dict[str, Any], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    profile_cache = dict(session_state.get("profile_cache", {}))
    changed = False
    for item in tool_results:
        result = item.get("result", {})
        if result.get("status") != "success":
            continue
        tool_name = item.get("tool")
        if tool_name == "get_user_profile" and isinstance(result.get("profile"), dict):
            profile_cache = dict(result["profile"])
            changed = True
        elif tool_name == "update_user_profile":
            if isinstance(result.get("profile"), dict):
                profile_cache = dict(result["profile"])
                changed = True
                continue
            field = result.get("field")
            value = result.get("value")
            if field == "name":
                profile_cache["name"] = value
                changed = True
            elif field == "traits":
                profile_cache["traits"] = value if isinstance(value, list) else [value]
                changed = True
            elif field == "preferences":
                profile_cache["preferences"] = value if isinstance(value, dict) else {}
                changed = True
            elif field == "memory":
                profile_cache["memory"] = value if isinstance(value, list) else []
                changed = True
        elif tool_name == "save_memory":
            profile_cache["memory"] = list(result.get("all_memories", profile_cache.get("memory", [])))
            changed = True
        elif tool_name == "delete_memory":
            profile_cache["memory"] = list(result.get("all_memories", profile_cache.get("memory", [])))
            changed = True

    if changed:
        session_state["profile_cache"] = profile_cache
    return session_state


def _make_update(
    *,
    state: LLMState,
    response_text: str,
    session_state: dict[str, Any],
    group: str,
    subtask: str,
    confidence: float = 0.8,
    task_status: str = "completed",
    dialogue_action: str = "respond_only",
    tool_calls: list[dict[str, Any]] | None = None,
    missing_fields: list[str] | None = None,
    task_input: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "group": group,
        "intent": group,
        "subtask": subtask,
        "confidence": confidence,
        "task_status": task_status,
        "return_mode": state.get("route_return_mode", "conversation"),
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    current_time = state.get("current_time") or get_current_time_string()
    return {
        "response_text": response_text,
        "tool_calls": tool_calls or [],
        "metadata": metadata,
        "session_state": session_state,
        "current_time": current_time,
        "dialogue_action": dialogue_action,
        "needs_clarification": task_status == "needs_clarification",
        "clarification_prompt": response_text if task_status in {"needs_clarification", "needs_confirmation"} else "",
        "missing_fields": missing_fields or [],
        "task_input": task_input or state.get("text_input", ""),
    }


def load_user_profile(state: LLMState, runtime) -> dict[str, Any]:
    nfc_tag_id = state.get("nfc_tag_id")
    session_state = _normalize_session_state(state.get("session_state"))
    cached_profile = session_state.get("profile_cache", {}) if isinstance(session_state.get("profile_cache"), dict) else {}

    if not nfc_tag_id:
        profile = cached_profile or _guest_profile()
        return {
            "user_profile": profile,
            "user_name": _display_name_from_profile(profile),
            "user_memory": profile.get("memory", []),
            "session_state": session_state,
        }

    try:
        response = requests.get(f"{BACKEND_API_URL}/api/users/{nfc_tag_id}", timeout=5)
        response.raise_for_status()
        profile = _merge_profile_with_cache(response.json(), cached_profile)
        session_state = _sync_profile_cache_from_profile(session_state, profile)
        return {
            "user_profile": profile,
            "user_name": _display_name_from_profile(profile),
            "user_memory": profile.get("memory", []),
            "session_state": session_state,
        }
    except Exception:
        profile = cached_profile or _guest_profile()
        return {
            "user_profile": profile,
            "user_name": _display_name_from_profile(profile),
            "user_memory": profile.get("memory", []),
            "session_state": session_state,
        }


def router_agent(state: LLMState, runtime) -> dict[str, Any]:
    llm: LLMWrapper = runtime.context.llm
    user_input = state.get("text_input", "")
    current_time = state.get("current_time") or get_current_time_string()
    session_state = _normalize_session_state(state.get("session_state"))

    start_time = time.time()

    route_result = _heuristic_route_group(session_state, user_input)
    if route_result is None:
        context_strings = _build_context_strings(
            session_state,
            "conversation",
        )
        route_result = llm.route_intent(
            user_input=user_input,
            conversation_summary=context_strings["conversation_summary"],
            conversation_transcript=context_strings["conversation_transcript"],
            session_mode=session_state.get("mode", "conversation"),
            pending_summary=_pending_summary(session_state),
        )

    route_group = route_result.get("group", "conversation")
    return_mode = _derive_return_mode(session_state, route_group)
    latency = int((time.time() - start_time) * 1000)
    log_kv(
        logger,
        logging.INFO,
        "router_decision",
        user_input=user_input,
        route_group=route_group,
        confidence=route_result.get("confidence", 0.5),
        reason=route_result.get("reason", ""),
        return_mode=return_mode,
        latency_ms=latency,
    )
    intent_classification = {
        "group": route_group,
        "intent": route_group,
        "confidence": route_result.get("confidence", 0.5),
        "reason": route_result.get("reason", ""),
        "allowed_tools": list(TASK_GROUPS.get(route_group, {}).get("tools", [])),
        "return_mode": return_mode,
    }

    return {
        "intent_classification": intent_classification,
        "route_group": route_group,
        "route_return_mode": return_mode,
        "processing_latency_ms": state.get("processing_latency_ms", 0) + latency,
        "current_time": current_time,
        "session_state": session_state,
        "metadata": {
            "group": route_group,
            "intent": route_group,
            "confidence": route_result.get("confidence", 0.5),
            "return_mode": return_mode,
        },
    }


def chat_node(state: LLMState, runtime) -> dict[str, Any]:
    """
    Main chat shell for every turn.

    The user always enters through conversation mode first; subtask routing is
    an internal decision of the chat shell rather than the public entrypoint.
    """
    session_state = _normalize_session_state(state.get("session_state"))
    if not _normalize_task_context(session_state.get("active_task")):
        session_state["mode"] = "conversation"

    route_update = router_agent({**state, "session_state": session_state}, runtime)
    normalized_session_state = _normalize_session_state(route_update.get("session_state"))
    if not _normalize_task_context(normalized_session_state.get("active_task")):
        normalized_session_state["mode"] = "conversation"

    route_update["session_state"] = normalized_session_state
    route_update["metadata"] = {
        **(route_update.get("metadata", {}) if isinstance(route_update.get("metadata"), dict) else {}),
        "shell": "chat",
    }
    return route_update


def _run_llm_group_agent(
    state: LLMState,
    runtime,
    group: str,
    effective_input: str,
    *,
    tools_available: list[str] | None = None,
) -> dict[str, Any]:
    llm: LLMWrapper = runtime.context.llm
    session_state = _normalize_session_state(state.get("session_state"))
    context_strings = _build_context_strings(session_state, group)
    selected_tools = tools_available if tools_available is not None else list(TASK_GROUPS.get(group, {}).get("tools", []))
    return llm.run_group_agent(
        group=group,
        user_input=effective_input,
        user_name=state.get("user_name", "Guest"),
        current_time=state.get("current_time") or get_current_time_string(),
        response_preferences=_response_preferences_text(state.get("user_profile", {})),
        user_profile=_profile_summary(state.get("user_profile", {})),
        task_summary=context_strings["task_summary"],
        task_transcript=context_strings["task_transcript"],
        conversation_summary=context_strings["conversation_summary"],
        conversation_transcript=context_strings["conversation_transcript"],
        tools_available=selected_tools,
        session_mode=session_state.get("mode", "conversation"),
        return_mode=state.get("route_return_mode", "conversation"),
        pending_summary=_pending_summary(session_state),
    )


def _normalize_task_agent_result(
    group: str,
    agent_result: dict[str, Any],
    *,
    fallback_subtask: str,
) -> dict[str, Any]:
    normalized = dict(agent_result or {})
    dialogue_action = str(normalized.get("dialogue_action", "respond_only") or "respond_only")
    response_text = str(normalized.get("assistant_text", "") or "")
    tool_plan = normalized.get("tool_plan", [])
    if not isinstance(tool_plan, list):
        tool_plan = []
    normalized["tool_plan"] = tool_plan

    if dialogue_action not in {"use_tools", "ask_clarification", "ask_confirmation", "respond_only", "end_conversation"}:
        dialogue_action = "respond_only"

    # For non-conversation tasks, a question must create a typed pending state.
    if (
        group != "conversation"
        and dialogue_action == "respond_only"
        and _looks_like_question_text(response_text)
        and not _looks_like_follow_up_offer(response_text)
    ):
        dialogue_action = "ask_confirmation" if tool_plan and _looks_like_confirmation_question_text(response_text) else "ask_clarification"

    if dialogue_action == "ask_confirmation" and not tool_plan:
        dialogue_action = "ask_clarification"

    normalized["dialogue_action"] = dialogue_action
    normalized["subtask"] = str(normalized.get("subtask", fallback_subtask) or fallback_subtask)
    normalized["assistant_text"] = response_text
    return normalized


def _normalize_tool_synthesis_output(
    group: str,
    synthesis_result: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(synthesis_result or {})
    dialogue_action = str(normalized.get("dialogue_action", "respond_only") or "respond_only")
    response_text = str(normalized.get("assistant_text", "") or "")
    missing_fields = normalized.get("missing_fields", [])
    if not isinstance(missing_fields, list):
        missing_fields = []

    if _looks_like_follow_up_offer(response_text) and not missing_fields:
        dialogue_action = "respond_only"

    if (
        group != "conversation"
        and dialogue_action == "respond_only"
        and _looks_like_question_text(response_text)
        and not _looks_like_follow_up_offer(response_text)
    ):
        dialogue_action = "ask_clarification"

    normalized["dialogue_action"] = dialogue_action
    normalized["assistant_text"] = response_text
    normalized["missing_fields"] = missing_fields
    return normalized


def media_agent(state: LLMState, runtime) -> dict[str, Any]:
    session_state = _normalize_session_state(state.get("session_state"))
    user_input = state.get("text_input", "")
    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = _get_active_pending(session_state)
    return_mode = state.get("route_return_mode", "conversation")

    confirmation_update, user_input, session_state = _handle_confirmation_pending(
        state,
        runtime,
        "media",
        confirm_response_text="Được rồi, mình phát cho bạn ngay.",
        deny_response_text="Được rồi, mình sẽ không phát nội dung đó.",
    )
    if confirmation_update is not None:
        return confirmation_update
    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = _get_active_pending(session_state)

    if active_task and active_task.get("group") == "media" and pending and pending.get("kind") == "clarification":
        user_input = _merge_followup_text(pending.get("original_user_input", ""), user_input)
        session_state = _clear_active_pending(session_state)

    query = _clean_media_query(user_input)
    if not query:
        question = "Bạn muốn mình phát bài hát hoặc video nào?"
        session_state = _set_active_pending(
            session_state,
            group="media",
            return_mode=return_mode,
            kind="clarification",
            question=question,
            original_user_input=user_input,
            subtask="play_media",
        )
        return _make_update(
            state=state,
            response_text=question,
            session_state=session_state,
            group="media",
            subtask="play_media",
            confidence=0.7,
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
        )

    agent_result = _normalize_task_agent_result(
        "media",
        _run_llm_group_agent({**state, "session_state": session_state}, runtime, "media", user_input),
        fallback_subtask="play_media",
    )
    mode = agent_result.get("slots", {}).get("mode") or _media_mode_from_text(user_input)
    response_text = agent_result.get("assistant_text") or "Mình đang tìm nội dung phù hợp cho bạn."
    if agent_result.get("dialogue_action") == "ask_clarification":
        session_state = _set_active_pending(
            session_state,
            group="media",
            return_mode=return_mode,
            kind="clarification",
            question=response_text,
            original_user_input=user_input,
            subtask="play_media",
            missing_fields=agent_result.get("missing_fields", []),
        )
        return _make_update(
            state=state,
            response_text=response_text,
            session_state=session_state,
            group="media",
            subtask="play_media",
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
            missing_fields=agent_result.get("missing_fields", []),
            task_input=user_input,
        )

    tool_plan = [{"name": "youtube_search", "parameters": {"query": query, "max_results": 5}}]
    return _make_update(
        state=state,
        response_text=response_text,
        session_state=_ensure_active_task(session_state, group="media", return_mode=return_mode, subtask="play_media"),
        group="media",
        subtask="play_media",
        confidence=agent_result.get("confidence", 0.8),
        task_status="in_progress",
        dialogue_action="use_tools",
        tool_calls=tool_plan,
        task_input=user_input,
        extra_metadata={"mode": mode, "search_query": query},
    )


def information_query_agent(state: LLMState, runtime) -> dict[str, Any]:
    session_state = _normalize_session_state(state.get("session_state"))
    user_input = state.get("text_input", "")
    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = _get_active_pending(session_state)
    return_mode = state.get("route_return_mode", "conversation")

    if active_task and active_task.get("group") == "information_query" and pending and pending.get("kind") == "clarification":
        user_input = _merge_followup_text(pending.get("original_user_input", ""), user_input)
        session_state = _clear_active_pending(session_state)

    if _looks_like_math_query(user_input):
        return _make_update(
            state=state,
            response_text="Mình tính giúp bạn ngay.",
            session_state=_ensure_active_task(session_state, group="information_query", return_mode=return_mode, subtask="calculate"),
            group="information_query",
            subtask="calculate",
            confidence=0.95,
            task_status="in_progress",
            dialogue_action="use_tools",
            tool_calls=[{"name": "calculator", "parameters": {"expression": user_input}}],
            task_input=user_input,
        )

    agent_result = _normalize_task_agent_result(
        "information_query",
        _run_llm_group_agent({**state, "session_state": session_state}, runtime, "information_query", user_input),
        fallback_subtask="search_information",
    )
    response_text = agent_result.get("assistant_text") or "Mình đang tra cứu cho bạn."
    if agent_result.get("dialogue_action") == "ask_clarification":
        session_state = _set_active_pending(
            session_state,
            group="information_query",
            return_mode=return_mode,
            kind="clarification",
            question=response_text,
            original_user_input=user_input,
            subtask=agent_result.get("subtask", "search_information"),
            missing_fields=agent_result.get("missing_fields", []),
        )
        return _make_update(
            state=state,
            response_text=response_text,
            session_state=session_state,
            group="information_query",
            subtask=agent_result.get("subtask", "search_information"),
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
            missing_fields=agent_result.get("missing_fields", []),
            task_input=user_input,
        )

    tool_plan = agent_result.get("tool_plan", [])
    if not tool_plan:
        tool_plan = [{"name": "web_search", "parameters": {"query": user_input, "max_results": 5}}]

    return _make_update(
        state=state,
        response_text=response_text,
        session_state=_ensure_active_task(
            session_state,
            group="information_query",
            return_mode=return_mode,
            subtask=agent_result.get("subtask", "search_information"),
        ),
        group="information_query",
        subtask=agent_result.get("subtask", "search_information"),
        confidence=agent_result.get("confidence", 0.8),
        task_status="in_progress",
        dialogue_action="use_tools",
        tool_calls=tool_plan,
        task_input=user_input,
    )


def _handle_confirmation_pending(
    state: LLMState,
    runtime,
    group: str,
    *,
    confirm_response_text: str,
    deny_response_text: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    session_state = _normalize_session_state(state.get("session_state"))
    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = _get_active_pending(session_state)
    user_input = state.get("text_input", "")
    if not active_task or active_task.get("group") != group or not pending or pending.get("kind") != "confirmation":
        return None, user_input, session_state

    resolution = _resolve_confirmation_reply(state, runtime, group=group, pending=pending)
    decision = resolution.get("decision", "unclear")
    task_input = pending.get("original_user_input") or user_input
    confidence = resolution.get("confidence", 0.99)
    subtask = pending.get("subtask", active_task.get("subtask", ""))

    if decision == "confirm":
        session_state = _clear_active_pending(session_state)
        return _make_update(
            state=state,
            response_text=confirm_response_text,
            session_state=session_state,
            group=group,
            subtask=subtask,
            confidence=confidence,
            task_status="in_progress",
            dialogue_action="use_tools",
            tool_calls=pending.get("tool_plan", []),
            task_input=task_input,
        ), user_input, session_state

    if decision == "deny":
        session_state = _clear_active_pending(session_state)
        return _make_update(
            state=state,
            response_text=deny_response_text,
            session_state=session_state,
            group=group,
            subtask=subtask,
            confidence=confidence,
            task_status="completed",
            dialogue_action="respond_only",
            task_input=task_input,
        ), user_input, session_state

    if decision == "revise":
        revised_input = resolution.get("rewritten_user_input") or _merge_followup_text(task_input, user_input)
        session_state = _clear_active_pending(session_state)
        return None, revised_input, session_state

    question = resolution.get("assistant_text") or pending.get("question") or "Bạn có đồng ý xác nhận yêu cầu này không?"
    return _make_update(
        state=state,
        response_text=question,
        session_state=session_state,
        group=group,
        subtask=subtask,
        confidence=confidence,
        task_status="needs_confirmation",
        dialogue_action="ask_confirmation",
        task_input=task_input,
    ), user_input, session_state


def _handle_clarification_pending(state: LLMState, runtime, group: str) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    session_state = _normalize_session_state(state.get("session_state"))
    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = _get_active_pending(session_state)
    user_input = state.get("text_input", "")
    if not active_task or active_task.get("group") != group or not pending or pending.get("kind") != "clarification":
        return None, user_input, session_state

    resolution = _resolve_clarification_reply(state, runtime, group=group, pending=pending)
    decision = resolution.get("decision", "unclear")
    original_user_input = pending.get("original_user_input") or user_input
    confidence = resolution.get("confidence", 0.8)
    subtask = pending.get("subtask", active_task.get("subtask", ""))

    if decision == "resolved":
        rewritten_input = resolution.get("rewritten_user_input") or _merge_followup_text(original_user_input, user_input)
        session_state = _clear_active_pending(session_state)
        return None, rewritten_input, session_state

    if decision == "cancel":
        session_state = _clear_active_pending(session_state)
        return _make_update(
            state=state,
            response_text="Được rồi, mình sẽ dừng yêu cầu đó.",
            session_state=session_state,
            group=group,
            subtask=subtask,
            confidence=confidence,
            task_status="completed",
            dialogue_action="respond_only",
            task_input=original_user_input,
        ), user_input, session_state

    question = resolution.get("assistant_text") or pending.get("question") or "Mình cần bạn nói rõ hơn một chút."
    return _make_update(
        state=state,
        response_text=question,
        session_state=session_state,
        group=group,
        subtask=subtask,
        confidence=confidence,
        task_status="needs_clarification",
        dialogue_action="ask_clarification",
        task_input=original_user_input,
        missing_fields=pending.get("missing_fields", []),
    ), user_input, session_state


def productivity_agent(state: LLMState, runtime) -> dict[str, Any]:
    confirmation_update, user_input, session_state = _handle_confirmation_pending(
        state,
        runtime,
        "productivity",
        confirm_response_text="Được rồi, mình thực hiện ngay.",
        deny_response_text="Được rồi, mình sẽ không thực hiện yêu cầu đó.",
    )
    if confirmation_update is not None:
        return confirmation_update

    clarification_update, user_input, session_state = _handle_clarification_pending(
        {**state, "text_input": user_input, "session_state": session_state},
        runtime,
        "productivity",
    )
    if clarification_update is not None:
        return clarification_update
    return_mode = state.get("route_return_mode", "conversation")
    agent_result = _normalize_task_agent_result(
        "productivity",
        _run_llm_group_agent(
            {**state, "session_state": session_state},
            runtime,
            "productivity",
            user_input,
        ),
        fallback_subtask="productivity_action",
    )
    log_kv(
        logger,
        logging.INFO,
        "productivity_llm_plan_selected",
        user_input=user_input,
        current_time=state.get("current_time") or get_current_time_string(),
        dialogue_action=agent_result.get("dialogue_action"),
        subtask=agent_result.get("subtask"),
        tool_plan=agent_result.get("tool_plan", []),
        missing_fields=agent_result.get("missing_fields", []),
        assistant_text=agent_result.get("assistant_text"),
    )
    response_text = agent_result.get("assistant_text") or "Mình đang xử lý yêu cầu của bạn."
    tool_plan = agent_result.get("tool_plan", [])
    subtask = agent_result.get("subtask", "productivity_action")

    if agent_result.get("dialogue_action") == "ask_clarification":
        session_state = _set_active_pending(
            session_state,
            group="productivity",
            return_mode=return_mode,
            kind="clarification",
            question=response_text,
            original_user_input=user_input,
            subtask=subtask,
            missing_fields=agent_result.get("missing_fields", []),
        )
        return _make_update(
            state=state,
            response_text=response_text,
            session_state=session_state,
            group="productivity",
            subtask=subtask,
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
            missing_fields=agent_result.get("missing_fields", []),
            task_input=user_input,
        )

    if agent_result.get("dialogue_action") == "ask_confirmation" and tool_plan:
        session_state = _set_active_pending(
            session_state,
            group="productivity",
            return_mode=return_mode,
            kind="confirmation",
            question=response_text,
            original_user_input=user_input,
            subtask=subtask,
            tool_plan=tool_plan,
        )
        return _make_update(
            state=state,
            response_text=response_text,
            session_state=session_state,
            group="productivity",
            subtask=subtask,
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    if _task_requires_confirmation("productivity", subtask, tool_plan):
        confirmation_text = response_text
        if not confirmation_text or "xac nhan" not in _normalize_lookup_text(confirmation_text):
            confirmation_text = f"Hãy xác nhận bạn muốn thực hiện yêu cầu này: {user_input.strip()}."
        session_state = _set_active_pending(
            session_state,
            group="productivity",
            return_mode=return_mode,
            kind="confirmation",
            question=confirmation_text,
            original_user_input=user_input,
            subtask=subtask,
            tool_plan=tool_plan,
        )
        return _make_update(
            state=state,
            response_text=confirmation_text,
            session_state=session_state,
            group="productivity",
            subtask=subtask,
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    return _make_update(
        state=state,
        response_text=response_text,
        session_state=_ensure_active_task(session_state, group="productivity", return_mode=return_mode, subtask=subtask),
        group="productivity",
        subtask=subtask,
        confidence=agent_result.get("confidence", 0.8),
        task_status="in_progress" if tool_plan else "completed",
        dialogue_action="use_tools" if tool_plan else "respond_only",
        tool_calls=tool_plan,
        task_input=user_input,
    )


def personalization_agent(state: LLMState, runtime) -> dict[str, Any]:
    confirmation_update, user_input, session_state = _handle_confirmation_pending(
        state,
        runtime,
        "personalization",
        confirm_response_text="Được rồi, mình thực hiện ngay.",
        deny_response_text="Được rồi, mình sẽ không thực hiện yêu cầu đó.",
    )
    if confirmation_update is not None:
        return confirmation_update

    clarification_update, user_input, session_state = _handle_clarification_pending(
        {**state, "text_input": user_input, "session_state": session_state},
        runtime,
        "personalization",
    )
    if clarification_update is not None:
        return clarification_update
    return_mode = state.get("route_return_mode", "conversation")

    reset_request = _extract_personal_data_reset_request(user_input)
    if reset_request:
        session_state = _set_active_pending(
            session_state,
            group="personalization",
            return_mode=return_mode,
            kind="confirmation",
            question=reset_request["question"],
            original_user_input=user_input,
            subtask=reset_request["subtask"],
            tool_plan=reset_request["tool_plan"],
        )
        return _make_update(
            state=state,
            response_text=reset_request["question"],
            session_state=session_state,
            group="personalization",
            subtask=reset_request["subtask"],
            confidence=0.98,
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    if _looks_like_personal_info_request(user_input):
        tool_name = (
            "get_memory"
            if "memory" in _normalize_lookup_text(user_input) or "ghi nho" in _normalize_lookup_text(user_input)
            else "get_user_profile"
        )
        return _make_update(
            state=state,
            response_text="Mình kiểm tra thông tin đã lưu của bạn nhé.",
            session_state=_ensure_active_task(
                session_state,
                group="personalization",
                return_mode=return_mode,
                subtask="memory.read" if tool_name == "get_memory" else "profile.read",
            ),
            group="personalization",
            subtask="memory.read" if tool_name == "get_memory" else "profile.read",
            confidence=0.92,
            task_status="in_progress",
            dialogue_action="use_tools",
            tool_calls=[{"name": tool_name, "parameters": {}}],
            task_input=user_input,
        )

    preference_result = _extract_preference_update_from_statement(
        user_input,
        state.get("user_profile", {}).get("preferences", {}),
    )
    if preference_result:
        merged_preferences = merge_preferences(
            normalize_preferences(state.get("user_profile", {}).get("preferences", {})),
            preference_result["update"],
        )
        session_state = _set_active_pending(
            session_state,
            group="personalization",
            return_mode=return_mode,
            kind="confirmation",
            question=preference_result["confirmation_text"],
            original_user_input=user_input,
            subtask=preference_result.get("subtask", "preferences.update"),
            tool_plan=[
                {
                    "name": "update_user_profile",
                    "parameters": {"field": "preferences", "value": merged_preferences},
                }
            ],
            context={"preference_update": preference_result["update"]},
        )
        return _make_update(
            state=state,
            response_text=preference_result["confirmation_text"],
            session_state=session_state,
            group="personalization",
            subtask=preference_result.get("subtask", "preferences.update"),
            confidence=0.97,
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    explicit_memory = _extract_explicit_memory_statement(user_input)
    if explicit_memory:
        question = f"Bạn có muốn mình ghi nhớ rằng {explicit_memory} không?"
        session_state = _set_active_pending(
            session_state,
            group="personalization",
            return_mode=return_mode,
            kind="confirmation",
            question=question,
            original_user_input=user_input,
            subtask="memory.create",
            tool_plan=[{"name": "save_memory", "parameters": {"memory": explicit_memory}}],
        )
        return _make_update(
            state=state,
            response_text=question,
            session_state=session_state,
            group="personalization",
            subtask="memory.create",
            confidence=0.96,
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    if _looks_like_personal_disclosure(user_input):
        extracted_name = _extract_name_from_statement(user_input)
        if extracted_name:
            tool_plan = [
                {
                    "name": "update_user_profile",
                    "parameters": {"field": "name", "value": extracted_name},
                }
            ]
            question = f"Tôi nghe bạn nói tên bạn là {extracted_name}. Bạn có muốn tôi ghi nhớ {extracted_name} là tên của bạn không?"
            subtask = "profile.update"
        else:
            tool_plan = [{"name": "save_memory", "parameters": {"memory": user_input.strip()}}]
            question = f"Bạn có muốn tôi ghi nhớ rằng {user_input.strip()} không?"
            subtask = "memory.create"

        session_state = _set_active_pending(
            session_state,
            group="personalization",
            return_mode=return_mode,
            kind="confirmation",
            question=question,
            original_user_input=user_input,
            subtask=subtask,
            tool_plan=tool_plan,
        )
        return _make_update(
            state=state,
            response_text=question,
            session_state=session_state,
            group="personalization",
            subtask=subtask,
            confidence=0.95,
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    agent_result = _normalize_task_agent_result(
        "personalization",
        _run_llm_group_agent({**state, "session_state": session_state}, runtime, "personalization", user_input),
        fallback_subtask="profile.read",
    )
    response_text = agent_result.get("assistant_text") or "Mình đang kiểm tra thông tin của bạn."
    tool_plan = agent_result.get("tool_plan", [])
    subtask = agent_result.get("subtask", "profile.read")

    if agent_result.get("dialogue_action") == "ask_clarification":
        session_state = _set_active_pending(
            session_state,
            group="personalization",
            return_mode=return_mode,
            kind="clarification",
            question=response_text,
            original_user_input=user_input,
            subtask=subtask,
            missing_fields=agent_result.get("missing_fields", []),
        )
        return _make_update(
            state=state,
            response_text=response_text,
            session_state=session_state,
            group="personalization",
            subtask=subtask,
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
            missing_fields=agent_result.get("missing_fields", []),
            task_input=user_input,
        )

    if _task_requires_confirmation("personalization", subtask, tool_plan):
        question = response_text
        if not question or "ghi nho" not in _normalize_lookup_text(question):
            question = f"Bạn có muốn tôi xác nhận cập nhật thông tin này không: {user_input.strip()}?"
        session_state = _set_active_pending(
            session_state,
            group="personalization",
            return_mode=return_mode,
            kind="confirmation",
            question=question,
            original_user_input=user_input,
            subtask=subtask,
            tool_plan=tool_plan,
        )
        return _make_update(
            state=state,
            response_text=question,
            session_state=session_state,
            group="personalization",
            subtask=subtask,
            confidence=agent_result.get("confidence", 0.8),
            task_status="needs_confirmation",
            dialogue_action="ask_confirmation",
            task_input=user_input,
        )

    return _make_update(
        state=state,
        response_text=response_text,
        session_state=_ensure_active_task(session_state, group="personalization", return_mode=return_mode, subtask=subtask),
        group="personalization",
        subtask=subtask,
        confidence=agent_result.get("confidence", 0.8),
        task_status="in_progress" if tool_plan else "completed",
        dialogue_action="use_tools" if tool_plan else "respond_only",
        tool_calls=tool_plan,
        task_input=user_input,
    )


def conversation_agent(state: LLMState, runtime) -> dict[str, Any]:
    session_state = _normalize_session_state(state.get("session_state"))
    user_input = state.get("text_input", "")

    if _looks_like_context_reset_request(user_input):
        session_state = _fresh_session_state(session_state.get("profile_cache", {}), mode="conversation")
        return _make_update(
            state=state,
            response_text="Mình đã quên ngữ cảnh cuộc trò chuyện hiện tại. Memory và preference của bạn vẫn được giữ lại, mình sẵn sàng bắt đầu chat mới.",
            session_state=session_state,
            group="conversation",
            subtask="chat",
            confidence=0.99,
            task_status="conversation_active",
            dialogue_action="respond_only",
            extra_metadata={"skip_context_recording": True},
        )

    if _looks_like_end_conversation(user_input):
        session_state["mode"] = "conversation"
        return _make_update(
            state=state,
            response_text="Được rồi, mình sẽ kết thúc cuộc trò chuyện tại đây. Khi cần bạn cứ gọi mình nhé.",
            session_state=session_state,
            group="conversation",
            subtask="chat",
            confidence=0.99,
            task_status="completed",
            dialogue_action="end_conversation",
        )

    session_state["mode"] = "conversation"
    _ensure_conversation_task(session_state)
    agent_result = _normalize_task_agent_result(
        "conversation",
        _run_llm_group_agent({**state, "session_state": session_state}, runtime, "conversation", user_input),
        fallback_subtask="chat",
    )
    response_text = agent_result.get("assistant_text") or "Mình vẫn đang nghe bạn đây."
    return _make_update(
        state=state,
        response_text=response_text,
        session_state=session_state,
        group="conversation",
        subtask="chat",
        confidence=agent_result.get("confidence", 0.8),
        task_status="conversation_active",
        dialogue_action=agent_result.get("dialogue_action", "respond_only"),
    )


def specialist_agent(state: LLMState, runtime) -> dict[str, Any]:
    group = state.get("intent_classification", {}).get("group") or state.get("intent_classification", {}).get("intent", "conversation")
    if group == "media":
        return media_agent(state, runtime)
    if group == "information_query":
        return information_query_agent(state, runtime)
    if group == "productivity":
        return productivity_agent(state, runtime)
    if group == "personalization":
        return personalization_agent(state, runtime)
    return conversation_agent(state, runtime)


def play_audio_agent(state: LLMState, runtime) -> dict[str, Any]:
    return media_agent(state, runtime)


def alarm_agent(state: LLMState, runtime) -> dict[str, Any]:
    return productivity_agent(state, runtime)


def timer_agent(state: LLMState, runtime) -> dict[str, Any]:
    return productivity_agent(state, runtime)


def list_management_agent(state: LLMState, runtime) -> dict[str, Any]:
    return productivity_agent(state, runtime)


def execute_tools(state: LLMState, runtime) -> dict[str, Any]:
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return {"tool_results": state.get("tool_results", [])}

    nfc_tag_id = state.get("nfc_tag_id", "")
    route_group = state.get("route_group") or state.get("intent_classification", {}).get("group", "conversation")
    allowed_tools = set(TASK_GROUPS.get(route_group, {}).get("tools", []))
    aggregated_results = list(state.get("tool_results", []))
    executed_actions = list(state.get("executed_actions", []))
    total_execution_time = 0

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        parameters = tool_call.get("parameters", {})
        log_kv(
            logger,
            logging.INFO,
            "tool_execution_started",
            route_group=route_group,
            tool_name=tool_name,
            parameters=parameters,
            nfc_tag_id=nfc_tag_id,
        )
        start_time = time.time()
        if allowed_tools and tool_name not in allowed_tools:
            result = {
                "status": "error",
                "message": f"Tool '{tool_name}' không thuộc domain '{route_group}'",
            }
        else:
            result = execute_tool(tool_name=tool_name, parameters=parameters, nfc_tag_id=nfc_tag_id)
        execution_time = int((time.time() - start_time) * 1000)
        total_execution_time += execution_time
        log_kv(
            logger,
            logging.INFO,
            "tool_execution_completed",
            route_group=route_group,
            tool_name=tool_name,
            parameters=parameters,
            status=result.get("status"),
            message=result.get("message"),
            error_code=result.get("error_code"),
            user_hint=result.get("user_hint"),
            execution_time_ms=execution_time,
            result_payload=result.get("device_payload") or result,
        )
        aggregated_results.append(
            {
                "tool": tool_name,
                "parameters": parameters,
                "result": result,
                "execution_time_ms": execution_time,
            }
        )
        executed_actions.append({"tool": tool_name, "parameters": parameters})

    return {
        "tool_calls": [],
        "tool_results": aggregated_results,
        "executed_actions": executed_actions,
        "processing_latency_ms": state.get("processing_latency_ms", 0) + total_execution_time,
    }


def _handle_media_search_results(state: LLMState, search_result: dict[str, Any]) -> dict[str, Any] | None:
    query = state.get("metadata", {}).get("search_query") or state.get("task_input") or state.get("text_input", "")
    mode = state.get("metadata", {}).get("mode", "audio")
    results = search_result.get("result", {}).get("results", []) or []
    session_state = _normalize_session_state(state.get("session_state"))
    return_mode = state.get("route_return_mode", "conversation")

    if not results:
        question = "Mình chưa tìm thấy nội dung đủ khớp. Bạn muốn nói bài hát hoặc video nào rõ hơn?"
        session_state = _set_active_pending(
            session_state,
            group="media",
            return_mode=return_mode,
            kind="clarification",
            question=question,
            original_user_input=query,
            subtask="play_media",
        )
        return _make_update(
            state=state,
            response_text=question,
            session_state=session_state,
            group="media",
            subtask="play_media",
            confidence=0.6,
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
        )

    scored_results = sorted(
        ((result, _media_candidate_score(query, result)) for result in results),
        key=lambda item: item[1],
        reverse=True,
    )
    top_result, top_score = scored_results[0]
    second_score = scored_results[1][1] if len(scored_results) > 1 else 0.0

    stream_tool = {
        "name": "youtube_stream",
        "parameters": {
            "video_id": top_result.get("video_id"),
            "mode": mode,
        },
    }

    if top_score >= 0.72 or (top_score >= 0.6 and (top_score - second_score) >= 0.12):
        session_state = _clear_active_pending(session_state)
        return _make_update(
            state=state,
            response_text=f"Mình tìm thấy nội dung khá khớp: {top_result.get('title', 'video đầu tiên')}. Mình phát cho bạn ngay.",
            session_state=session_state,
            group="media",
            subtask="play_media",
            confidence=top_score,
            task_status="in_progress",
            dialogue_action="use_tools",
            tool_calls=[stream_tool],
            task_input=query,
        )

    question = f"Tôi nghe không rõ, Ý của bạn có phải là {top_result.get('title', 'video này')} hay một video nào khác?"
    session_state = _set_active_pending(
        session_state,
        group="media",
        return_mode=return_mode,
        kind="confirmation",
        question=question,
        original_user_input=query,
        subtask="play_media",
        tool_plan=[stream_tool],
        context={"candidate": top_result, "mode": mode},
    )
    return _make_update(
        state=state,
        response_text=question,
        session_state=session_state,
        group="media",
        subtask="play_media",
        confidence=top_score,
        task_status="needs_confirmation",
        dialogue_action="ask_confirmation",
    )


def _synthesize_failed_tool_turn(
    state: LLMState,
    runtime,
    *,
    session_state: dict[str, Any],
    route_group: str,
    fallback_message: str,
) -> dict[str, Any] | None:
    llm: LLMWrapper = runtime.context.llm
    context_strings = _build_context_strings(session_state, route_group)
    try:
        synthesis_result = _normalize_tool_synthesis_output(
            route_group,
            llm.synthesize_tool_results(
                group=route_group,
                user_input=state.get("task_input") or state.get("text_input", ""),
                draft_response=state.get("response_text", "") or fallback_message,
                answer_policy={},
                tool_results=state.get("tool_results", []),
                response_preferences=_response_preferences_text(state.get("user_profile", {})),
                task_summary=context_strings["task_summary"],
                task_transcript=context_strings["task_transcript"],
                conversation_summary=context_strings["conversation_summary"],
                conversation_transcript=context_strings["conversation_transcript"],
                session_mode=session_state.get("mode", "conversation"),
            ),
        )
    except Exception as exc:
        logger.warning("tool_failure_synthesis_failed | route_group=%s | error=%s", route_group, exc)
        return None

    response_text = str(synthesis_result.get("assistant_text", "") or "").strip() or fallback_message
    if synthesis_result.get("dialogue_action") == "ask_clarification":
        missing_fields = synthesis_result.get("missing_fields", [])
        session_state = _set_active_pending(
            session_state,
            group=route_group,
            return_mode=state.get("route_return_mode", "conversation"),
            kind="clarification",
            question=response_text,
            original_user_input=state.get("task_input") or state.get("text_input", ""),
            subtask=state.get("metadata", {}).get("subtask", route_group),
            missing_fields=missing_fields,
        )
        return _make_update(
            state=state,
            response_text=response_text,
            session_state=session_state,
            group=route_group,
            subtask=state.get("metadata", {}).get("subtask", route_group),
            confidence=synthesis_result.get("confidence", state.get("metadata", {}).get("confidence", 0.7)),
            task_status="needs_clarification",
            dialogue_action="ask_clarification",
            missing_fields=missing_fields,
        )

    return _make_update(
        state=state,
        response_text=response_text,
        session_state=session_state,
        group=route_group,
        subtask=state.get("metadata", {}).get("subtask", route_group),
        confidence=synthesis_result.get("confidence", state.get("metadata", {}).get("confidence", 0.7)),
        task_status="failed",
        dialogue_action="respond_only",
    )


def handle_tool_results(state: LLMState, runtime) -> dict[str, Any]:
    llm: LLMWrapper = runtime.context.llm
    tool_results = state.get("tool_results", [])
    if not tool_results:
        return {}

    session_state = _normalize_session_state(state.get("session_state"))
    session_state = _sync_profile_cache_from_tool_results(session_state, tool_results)
    last_result = tool_results[-1]
    route_group = state.get("route_group") or state.get("metadata", {}).get("group", "conversation")
    metadata_subtask = str(state.get("metadata", {}).get("subtask", "") or "")
    verification_result: dict[str, Any] | None = None

    if route_group == "media" and last_result.get("tool") == "youtube_search":
        media_followup = _handle_media_search_results({**state, "session_state": session_state}, last_result)
        if media_followup is not None:
            return media_followup

    failures = [item for item in tool_results if item.get("result", {}).get("status") != "success"]
    if failures and len(failures) == len(tool_results):
        message = failures[-1].get("result", {}).get("message") or "Có lỗi xảy ra khi thực hiện yêu cầu."
        if route_group == "productivity":
            synthesized_failure = _synthesize_failed_tool_turn(
                state,
                runtime,
                session_state=session_state,
                route_group=route_group,
                fallback_message=message,
            )
            if synthesized_failure is not None:
                return synthesized_failure
        return _make_update(
            state=state,
            response_text=message,
            session_state=session_state,
            group=route_group,
            subtask=state.get("metadata", {}).get("subtask", route_group),
            confidence=state.get("metadata", {}).get("confidence", 0.5),
            task_status="failed",
            dialogue_action="respond_only",
        )

    if route_group == "information_query":
        context_strings = _build_context_strings(session_state, route_group)
        verification_result = {
            "decision": "answer",
            "assistant_text": "",
            "reason": "default_answer",
            "confidence": 0.5,
            "missing_fields": [],
            "refined_query": "",
            "answer_style": "balanced",
            "follow_up_mode": "none",
            "should_strip_follow_up_offer": True,
            "answer_outline": [],
        }
        try:
            verification_result = llm.verify_information_result(
                user_input=state.get("task_input") or state.get("text_input", ""),
                draft_response=state.get("response_text", ""),
                tool_results=tool_results,
                response_preferences=_response_preferences_text(state.get("user_profile", {})),
                task_summary=context_strings["task_summary"],
                task_transcript=context_strings["task_transcript"],
                conversation_summary=context_strings["conversation_summary"],
                conversation_transcript=context_strings["conversation_transcript"],
                session_mode=session_state.get("mode", "conversation"),
                current_time=state.get("current_time") or get_current_time_string(),
            )
        except Exception as exc:
            logger.warning("information_result_verifier_failed | error=%s", exc)

        log_kv(
            logger,
            logging.INFO,
            "information_result_verified",
            user_input=state.get("task_input") or state.get("text_input", ""),
            decision=verification_result.get("decision"),
            reason=verification_result.get("reason", ""),
            confidence=verification_result.get("confidence", 0.5),
            refined_query=verification_result.get("refined_query", ""),
            answer_style=verification_result.get("answer_style", "balanced"),
            follow_up_mode=verification_result.get("follow_up_mode", "none"),
            missing_fields=verification_result.get("missing_fields", []),
        )

        if verification_result.get("decision") == "clarify":
            question = (
                verification_result.get("assistant_text")
                or str(last_result.get("result", {}).get("ambiguity_hint", {}).get("question", "") or "")
                or "Bạn muốn mình làm rõ thêm thông tin nào?"
            )
            missing_fields = verification_result.get("missing_fields", [])
            options = []
            ambiguity_hint = last_result.get("result", {}).get("ambiguity_hint")
            if isinstance(ambiguity_hint, dict):
                options = ambiguity_hint.get("options", [])
                if not missing_fields:
                    missing_fields = ambiguity_hint.get("missing_fields", [])
            session_state = _set_active_pending(
                session_state,
                group="information_query",
                return_mode=state.get("route_return_mode", "conversation"),
                kind="clarification",
                question=question,
                original_user_input=state.get("task_input") or state.get("text_input", ""),
                subtask="search_information",
                missing_fields=missing_fields,
                context={"options": options},
            )
            return _make_update(
                state=state,
                response_text=question,
                session_state=session_state,
                group="information_query",
                subtask="search_information",
                confidence=verification_result.get("confidence", 0.75),
                task_status="needs_clarification",
                dialogue_action="ask_clarification",
                missing_fields=missing_fields,
            )

        refined_query = str(verification_result.get("refined_query", "") or "").strip()
        original_query = " ".join(str(state.get("task_input") or state.get("text_input", "") or "").split()).strip()
        if verification_result.get("decision") == "refine_search" and refined_query and refined_query != original_query:
            return _make_update(
                state=state,
                response_text="Mình tìm lại theo hướng phù hợp hơn.",
                session_state=_ensure_active_task(
                    session_state,
                    group="information_query",
                    return_mode=state.get("route_return_mode", "conversation"),
                    subtask="search_information",
                ),
                group="information_query",
                subtask="search_information",
                confidence=verification_result.get("confidence", 0.8),
                task_status="in_progress",
                dialogue_action="use_tools",
                tool_calls=[{"name": "web_search", "parameters": {"query": refined_query, "max_results": 5}}],
                task_input=original_query,
                extra_metadata={"refined_query": refined_query, "verify_reason": verification_result.get("reason", "")},
            )

    if route_group == "personalization":
        reset_request = _extract_personal_data_reset_request(
            state.get("task_input") or state.get("text_input", "")
        )
        only_read_tools_ran = all(
            item.get("tool") in {"get_user_profile", "get_memory"}
            for item in tool_results
        )
        if reset_request and metadata_subtask in {"profile.read", "memory.read"} and only_read_tools_ran:
            session_state = _set_active_pending(
                session_state,
                group="personalization",
                return_mode=state.get("route_return_mode", "conversation"),
                kind="confirmation",
                question=reset_request["question"],
                original_user_input=state.get("task_input") or state.get("text_input", ""),
                subtask=reset_request["subtask"],
                tool_plan=reset_request["tool_plan"],
                context={"source": "tool_result_guard"},
            )
            return _make_update(
                state=state,
                response_text=reset_request["question"],
                session_state=session_state,
                group="personalization",
                subtask=reset_request["subtask"],
                confidence=0.95,
                task_status="needs_confirmation",
                dialogue_action="ask_confirmation",
            )

        if metadata_subtask == "personal_data.reset" and not failures:
            return _make_update(
                state=state,
                response_text="Mình đã xóa thông tin cá nhân hóa đã lưu của bạn.",
                session_state=session_state,
                group="personalization",
                subtask="personal_data.reset",
                confidence=0.98,
                task_status="completed",
                dialogue_action="respond_only",
            )

        deterministic_response = _personalization_success_response_from_tools(state, tool_results)
        if deterministic_response:
            return _make_update(
                state=state,
                response_text=deterministic_response,
                session_state=session_state,
                group="personalization",
                subtask=state.get("metadata", {}).get("subtask", route_group),
                confidence=state.get("metadata", {}).get("confidence", 0.98),
                task_status="completed",
                dialogue_action="respond_only",
            )

    context_strings = _build_context_strings(session_state, route_group)
    answer_policy = (
        {
            "decision": verification_result.get("decision"),
            "answer_style": verification_result.get("answer_style", "balanced"),
            "follow_up_mode": verification_result.get("follow_up_mode", "none"),
            "should_strip_follow_up_offer": verification_result.get("should_strip_follow_up_offer", True),
            "answer_outline": verification_result.get("answer_outline", []),
            "reason": verification_result.get("reason", ""),
        }
        if route_group == "information_query" and verification_result
        else {}
    )
    synthesis_result = _normalize_tool_synthesis_output(
        route_group,
        llm.synthesize_tool_results(
            group=route_group,
            user_input=state.get("task_input") or state.get("text_input", ""),
            draft_response=(
                verification_result.get("assistant_text", "")
                if route_group == "information_query"
                else state.get("response_text", "")
            ),
            answer_policy=answer_policy,
            tool_results=tool_results,
            response_preferences=_response_preferences_text(state.get("user_profile", {})),
            task_summary=context_strings["task_summary"],
            task_transcript=context_strings["task_transcript"],
            conversation_summary=context_strings["conversation_summary"],
            conversation_transcript=context_strings["conversation_transcript"],
            session_mode=session_state.get("mode", "conversation"),
        ),
    )

    response_text = synthesis_result.get("assistant_text") or state.get("response_text", "")
    if (
        route_group == "information_query"
        and verification_result
        and verification_result.get("decision") == "answer"
        and verification_result.get("should_strip_follow_up_offer", True)
        and _looks_like_follow_up_offer(response_text)
    ):
        response_text = _trim_trailing_follow_up_offer(response_text)
        synthesis_result["assistant_text"] = response_text
    if (
        route_group == "information_query"
        and verification_result
        and verification_result.get("decision") == "answer"
        and synthesis_result.get("dialogue_action") == "ask_clarification"
        and (
            _looks_like_follow_up_offer(response_text)
            or not synthesis_result.get("missing_fields")
        )
    ):
        synthesis_result["dialogue_action"] = "respond_only"
        synthesis_result["missing_fields"] = []
        response_text = _trim_trailing_follow_up_offer(response_text)
        synthesis_result["assistant_text"] = response_text
    if synthesis_result.get("dialogue_action") == "ask_clarification":
        session_state = _set_active_pending(
            session_state,
            group=route_group,
            return_mode=state.get("route_return_mode", "conversation"),
            kind="clarification",
            question=response_text,
            original_user_input=state.get("task_input") or state.get("text_input", ""),
            subtask=state.get("metadata", {}).get("subtask", route_group),
            missing_fields=synthesis_result.get("missing_fields", []),
        )
        task_status = "needs_clarification"
    else:
        task_status = "completed"

    return _make_update(
        state=state,
        response_text=response_text,
        session_state=session_state,
        group=route_group,
        subtask=state.get("metadata", {}).get("subtask", route_group),
        confidence=synthesis_result.get("confidence", state.get("metadata", {}).get("confidence", 0.8)),
        task_status=task_status,
        dialogue_action=synthesis_result.get("dialogue_action", "respond_only"),
        missing_fields=synthesis_result.get("missing_fields", []),
    )


def format_output(state: LLMState, runtime) -> dict[str, Any]:
    response_text = state.get("response_text", "")
    metadata = state.get("metadata", {}) if isinstance(state.get("metadata"), dict) else {}
    session_state = _normalize_session_state(state.get("session_state"))
    tool_results = state.get("tool_results", [])
    executed_actions = state.get("executed_actions", [])
    current_time = state.get("current_time") or get_current_time_string()

    if not metadata.get("skip_context_recording"):
        session_state = _record_turn_in_context(
            session_state,
            user_input=state.get("text_input", ""),
            assistant_text=response_text,
            group=metadata.get("group", state.get("route_group", "conversation")),
            subtask=metadata.get("subtask", ""),
            return_mode=metadata.get("return_mode", state.get("route_return_mode", "conversation")),
            task_status=metadata.get("task_status", "completed"),
        )

    active_task = _normalize_task_context(session_state.get("active_task"))
    pending = active_task.get("pending") if active_task else None

    commands = []
    tool_outputs = []
    for item in tool_results:
        result = item.get("result", {})
        payload = result.get("device_payload")
        if payload:
            commands.append(payload)
        tool_output = {
            "tool": item.get("tool"),
            "status": result.get("status", "error"),
            "message": result.get("message", ""),
            "execution_time_ms": item.get("execution_time_ms", 0),
        }
        if payload:
            tool_output["payload"] = payload
        tool_outputs.append(tool_output)

    expect_user_input = bool(pending) or session_state.get("mode") == "conversation"
    final_output = {
        "tts_text": response_text,
        "status": metadata.get("task_status", "completed"),
        "route": {
            "group": metadata.get("group", state.get("route_group", "conversation")),
            "subtask": metadata.get("subtask", "unknown"),
            "return_mode": metadata.get("return_mode", state.get("route_return_mode", "conversation")),
        },
        "dialog": {
            "mode": session_state.get("mode", "conversation"),
            "expect_user_input": expect_user_input,
            "pending_kind": pending.get("kind") if pending else None,
            "pending_question": pending.get("question") if pending else None,
        },
        "session_state": session_state,
        "actions": executed_actions,
        "tool_outputs": tool_outputs,
        "commands": commands,
        "edge_payload": {
            "version": EDGE_PAYLOAD_VERSION,
            "commands": commands,
        },
        "metadata": {
            "intent": metadata.get("intent", metadata.get("group", "conversation")),
            "group": metadata.get("group", state.get("route_group", "conversation")),
            "subtask": metadata.get("subtask", "unknown"),
            "confidence": metadata.get("confidence", 0.8),
            "task_status": metadata.get("task_status", "completed"),
            "timestamp": current_time,
            "user_id": state.get("user_id", ""),
            "nfc_tag_id": state.get("nfc_tag_id", ""),
            "total_latency_ms": state.get("processing_latency_ms", 0),
            "tool_count": len(executed_actions),
            "edge_command_count": len(commands),
        },
    }
    return {"final_output": final_output}


def log_interaction(state: LLMState, runtime) -> dict[str, Any]:
    user_id = state.get("user_id", "")
    if not user_id:
        return {}

    try:
        requests.post(
            f"{BACKEND_API_URL}/api/logs",
            json={
                "user_id": user_id,
                "input_text": state.get("text_input", ""),
                "output_text": state.get("response_text", ""),
                "intent": state.get("metadata", {}).get("group", state.get("route_group", "conversation")),
                "tools_called": [action.get("tool") for action in state.get("executed_actions", [])],
                "latency_ms": state.get("processing_latency_ms", 0),
            },
            timeout=5,
        )
    except Exception:
        pass
    return {}


def route_after_specialist(state: LLMState) -> Literal["execute_tools", "format_output"]:
    if state.get("tool_calls"):
        return "execute_tools"
    return "format_output"


def route_after_task_agent(state: LLMState) -> Literal["execute_tools", "format_output"]:
    return route_after_specialist(state)


def route_after_tools(state: LLMState) -> Literal["handle_tool_results", "format_output"]:
    if state.get("tool_results"):
        return "handle_tool_results"
    return "format_output"


def route_after_handle_tool_results(state: LLMState) -> Literal["execute_tools", "format_output"]:
    if state.get("tool_calls"):
        return "execute_tools"
    return "format_output"

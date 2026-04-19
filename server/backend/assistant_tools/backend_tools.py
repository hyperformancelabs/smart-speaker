from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from assistant_tools.common import backend_json, backend_request, parse_json_string_if_possible


def _normalize_lookup_value(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _parse_iso_datetime_for_lookup(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw_value = " ".join(str(value or "").split()).strip()
    if not raw_value:
        return None

    normalized_value = raw_value.replace("Z", "+00:00")
    for candidate in (normalized_value, normalized_value.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _normalize_iso_datetime_for_lookup(value: Any) -> str:
    parsed = _parse_iso_datetime_for_lookup(value)
    if parsed is not None:
        return parsed.isoformat()
    return " ".join(str(value or "").split()).strip().replace(" ", "T")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_duration_seconds_for_lookup(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return 0

    normalized = _normalize_lookup_value(value)
    if not normalized:
        return 0
    if normalized.isdigit():
        return int(normalized)

    total_seconds = 0
    patterns = (
        (r"(\d+)\s*(?:d|day|days|ngay|ngày)", 86400),
        (r"(\d+)\s*(?:h|hr|hrs|hour|hours|gio|giờ)", 3600),
        (r"(\d+)\s*(?:m|min|mins|minute|minutes|phut|phút)", 60),
        (r"(\d+)\s*(?:s|sec|secs|second|seconds|giay|giây)", 1),
    )
    for pattern, multiplier in patterns:
        matches = re.findall(pattern, normalized)
        for match in matches:
            total_seconds += int(match) * multiplier
    return total_seconds


def _coerce_datetime_to_utc(value: Any) -> datetime | None:
    parsed = _parse_iso_datetime_for_lookup(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _timer_record_is_effectively_active(timer: dict[str, Any], *, now: datetime | None = None) -> bool:
    if not bool(timer.get("active", True)):
        return False

    started_at = _coerce_datetime_to_utc(timer.get("started_at"))
    duration_seconds = int(timer.get("duration_seconds") or 0)
    if started_at is None or duration_seconds <= 0:
        return True

    effective_now = now or _now_utc()
    return (started_at.timestamp() + duration_seconds) > effective_now.timestamp()


def _infer_alarm_schedule_type(
    *,
    schedule_type: str | None = None,
    time: str | None = None,
    scheduled_for: str | None = None,
    offset_seconds: int | None = None,
) -> str | None:
    normalized_schedule_type = _normalize_lookup_value(schedule_type)
    if normalized_schedule_type in {"time", "datetime", "relative"}:
        return normalized_schedule_type
    if scheduled_for:
        return "datetime"
    if offset_seconds is not None:
        return "relative"
    if time:
        return "time"
    return None


def _build_productivity_error_metadata(raw_message: str) -> dict[str, Any]:
    normalized = _normalize_lookup_value(raw_message)
    if not normalized:
        return {
            "error_code": "productivity_internal_error",
            "message_detail": "đã xảy ra lỗi nội bộ",
            "user_hint": "Bạn thử lại một lần nữa nhé.",
        }
    if "user not found" in normalized:
        return {
            "error_code": "user_not_found",
            "message_detail": "chưa có hồ sơ người dùng cho thẻ NFC hiện tại",
            "user_hint": "Bạn hãy đăng ký người dùng cho thẻ NFC này trước.",
        }
    if "internal server error" in normalized or normalized == "server error":
        return {
            "error_code": "backend_internal_error",
            "message_detail": "máy chủ database đang lỗi nội bộ",
            "user_hint": "Bạn thử lại sau ít phút nữa nhé.",
        }
    if "invalid duration" in normalized:
        return {
            "error_code": "timer_invalid_duration",
            "message_detail": "thời lượng timer chưa hợp lệ",
            "user_hint": "Bạn hãy nói rõ thời lượng, ví dụ 10 phút hoặc 30 giây.",
        }
    if "invalid scheduled_for datetime" in normalized:
        return {
            "error_code": "alarm_invalid_datetime",
            "message_detail": "thời điểm báo thức chưa đúng định dạng ngày giờ",
            "user_hint": "Bạn hãy nói rõ ngày và giờ, ví dụ 6 giờ sáng ngày 21.",
        }
    if "invalid time format" in normalized:
        return {
            "error_code": "alarm_invalid_time",
            "message_detail": "giờ báo thức chưa hợp lệ",
            "user_hint": "Bạn hãy nói giờ theo dạng quen thuộc như 6 giờ sáng hoặc 18 giờ 30.",
        }
    if "missing or invalid schedule_type" in normalized or "missing alarm schedule" in normalized:
        return {
            "error_code": "alarm_missing_schedule",
            "message_detail": "thiếu thời điểm báo thức",
            "user_hint": "Bạn hãy nói rõ báo thức vào lúc nào hoặc sau bao lâu.",
        }
    if "invalid offset_seconds" in normalized:
        return {
            "error_code": "alarm_invalid_offset",
            "message_detail": "khoảng thời gian báo thức chưa hợp lệ",
            "user_hint": "Bạn hãy nói rõ sau bao lâu, ví dụ sau 10 phút.",
        }
    if "alarm already exists" in normalized:
        return {
            "error_code": "alarm_already_exists",
            "message_detail": "đã có báo thức tương tự rồi",
            "user_hint": "Bạn có thể đổi giờ hoặc yêu cầu mình kiểm tra các báo thức hiện có.",
        }
    if "timer already exists" in normalized:
        return {
            "error_code": "timer_already_exists",
            "message_detail": "đã có timer tương tự đang chạy rồi",
            "user_hint": "Bạn có thể đổi thời lượng hoặc yêu cầu mình kiểm tra các timer đang chạy.",
        }
    if "alarm not found" in normalized:
        return {
            "error_code": "alarm_not_found",
            "message_detail": "không tìm thấy báo thức phù hợp",
            "user_hint": "Bạn hãy nói rõ giờ hoặc nhãn của báo thức cần thao tác.",
        }
    if "timer not found" in normalized:
        return {
            "error_code": "timer_not_found",
            "message_detail": "không tìm thấy timer phù hợp",
            "user_hint": "Bạn hãy nói rõ tên timer hoặc kiểm tra timer nào đang chạy.",
        }
    if "no active timers found" in normalized:
        return {
            "error_code": "timer_none_active",
            "message_detail": "hiện không có timer nào đang chạy",
            "user_hint": "Bạn có thể yêu cầu mình bật timer mới.",
        }
    if "multiple active timers found" in normalized or "multiple timers match" in normalized:
        return {
            "error_code": "timer_multiple_matches",
            "message_detail": "có nhiều timer đang chạy, bạn cần nói rõ hơn",
            "user_hint": "Bạn hãy nói tên timer hoặc thời lượng cụ thể.",
        }
    if "multiple alarms match" in normalized:
        return {
            "error_code": "alarm_multiple_matches",
            "message_detail": "có nhiều báo thức khớp, bạn cần nói rõ hơn",
            "user_hint": "Bạn hãy nói rõ giờ hoặc nhãn của báo thức.",
        }
    if raw_message.isupper():
        raw_message = raw_message.lower()
    elif raw_message[:1].isupper():
        raw_message = raw_message[:1].lower() + raw_message[1:]
    return {
        "error_code": "productivity_backend_error",
        "message_detail": raw_message,
        "user_hint": "",
    }


def _productivity_conflict(
    action: str,
    reason: str,
    *,
    error_code: str,
    user_hint: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "status": "error",
        "message": f"Không thể {action} vì {reason}.",
        "error_code": error_code,
    }
    if user_hint:
        result["user_hint"] = user_hint
    if extra:
        result.update(extra)
    return result


def _productivity_error(action: str, exc: Exception, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_message = " ".join(str(exc or "").split()).strip().rstrip(".")
    metadata = _build_productivity_error_metadata(raw_message)
    result = {
        "status": "error",
        "message": f"Không thể {action} vì {metadata['message_detail']}.",
        "error_code": metadata["error_code"],
        "raw_message": raw_message,
    }
    if metadata.get("user_hint"):
        result["user_hint"] = metadata["user_hint"]
    if extra:
        result.update(extra)
    return result


def _get_lists_data(nfc_tag_id: str) -> dict[str, Any]:
    return backend_json("GET", f"/api/users/{nfc_tag_id}/lists")


def _get_alarms_data(nfc_tag_id: str) -> dict[str, Any]:
    return backend_json("GET", f"/api/users/{nfc_tag_id}/alarms")


def _get_timers_data(nfc_tag_id: str) -> dict[str, Any]:
    return backend_json("GET", f"/api/users/{nfc_tag_id}/timers")


def _find_list_record(lists_data: dict[str, Any], list_name: str) -> dict[str, Any] | None:
    for current_list in lists_data.get("lists", []):
        if _normalize_lookup_value(current_list.get("list_name")) == _normalize_lookup_value(list_name):
            return current_list
    return None


def _find_timer_record(
    timers_data: dict[str, Any],
    timer_id: str | None = None,
    label: str | None = None,
) -> dict[str, Any] | None:
    for current_timer in timers_data.get("timers", []):
        if timer_id and current_timer.get("timer_id") == timer_id:
            return current_timer
        if label and _normalize_lookup_value(current_timer.get("label")) == _normalize_lookup_value(label):
            return current_timer
    return None


def _find_alarm_record(
    alarms_data: dict[str, Any],
    alarm_id: str | None = None,
    label: str | None = None,
    time: str | None = None,
) -> dict[str, Any] | None:
    for current_alarm in alarms_data.get("alarms", []):
        if alarm_id and current_alarm.get("alarm_id") == alarm_id:
            return current_alarm
        if label and _normalize_lookup_value(current_alarm.get("label")) == _normalize_lookup_value(label):
            return current_alarm
        if time and str(current_alarm.get("time") or "").strip() == str(time or "").strip():
            return current_alarm
    return None


def _find_duplicate_alarm_records(
    alarms_data: dict[str, Any],
    *,
    schedule_type: str | None = None,
    time: str | None = None,
    repeat: str | None = None,
    scheduled_for: str | None = None,
) -> list[dict[str, Any]]:
    normalized_schedule_type = _normalize_lookup_value(schedule_type)
    normalized_repeat = " ".join(str(repeat or "once").split()).strip().lower() or "once"
    alarms = [
        alarm
        for alarm in alarms_data.get("alarms", [])
        if bool(alarm.get("enabled", True))
    ]

    if normalized_schedule_type == "time" and time:
        normalized_time = str(time or "").strip()
        return [
            alarm
            for alarm in alarms
            if _normalize_lookup_value(alarm.get("schedule_type")) == "time"
            and str(alarm.get("time") or "").strip() == normalized_time
            and _normalize_lookup_value(alarm.get("repeat") or "once") == normalized_repeat
        ]

    if normalized_schedule_type == "datetime" and scheduled_for:
        normalized_datetime = _normalize_iso_datetime_for_lookup(scheduled_for)
        if not normalized_datetime:
            return []
        return [
            alarm
            for alarm in alarms
            if _normalize_lookup_value(alarm.get("schedule_type")) == "datetime"
            and _normalize_iso_datetime_for_lookup(alarm.get("scheduled_for")) == normalized_datetime
            and _normalize_lookup_value(alarm.get("repeat") or "once") == normalized_repeat
        ]

    return []


def _find_duplicate_timer_records(
    timers_data: dict[str, Any],
    *,
    label: str | None = None,
    duration_seconds: int | None = None,
) -> list[dict[str, Any]]:
    normalized_label = _normalize_lookup_value(label)
    if not normalized_label or not duration_seconds or duration_seconds <= 0:
        return []
    return [
        timer
        for timer in timers_data.get("timers", [])
        if _timer_record_is_effectively_active(timer)
        if _normalize_lookup_value(timer.get("label")) == normalized_label
        and int(timer.get("duration_seconds") or 0) == int(duration_seconds)
    ]


def _resolve_timer_record(
    nfc_tag_id: str,
    *,
    timer_id: str | None = None,
    label: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    timers_data = _get_timers_data(nfc_tag_id)
    timers = [
        current_timer
        for current_timer in timers_data.get("timers", [])
        if _timer_record_is_effectively_active(current_timer)
    ]
    if not timers:
        return None, "Hiện không có timer nào đang chạy"

    if timer_id:
        timer = _find_timer_record({"timers": timers}, timer_id=timer_id)
        return (timer, None) if timer else (None, "Không tìm thấy timer phù hợp")

    if label:
        matches = [
            current_timer
            for current_timer in timers
            if _normalize_lookup_value(current_timer.get("label")) == _normalize_lookup_value(label)
        ]
        if len(matches) == 1:
            return matches[0], None
        if not matches:
            return None, f"Không tìm thấy timer '{label}'"
        return None, f"Có nhiều timer khớp với '{label}', bạn cần nói rõ hơn"

    if len(timers) == 1:
        return timers[0], None
    return None, "Có nhiều timer đang chạy, bạn cần nói rõ hơn"


def _resolve_alarm_record(
    nfc_tag_id: str,
    *,
    alarm_id: str | None = None,
    label: str | None = None,
    time: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    alarms_data = _get_alarms_data(nfc_tag_id)
    alarms = alarms_data.get("alarms", [])
    if not alarms:
        return None, "Hiện không có báo thức nào"

    if alarm_id:
        alarm = _find_alarm_record(alarms_data, alarm_id=alarm_id)
        return (alarm, None) if alarm else (None, "Không tìm thấy báo thức phù hợp")

    matches = alarms
    if label:
        matches = [
            current_alarm
            for current_alarm in matches
            if _normalize_lookup_value(current_alarm.get("label")) == _normalize_lookup_value(label)
        ]
    if time:
        matches = [
            current_alarm
            for current_alarm in matches
            if str(current_alarm.get("time") or "").strip() == str(time or "").strip()
        ]

    if label or time:
        if len(matches) == 1:
            return matches[0], None
        if not matches:
            return None, "Không tìm thấy báo thức phù hợp"
        return None, "Có nhiều báo thức khớp, bạn cần nói rõ thời gian hoặc nhãn"

    if len(alarms) == 1:
        return alarms[0], None
    return None, "Có nhiều báo thức, bạn cần nói rõ thời gian hoặc nhãn"


def create_alarm(
    nfc_tag_id: str,
    label: str | None = None,
    time: str | None = None,
    repeat: str = "once",
    schedule_type: str | None = None,
    scheduled_for: str | None = None,
    offset_seconds: int | None = None,
) -> dict[str, Any]:
    try:
        resolved_label = str(label or "").strip() or "Báo thức"
        payload = {"label": resolved_label, "repeat": repeat}
        if time:
            payload["time"] = time
        if schedule_type:
            payload["schedule_type"] = schedule_type
        if scheduled_for:
            payload["scheduled_for"] = scheduled_for
        if offset_seconds is not None:
            payload["offset_seconds"] = offset_seconds

        inferred_schedule_type = _infer_alarm_schedule_type(
            schedule_type=schedule_type,
            time=time,
            scheduled_for=scheduled_for,
            offset_seconds=offset_seconds,
        )
        if inferred_schedule_type in {"time", "datetime"}:
            existing_matches = _find_duplicate_alarm_records(
                _get_alarms_data(nfc_tag_id),
                schedule_type=inferred_schedule_type,
                time=time,
                repeat=repeat,
                scheduled_for=scheduled_for,
            )
            if existing_matches:
                return _productivity_conflict(
                    "tạo báo thức",
                    "đã có báo thức tương tự đang bật",
                    error_code="alarm_already_exists",
                    user_hint="Bạn có thể đổi giờ hoặc yêu cầu mình kiểm tra các báo thức hiện có.",
                    extra={"existing_matches": existing_matches[:3]},
                )

        data = backend_json("POST", f"/api/users/{nfc_tag_id}/alarms", json_payload=payload)
        return {
            "status": "success",
            "alarm_id": data.get("alarm_id"),
            "label": data.get("label", resolved_label),
            "time": data.get("time", time),
            "repeat": data.get("repeat", repeat),
            "schedule_type": data.get("schedule_type", schedule_type),
            "scheduled_for": data.get("scheduled_for"),
            "offset_seconds": data.get("offset_seconds"),
            "device_payload": {
                "type": "alarm",
                "action": "create",
                "alarm_id": data.get("alarm_id"),
                "label": data.get("label", resolved_label),
                "time": data.get("time", time),
                "repeat": data.get("repeat", repeat),
                "schedule_type": data.get("schedule_type", schedule_type),
                "scheduled_for": data.get("scheduled_for"),
                "offset_seconds": data.get("offset_seconds"),
                "enabled": data.get("enabled", True),
            },
        }
    except Exception as exc:
        return _productivity_error("tạo báo thức", exc)


def update_alarm(
    nfc_tag_id: str,
    alarm_id: str | None = None,
    time: str | None = None,
    label: str | None = None,
    current_time: str | None = None,
    current_label: str | None = None,
    repeat: str | None = None,
    schedule_type: str | None = None,
    scheduled_for: str | None = None,
    offset_seconds: int | None = None,
) -> dict[str, Any]:
    try:
        alarm_record, error_message = _resolve_alarm_record(
            nfc_tag_id,
            alarm_id=alarm_id,
            label=current_label or (label if not alarm_id else None),
            time=current_time or (time if not alarm_id else None),
        )
        if error_message:
            return {"status": "error", "message": error_message}

        update_data = {}
        if time:
            update_data["time"] = time
        if label:
            update_data["label"] = label
        if repeat:
            update_data["repeat"] = repeat
        if schedule_type:
            update_data["schedule_type"] = schedule_type
        if scheduled_for:
            update_data["scheduled_for"] = scheduled_for
        if offset_seconds is not None:
            update_data["offset_seconds"] = offset_seconds
        if not update_data:
            return {"status": "error", "message": "No alarm fields to update"}

        resolved_alarm_id = str(alarm_record.get("alarm_id"))
        data = backend_json("PATCH", f"/api/users/{nfc_tag_id}/alarms/{resolved_alarm_id}", json_payload=update_data)
        return {
            "status": "success",
            "alarm_id": data.get("alarm_id", resolved_alarm_id),
            "updated": True,
            "alarm": data,
            "device_payload": {
                "type": "alarm",
                "action": "update",
                "alarm_id": data.get("alarm_id", resolved_alarm_id),
                "label": data.get("label"),
                "time": data.get("time"),
                "repeat": data.get("repeat"),
                "schedule_type": data.get("schedule_type"),
                "scheduled_for": data.get("scheduled_for"),
                "offset_seconds": data.get("offset_seconds"),
                "enabled": data.get("enabled"),
            },
        }
    except Exception as exc:
        return _productivity_error("cập nhật báo thức", exc)


def delete_alarm(
    nfc_tag_id: str,
    alarm_id: str | None = None,
    label: str | None = None,
    time: str | None = None,
) -> dict[str, Any]:
    try:
        alarm_record, error_message = _resolve_alarm_record(
            nfc_tag_id,
            alarm_id=alarm_id,
            label=label,
            time=time,
        )
        if error_message:
            return {"status": "error", "message": error_message}

        resolved_alarm_id = str(alarm_record.get("alarm_id"))
        backend_request("DELETE", f"/api/users/{nfc_tag_id}/alarms/{resolved_alarm_id}")
        return {
            "status": "success",
            "alarm_id": resolved_alarm_id,
            "deleted": True,
            "device_payload": {
                "type": "alarm",
                "action": "delete",
                "alarm_id": resolved_alarm_id,
            },
        }
    except Exception as exc:
        return _productivity_error("xóa báo thức", exc)


def list_alarms(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = backend_json("GET", f"/api/users/{nfc_tag_id}/alarms")
        alarms = data.get("alarms", [])
        return {"status": "success", "alarms": alarms, "count": len(alarms)}
    except Exception as exc:
        return _productivity_error("liệt kê báo thức", exc)


def start_timer(nfc_tag_id: str, duration: str, label: str = "Timer") -> dict[str, Any]:
    try:
        resolved_label = str(label or "").strip() or "Timer"
        duration_seconds = _parse_duration_seconds_for_lookup(duration)
        if duration_seconds > 0:
            existing_matches = _find_duplicate_timer_records(
                _get_timers_data(nfc_tag_id),
                label=resolved_label,
                duration_seconds=duration_seconds,
            )
            if existing_matches:
                return _productivity_conflict(
                    "bắt đầu timer",
                    "đã có timer tương tự đang chạy",
                    error_code="timer_already_exists",
                    user_hint="Bạn có thể đổi thời lượng hoặc yêu cầu mình kiểm tra các timer đang chạy.",
                    extra={"existing_matches": existing_matches[:3]},
                )

        data = backend_json(
            "POST",
            f"/api/users/{nfc_tag_id}/timers",
            json_payload={"duration": duration, "label": resolved_label},
        )
        return {
            "status": "success",
            "timer_id": data.get("timer_id"),
            "duration": duration,
            "label": data.get("label"),
            "duration_seconds": data.get("duration_seconds"),
            "device_payload": {
                "type": "timer",
                "action": "start",
                "timer_id": data.get("timer_id"),
                "label": data.get("label"),
                "duration_seconds": data.get("duration_seconds"),
                "started_at": data.get("started_at"),
                "active": data.get("active", True),
            },
        }
    except Exception as exc:
        return _productivity_error("bắt đầu timer", exc)


def list_timers(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = _get_timers_data(nfc_tag_id)
        timers = data.get("timers", [])
        return {"status": "success", "timers": timers, "count": len(timers)}
    except Exception as exc:
        return _productivity_error("liệt kê timer", exc)


def update_timer(
    nfc_tag_id: str,
    timer_id: str | None = None,
    duration: str | None = None,
    label: str | None = None,
    current_label: str | None = None,
) -> dict[str, Any]:
    try:
        timer_record, error_message = _resolve_timer_record(
            nfc_tag_id,
            timer_id=timer_id,
            label=current_label or (label if not timer_id else None),
        )
        if error_message:
            return {"status": "error", "message": error_message}

        payload = {}
        if duration:
            payload["duration"] = duration
        if label:
            payload["label"] = label
        if not payload:
            return {"status": "error", "message": "No timer fields to update"}

        resolved_timer_id = str(timer_record.get("timer_id"))
        data = backend_json("PATCH", f"/api/users/{nfc_tag_id}/timers/{resolved_timer_id}", json_payload=payload)
        return {
            "status": "success",
            "timer_id": data.get("timer_id", resolved_timer_id),
            "updated": True,
            "timer": data,
            "device_payload": {
                "type": "timer",
                "action": "update",
                "timer_id": data.get("timer_id", resolved_timer_id),
                "label": data.get("label"),
                "duration_seconds": data.get("duration_seconds"),
                "started_at": data.get("started_at"),
                "active": data.get("active", True),
            },
        }
    except Exception as exc:
        return _productivity_error("cập nhật timer", exc)


def cancel_timer(nfc_tag_id: str, timer_id: str | None = None, label: str | None = None) -> dict[str, Any]:
    try:
        timer_record, error_message = _resolve_timer_record(nfc_tag_id, timer_id=timer_id, label=label)
        if error_message:
            return {"status": "error", "message": error_message}

        resolved_timer_id = str(timer_record.get("timer_id"))
        backend_request("DELETE", f"/api/users/{nfc_tag_id}/timers/{resolved_timer_id}")
        return {
            "status": "success",
            "timer_id": resolved_timer_id,
            "cancelled": True,
            "device_payload": {
                "type": "timer",
                "action": "cancel",
                "timer_id": resolved_timer_id,
            },
        }
    except Exception as exc:
        return _productivity_error("hủy timer", exc)


def create_list(nfc_tag_id: str, list_name: str) -> dict[str, Any]:
    try:
        data = backend_json("POST", f"/api/users/{nfc_tag_id}/lists", json_payload={"list_name": list_name})
        return {"status": "success", "list_id": data.get("list_id"), "list_name": data.get("list_name", list_name)}
    except Exception as exc:
        return _productivity_error("tạo danh sách", exc)


def rename_list(nfc_tag_id: str, list_name: str, new_list_name: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"Không tìm thấy danh sách '{list_name}'"}

        data = backend_json(
            "PATCH",
            f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}",
            json_payload={"list_name": new_list_name},
        )
        return {
            "status": "success",
            "list_id": data.get("list_id"),
            "list_name": new_list_name,
            "updated": True,
        }
    except Exception as exc:
        return _productivity_error("đổi tên danh sách", exc)


def delete_list(nfc_tag_id: str, list_name: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"Không tìm thấy danh sách '{list_name}'"}

        backend_request("DELETE", f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}")
        return {
            "status": "success",
            "list_id": current_list.get("list_id"),
            "list_name": current_list.get("list_name"),
            "deleted": True,
        }
    except Exception as exc:
        return _productivity_error("xóa danh sách", exc)


def add_list_item(nfc_tag_id: str, list_name: str, item: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"Không tìm thấy danh sách '{list_name}'"}

        data = backend_json(
            "POST",
            f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}/items",
            json_payload={"item": item},
        )
        return {
            "status": "success",
            "list_name": list_name,
            "item": data.get("content", item),
            "item_id": data.get("item_id"),
            "added": True,
        }
    except Exception as exc:
        return _productivity_error("thêm mục vào danh sách", exc)


def update_list_item(
    nfc_tag_id: str,
    list_name: str,
    item: str,
    new_item: str | None = None,
    completed: bool | None = None,
) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"Không tìm thấy danh sách '{list_name}'"}

        item_id = None
        for list_item_detail in current_list.get("items", []):
            if list_item_detail.get("content", "").lower() == item.lower():
                item_id = list_item_detail.get("item_id")
                break
        if not item_id:
            return {"status": "error", "message": f"Không tìm thấy mục '{item}' trong danh sách"}

        payload = {}
        if new_item:
            payload["item"] = new_item
        if completed is not None:
            payload["completed"] = bool(completed)

        data = backend_json(
            "PATCH",
            f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}/items/{item_id}",
            json_payload=payload,
        )
        return {
            "status": "success",
            "list_name": list_name,
            "item_id": item_id,
            "item": data.get("content", new_item or item),
            "completed": data.get("completed"),
            "updated": True,
        }
    except Exception as exc:
        return _productivity_error("cập nhật mục trong danh sách", exc)


def remove_list_item(nfc_tag_id: str, list_name: str, item: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"Không tìm thấy danh sách '{list_name}'"}

        item_id = None
        for list_item_detail in current_list.get("items", []):
            if list_item_detail.get("content", "").lower() == item.lower():
                item_id = list_item_detail.get("item_id")
                break
        if not item_id:
            return {"status": "error", "message": f"Không tìm thấy mục '{item}' trong danh sách"}

        backend_request("DELETE", f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}/items/{item_id}")
        return {"status": "success", "list_name": list_name, "item": item, "removed": True}
    except Exception as exc:
        return _productivity_error("xóa mục khỏi danh sách", exc)


def get_lists(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = _get_lists_data(nfc_tag_id)
        return {
            "status": "success",
            "lists": data.get("lists", []),
            "count": len(data.get("lists", [])),
        }
    except Exception as exc:
        return _productivity_error("lấy danh sách", exc)


def list_items(nfc_tag_id: str, list_name: str) -> dict[str, Any]:
    try:
        data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(data, list_name)
        if not current_list:
            return {"status": "error", "message": f"Không tìm thấy danh sách '{list_name}'"}
        items = current_list.get("items", [])
        return {"status": "success", "list_name": list_name, "items": items, "count": len(items)}
    except Exception as exc:
        return _productivity_error("liệt kê mục trong danh sách", exc)


def get_user_profile(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = backend_json("GET", f"/api/users/{nfc_tag_id}")
        return {"status": "success", "profile": data}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to get profile: {str(exc)}"}


def update_user_profile(
    nfc_tag_id: str,
    field: str,
    value: Any,
    replace: bool = False,
) -> dict[str, Any]:
    try:
        parsed_value = parse_json_string_if_possible(value) if isinstance(value, str) else value
        data = backend_json(
            "PATCH",
            f"/api/users/{nfc_tag_id}/update",
            json_payload={"field": field, "value": parsed_value, "replace": bool(replace)},
        )
        return {
            "status": "success",
            "field": field,
            "value": data.get(field, parsed_value),
            "updated": True,
            "profile": data,
            "replace": bool(replace),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to update profile: {str(exc)}"}


def save_memory(nfc_tag_id: str, memory: str) -> dict[str, Any]:
    try:
        data = backend_json("POST", f"/api/users/{nfc_tag_id}/memory", json_payload={"memory": memory})
        return {
            "status": "success",
            "memory": memory,
            "saved": True,
            "all_memories": data.get("memory", []),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to save memory: {str(exc)}"}


def delete_memory(nfc_tag_id: str, memory: str) -> dict[str, Any]:
    try:
        data = backend_json("DELETE", f"/api/users/{nfc_tag_id}/memory", json_payload={"memory": memory})
        return {
            "status": "success",
            "memory": memory,
            "deleted": True,
            "all_memories": data.get("memory", []),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to delete memory: {str(exc)}"}


def get_memory(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = backend_json("GET", f"/api/users/{nfc_tag_id}")
        return {"status": "success", "memories": data.get("memory", [])}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to get memory: {str(exc)}"}

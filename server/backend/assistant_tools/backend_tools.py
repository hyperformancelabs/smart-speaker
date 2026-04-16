from __future__ import annotations

from typing import Any

from assistant_tools.common import backend_json, backend_request, parse_json_string_if_possible


def _get_lists_data(nfc_tag_id: str) -> dict[str, Any]:
    return backend_json("GET", f"/api/users/{nfc_tag_id}/lists")


def _get_timers_data(nfc_tag_id: str) -> dict[str, Any]:
    return backend_json("GET", f"/api/users/{nfc_tag_id}/timers")


def _find_list_record(lists_data: dict[str, Any], list_name: str) -> dict[str, Any] | None:
    for current_list in lists_data.get("lists", []):
        if current_list.get("list_name", "").lower() == list_name.lower():
            return current_list
    return None


def _find_timer_record(timers_data: dict[str, Any], timer_id: str | None = None, label: str | None = None) -> dict[str, Any] | None:
    for current_timer in timers_data.get("timers", []):
        if timer_id and current_timer.get("timer_id") == timer_id:
            return current_timer
        if label and current_timer.get("label", "").lower() == label.lower():
            return current_timer
    return None


def create_alarm(
    nfc_tag_id: str,
    label: str,
    time: str | None = None,
    repeat: str = "once",
    schedule_type: str | None = None,
    scheduled_for: str | None = None,
    offset_seconds: int | None = None,
) -> dict[str, Any]:
    try:
        payload = {"label": label, "repeat": repeat}
        if time:
            payload["time"] = time
        if schedule_type:
            payload["schedule_type"] = schedule_type
        if scheduled_for:
            payload["scheduled_for"] = scheduled_for
        if offset_seconds is not None:
            payload["offset_seconds"] = offset_seconds

        data = backend_json("POST", f"/api/users/{nfc_tag_id}/alarms", json_payload=payload)
        return {
            "status": "success",
            "alarm_id": data.get("alarm_id"),
            "label": data.get("label", label),
            "time": data.get("time", time),
            "repeat": data.get("repeat", repeat),
            "schedule_type": data.get("schedule_type", schedule_type),
            "scheduled_for": data.get("scheduled_for"),
            "offset_seconds": data.get("offset_seconds"),
            "device_payload": {
                "type": "alarm",
                "action": "create",
                "alarm_id": data.get("alarm_id"),
                "label": data.get("label", label),
                "time": data.get("time", time),
                "repeat": data.get("repeat", repeat),
                "schedule_type": data.get("schedule_type", schedule_type),
                "scheduled_for": data.get("scheduled_for"),
                "offset_seconds": data.get("offset_seconds"),
                "enabled": data.get("enabled", True),
            },
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to create alarm: {str(exc)}"}


def update_alarm(
    nfc_tag_id: str,
    alarm_id: str,
    time: str | None = None,
    label: str | None = None,
    repeat: str | None = None,
    schedule_type: str | None = None,
    scheduled_for: str | None = None,
    offset_seconds: int | None = None,
) -> dict[str, Any]:
    try:
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

        data = backend_json("PATCH", f"/api/users/{nfc_tag_id}/alarms/{alarm_id}", json_payload=update_data)
        return {
            "status": "success",
            "alarm_id": data.get("alarm_id", alarm_id),
            "updated": True,
            "alarm": data,
            "device_payload": {
                "type": "alarm",
                "action": "update",
                "alarm_id": data.get("alarm_id", alarm_id),
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
        return {"status": "error", "message": f"Failed to update alarm: {str(exc)}"}


def delete_alarm(nfc_tag_id: str, alarm_id: str) -> dict[str, Any]:
    try:
        backend_request("DELETE", f"/api/users/{nfc_tag_id}/alarms/{alarm_id}")
        return {
            "status": "success",
            "alarm_id": alarm_id,
            "deleted": True,
            "device_payload": {
                "type": "alarm",
                "action": "delete",
                "alarm_id": alarm_id,
            },
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to delete alarm: {str(exc)}"}


def list_alarms(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = backend_json("GET", f"/api/users/{nfc_tag_id}/alarms")
        alarms = data.get("alarms", [])
        return {"status": "success", "alarms": alarms, "count": len(alarms)}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to list alarms: {str(exc)}"}


def start_timer(nfc_tag_id: str, duration: str, label: str = "Timer") -> dict[str, Any]:
    try:
        data = backend_json(
            "POST",
            f"/api/users/{nfc_tag_id}/timers",
            json_payload={"duration": duration, "label": label},
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
        return {"status": "error", "message": f"Failed to start timer: {str(exc)}"}


def list_timers(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = _get_timers_data(nfc_tag_id)
        timers = data.get("timers", [])
        return {"status": "success", "timers": timers, "count": len(timers)}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to list timers: {str(exc)}"}


def update_timer(nfc_tag_id: str, timer_id: str, duration: str | None = None, label: str | None = None) -> dict[str, Any]:
    try:
        payload = {}
        if duration:
            payload["duration"] = duration
        if label:
            payload["label"] = label
        data = backend_json("PATCH", f"/api/users/{nfc_tag_id}/timers/{timer_id}", json_payload=payload)
        return {
            "status": "success",
            "timer_id": data.get("timer_id", timer_id),
            "updated": True,
            "timer": data,
            "device_payload": {
                "type": "timer",
                "action": "update",
                "timer_id": data.get("timer_id", timer_id),
                "label": data.get("label"),
                "duration_seconds": data.get("duration_seconds"),
                "started_at": data.get("started_at"),
                "active": data.get("active", True),
            },
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to update timer: {str(exc)}"}


def cancel_timer(nfc_tag_id: str, timer_id: str) -> dict[str, Any]:
    try:
        backend_request("DELETE", f"/api/users/{nfc_tag_id}/timers/{timer_id}")
        return {
            "status": "success",
            "timer_id": timer_id,
            "cancelled": True,
            "device_payload": {
                "type": "timer",
                "action": "cancel",
                "timer_id": timer_id,
            },
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to cancel timer: {str(exc)}"}


def create_list(nfc_tag_id: str, list_name: str) -> dict[str, Any]:
    try:
        data = backend_json("POST", f"/api/users/{nfc_tag_id}/lists", json_payload={"list_name": list_name})
        return {"status": "success", "list_id": data.get("list_id"), "list_name": data.get("list_name", list_name)}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to create list: {str(exc)}"}


def rename_list(nfc_tag_id: str, list_name: str, new_list_name: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"List '{list_name}' not found"}

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
        return {"status": "error", "message": f"Failed to rename list: {str(exc)}"}


def delete_list(nfc_tag_id: str, list_name: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"List '{list_name}' not found"}

        backend_request("DELETE", f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}")
        return {
            "status": "success",
            "list_id": current_list.get("list_id"),
            "list_name": current_list.get("list_name"),
            "deleted": True,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to delete list: {str(exc)}"}


def add_list_item(nfc_tag_id: str, list_name: str, item: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"List '{list_name}' not found"}

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
        return {"status": "error", "message": f"Failed to add item: {str(exc)}"}


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
            return {"status": "error", "message": f"List '{list_name}' not found"}

        item_id = None
        for list_item_detail in current_list.get("items", []):
            if list_item_detail.get("content", "").lower() == item.lower():
                item_id = list_item_detail.get("item_id")
                break
        if not item_id:
            return {"status": "error", "message": f"Item '{item}' not found in list"}

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
        return {"status": "error", "message": f"Failed to update item: {str(exc)}"}


def remove_list_item(nfc_tag_id: str, list_name: str, item: str) -> dict[str, Any]:
    try:
        lists_data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(lists_data, list_name)
        if not current_list:
            return {"status": "error", "message": f"List '{list_name}' not found"}

        item_id = None
        for list_item_detail in current_list.get("items", []):
            if list_item_detail.get("content", "").lower() == item.lower():
                item_id = list_item_detail.get("item_id")
                break
        if not item_id:
            return {"status": "error", "message": f"Item '{item}' not found in list"}

        backend_request("DELETE", f"/api/users/{nfc_tag_id}/lists/{current_list.get('list_id')}/items/{item_id}")
        return {"status": "success", "list_name": list_name, "item": item, "removed": True}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to remove item: {str(exc)}"}


def get_lists(nfc_tag_id: str) -> dict[str, Any]:
    try:
        data = _get_lists_data(nfc_tag_id)
        return {
            "status": "success",
            "lists": data.get("lists", []),
            "count": len(data.get("lists", [])),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to get lists: {str(exc)}"}


def list_items(nfc_tag_id: str, list_name: str) -> dict[str, Any]:
    try:
        data = _get_lists_data(nfc_tag_id)
        current_list = _find_list_record(data, list_name)
        items = current_list.get("items", []) if current_list else []
        return {"status": "success", "list_name": list_name, "items": items, "count": len(items)}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to list items: {str(exc)}"}


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

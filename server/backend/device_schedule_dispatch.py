from __future__ import annotations

import json
from typing import Any

import websocket

from device_endpoint_store import DeviceEndpoint, device_endpoint_store


def build_schedule_sync_request(*, nfc_tag_id: str, reason: str) -> dict[str, Any]:
    return {
        "type": "schedule_sync_request",
        "nfc_tag_id": str(nfc_tag_id or "").strip(),
        "reason": str(reason or "schedule_changed").strip() or "schedule_changed",
    }


def send_device_json_message(
    endpoint: DeviceEndpoint,
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 2.5,
) -> None:
    ws = websocket.create_connection(endpoint.websocket_url, timeout=timeout_seconds)
    try:
        ws.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    finally:
        ws.close()


def notify_device_schedule_sync(*, nfc_tag_id: str, reason: str) -> dict[str, Any]:
    normalized_nfc_tag_id = str(nfc_tag_id or "").strip()
    if not normalized_nfc_tag_id:
        raise ValueError("nfc_tag_id is required")

    endpoint = device_endpoint_store.get_by_nfc_tag_id(normalized_nfc_tag_id)
    if endpoint is None:
        return {
            "status": "no_endpoint",
            "nfc_tag_id": normalized_nfc_tag_id,
            "reason": reason,
        }

    payload = build_schedule_sync_request(
        nfc_tag_id=normalized_nfc_tag_id,
        reason=reason,
    )
    send_device_json_message(endpoint, payload)
    return {
        "status": "sent",
        "nfc_tag_id": normalized_nfc_tag_id,
        "device_id": endpoint.device_id,
        "ws_host": endpoint.ws_host,
        "ws_port": endpoint.ws_port,
        "reason": reason,
    }

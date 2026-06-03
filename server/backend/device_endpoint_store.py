from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time
from typing import Any

from config import DEVICE_ENDPOINT_TTL_SECONDS


@dataclass(slots=True)
class DeviceEndpoint:
    ws_host: str
    ws_port: int
    device_id: str
    nfc_tag_id: str | None
    updated_at: float

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.ws_host}:{self.ws_port}/"


class DeviceEndpointStore:
    def __init__(self, ttl_seconds: int = DEVICE_ENDPOINT_TTL_SECONDS) -> None:
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._lock = Lock()
        self._by_device_id: dict[str, DeviceEndpoint] = {}
        self._by_nfc_tag_id: dict[str, DeviceEndpoint] = {}

    def _cleanup_expired_locked(self, now: float) -> None:
        expired_device_ids = [
            device_id
            for device_id, endpoint in self._by_device_id.items()
            if now - endpoint.updated_at > self._ttl_seconds
        ]
        for device_id in expired_device_ids:
            endpoint = self._by_device_id.pop(device_id, None)
            if endpoint and endpoint.nfc_tag_id:
                current = self._by_nfc_tag_id.get(endpoint.nfc_tag_id)
                if current and current.device_id == device_id:
                    self._by_nfc_tag_id.pop(endpoint.nfc_tag_id, None)

    def register(
        self,
        *,
        ws_host: str,
        ws_port: int,
        device_id: str | None,
        nfc_tag_id: str | None,
    ) -> DeviceEndpoint:
        normalized_host = str(ws_host or "").strip()
        if not normalized_host:
            raise ValueError("ws_host is required")

        normalized_port = int(ws_port or 81)
        normalized_device_id = str(device_id or normalized_host).strip() or normalized_host
        normalized_nfc_tag_id = str(nfc_tag_id or "").strip() or None

        now = time.time()
        with self._lock:
            self._cleanup_expired_locked(now)

            previous = self._by_device_id.get(normalized_device_id)
            if previous and previous.nfc_tag_id:
                current = self._by_nfc_tag_id.get(previous.nfc_tag_id)
                if current and current.device_id == normalized_device_id:
                    self._by_nfc_tag_id.pop(previous.nfc_tag_id, None)

            endpoint = DeviceEndpoint(
                ws_host=normalized_host,
                ws_port=normalized_port,
                device_id=normalized_device_id,
                nfc_tag_id=normalized_nfc_tag_id,
                updated_at=now,
            )
            self._by_device_id[normalized_device_id] = endpoint
            if normalized_nfc_tag_id:
                self._by_nfc_tag_id[normalized_nfc_tag_id] = endpoint
            return endpoint

    def get_by_nfc_tag_id(self, nfc_tag_id: str | None) -> DeviceEndpoint | None:
        normalized_nfc_tag_id = str(nfc_tag_id or "").strip()
        if not normalized_nfc_tag_id:
            return None

        now = time.time()
        with self._lock:
            self._cleanup_expired_locked(now)
            endpoint = self._by_nfc_tag_id.get(normalized_nfc_tag_id)
            if endpoint is None:
                return None
            endpoint.updated_at = now
            return DeviceEndpoint(
                ws_host=endpoint.ws_host,
                ws_port=endpoint.ws_port,
                device_id=endpoint.device_id,
                nfc_tag_id=endpoint.nfc_tag_id,
                updated_at=endpoint.updated_at,
            )

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._cleanup_expired_locked(now)
            return {
                "by_device_id": {
                    device_id: {
                        "ws_host": endpoint.ws_host,
                        "ws_port": endpoint.ws_port,
                        "device_id": endpoint.device_id,
                        "nfc_tag_id": endpoint.nfc_tag_id,
                        "updated_at": endpoint.updated_at,
                    }
                    for device_id, endpoint in self._by_device_id.items()
                },
                "by_nfc_tag_id": {
                    nfc_tag_id: {
                        "ws_host": endpoint.ws_host,
                        "ws_port": endpoint.ws_port,
                        "device_id": endpoint.device_id,
                        "nfc_tag_id": endpoint.nfc_tag_id,
                        "updated_at": endpoint.updated_at,
                    }
                    for nfc_tag_id, endpoint in self._by_nfc_tag_id.items()
                },
            }


device_endpoint_store = DeviceEndpointStore()

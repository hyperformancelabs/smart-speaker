from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

import device_schedule_dispatch
from device_endpoint_store import DeviceEndpointStore


class DeviceScheduleDispatchTests(unittest.TestCase):
    def test_endpoint_store_registers_and_resolves_by_nfc_tag_id(self) -> None:
        store = DeviceEndpointStore(ttl_seconds=3600)
        store.register(
            ws_host="192.168.1.15",
            ws_port=81,
            device_id="esp-1",
            nfc_tag_id="15:CF:D0:06",
        )

        endpoint = store.get_by_nfc_tag_id("15:CF:D0:06")

        self.assertIsNotNone(endpoint)
        assert endpoint is not None
        self.assertEqual(endpoint.device_id, "esp-1")
        self.assertEqual(endpoint.websocket_url, "ws://192.168.1.15:81/")

    def test_notify_device_schedule_sync_returns_no_endpoint_when_unknown(self) -> None:
        with patch.object(device_schedule_dispatch, "device_endpoint_store", DeviceEndpointStore(ttl_seconds=3600)):
            result = device_schedule_dispatch.notify_device_schedule_sync(
                nfc_tag_id="15:CF:D0:06",
                reason="timer_created",
            )

        self.assertEqual(result["status"], "no_endpoint")
        self.assertEqual(result["nfc_tag_id"], "15:CF:D0:06")

    def test_notify_device_schedule_sync_sends_request_to_registered_endpoint(self) -> None:
        store = DeviceEndpointStore(ttl_seconds=3600)
        store.register(
            ws_host="192.168.1.15",
            ws_port=81,
            device_id="esp-1",
            nfc_tag_id="15:CF:D0:06",
        )

        with patch.object(device_schedule_dispatch, "device_endpoint_store", store), patch.object(
            device_schedule_dispatch,
            "send_device_json_message",
        ) as send_mock:
            result = device_schedule_dispatch.notify_device_schedule_sync(
                nfc_tag_id="15:CF:D0:06",
                reason="alarm_created",
            )

        self.assertEqual(result["status"], "sent")
        send_mock.assert_called_once()
        payload = send_mock.call_args.args[1]
        self.assertEqual(payload["type"], "schedule_sync_request")
        self.assertEqual(payload["nfc_tag_id"], "15:CF:D0:06")
        self.assertEqual(payload["reason"], "alarm_created")


if __name__ == "__main__":
    unittest.main()

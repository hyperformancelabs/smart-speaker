from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

try:
    import app as backend_app_module
except ModuleNotFoundError as exc:
    backend_app_module = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(backend_app_module is None, f"backend app dependencies are unavailable: {IMPORT_ERROR}")
class DebugRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        backend_app_module.app.config.update(TESTING=True)
        self.client = backend_app_module.app.test_client()

    def test_dev_assistant_turn_wraps_result_and_session_key(self) -> None:
        with patch.object(
            backend_app_module,
            "_ensure_debug_user_registration",
            return_value={"user_id": "resolved-user"},
        ) as ensure_debug_user_mock, patch.object(
            backend_app_module,
            "run_browser_turn",
            return_value={
                "tts_text": "Xin chào",
                "status": "completed",
                "route": {"group": "conversation"},
                "session_state": {"mode": "conversation"},
                "playback_sequence": [],
            },
        ) as run_browser_turn_mock, patch.object(
            backend_app_module,
            "resolve_session_key",
            return_value="device:browser-1",
        ):
            response = self.client.post(
                "/api/dev/assistant-turn",
                json={
                    "device_id": "browser-1",
                    "text_input": "hello server",
                    "session_state": {"mode": "conversation"},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["tts_text"], "Xin chào")
        self.assertEqual(payload["session_key"], "device:browser-1")
        ensure_debug_user_mock.assert_called_once_with(None)
        run_browser_turn_mock.assert_called_once()

    def test_dev_session_reset_clears_backend_store(self) -> None:
        with patch.object(
            backend_app_module,
            "clear_assistant_session",
            return_value="device:browser-2",
        ) as clear_session_mock, patch.object(
            backend_app_module.device_session_store,
            "dump",
            return_value={"device:browser-2": {"session_state": {"mode": "router"}}},
        ):
            response = self.client.post(
                "/api/dev/session/reset",
                json={"device_id": "browser-2"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "cleared")
        self.assertEqual(payload["session_key"], "device:browser-2")
        clear_session_mock.assert_called_once()

    def test_api_test_uses_default_smoke_prompt(self) -> None:
        with patch.object(
            backend_app_module,
            "_ensure_debug_user_registration",
            return_value={"user_id": "resolved-user"},
        ) as ensure_debug_user_mock, patch.object(
            backend_app_module,
            "run_assistant_turn",
            return_value={
                "tts_text": "Đây là smoke test.",
                "status": "completed",
                "route": {"group": "conversation"},
                "session_state": {},
            },
        ) as run_assistant_turn_mock:
            response = self.client.post("/api/test", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("câu chuyện vui", payload["input"])
        self.assertEqual(payload["output"]["tts_text"], "Đây là smoke test.")
        ensure_debug_user_mock.assert_called_once_with(backend_app_module.DEFAULT_TEST_NFC_TAG_ID)
        run_assistant_turn_mock.assert_called_once()

    def test_dev_assistant_turn_ensures_debug_user_for_nfc_tag(self) -> None:
        with patch.object(
            backend_app_module,
            "_ensure_debug_user_registration",
            return_value={"user_id": "resolved-user"},
        ) as ensure_debug_user_mock, patch.object(
            backend_app_module,
            "run_browser_turn",
            return_value={
                "tts_text": "Đặt timer xong rồi",
                "status": "completed",
                "route": {"group": "productivity"},
                "session_state": {"mode": "conversation"},
                "playback_sequence": [],
            },
        ), patch.object(
            backend_app_module,
            "resolve_session_key",
            return_value="nfc:15:CF:D0:06",
        ):
            response = self.client.post(
                "/api/dev/assistant-turn",
                json={
                    "device_id": "browser-lab",
                    "nfc_tag_id": "15:CF:D0:06",
                    "text_input": "hãy cài timer sau 10 giây",
                },
            )

        self.assertEqual(response.status_code, 200)
        ensure_debug_user_mock.assert_called_once_with("15:CF:D0:06")

    def test_audio_start_passes_nfc_tag_id_into_capture_request(self) -> None:
        with patch.object(
            backend_app_module.capture_manager,
            "start",
            return_value={"state": "started"},
        ) as capture_start_mock:
            response = self.client.post(
                "/api/audio/start",
                json={
                    "ws_host": "192.168.1.11",
                    "ws_port": 81,
                    "capture_token": "cap-123",
                    "nfc_tag_id": "15:CF:D0:06",
                    "device_id": "esp-1",
                },
            )

        self.assertEqual(response.status_code, 202)
        capture_request = capture_start_mock.call_args.args[0]
        self.assertEqual(capture_request.nfc_tag_id, "15:CF:D0:06")
        self.assertEqual(capture_request.device_id, "esp-1")

    def test_device_announce_registers_latest_endpoint(self) -> None:
        with patch.object(
            backend_app_module.device_endpoint_store,
            "register",
        ) as register_mock:
            response = self.client.post(
                "/api/device/announce",
                json={
                    "ws_host": "192.168.1.15",
                    "ws_port": 81,
                    "device_id": "esp-1",
                    "nfc_tag_id": "15:CF:D0:06",
                },
            )

        self.assertEqual(response.status_code, 202)
        register_mock.assert_called_once_with(
            ws_host="192.168.1.15",
            ws_port=81,
            device_id="esp-1",
            nfc_tag_id="15:CF:D0:06",
        )

    def test_device_schedule_notify_dispatches_sync_request(self) -> None:
        with patch.object(
            backend_app_module,
            "notify_device_schedule_sync",
            return_value={"status": "sent", "device_id": "esp-1"},
        ) as notify_mock:
            response = self.client.post(
                "/api/device/schedules/notify",
                json={
                    "nfc_tag_id": "15:CF:D0:06",
                    "reason": "timer_created",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "sent")
        notify_mock.assert_called_once_with(
            nfc_tag_id="15:CF:D0:06",
            reason="timer_created",
        )


if __name__ == "__main__":
    unittest.main()

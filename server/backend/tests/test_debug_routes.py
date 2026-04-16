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
        run_assistant_turn_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

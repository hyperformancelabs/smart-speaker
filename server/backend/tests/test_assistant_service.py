from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

import assistant_service


class AssistantServiceTests(unittest.TestCase):
    def test_run_assistant_turn_uses_cached_session_when_request_omits_one(self) -> None:
        captured_payload: dict[str, object] = {}

        def fake_run_pipeline(payload: dict[str, object]) -> dict[str, object]:
            captured_payload.update(payload)
            return {
                "tts_text": "Xin chào",
                "status": "completed",
                "route": {"group": "conversation"},
                "session_state": {"mode": "conversation"},
                "commands": [],
            }

        synthesized = SimpleNamespace(
            text="Xin chào",
            spoken_text="Xin chao",
            file_path=Path("/tmp/fake_tts.wav"),
            duration_seconds=1.2,
            voice_name="voice-a",
            sample_rate=16000,
            channels=1,
        )

        with patch.object(assistant_service.device_session_store, "get", return_value={"mode": "router"}), patch.object(
            assistant_service.device_session_store,
            "set",
        ), patch.object(
            assistant_service,
            "run_pipeline",
            side_effect=fake_run_pipeline,
        ), patch.object(
            assistant_service,
            "get_user_by_nfc_tag",
            return_value={"user_id": "resolved-user"},
        ), patch.object(
            assistant_service.tts_service,
            "synthesize",
            return_value=synthesized,
        ), patch.object(
            assistant_service.asset_registry,
            "register_tts_file",
            return_value=SimpleNamespace(asset_id="tts_123"),
        ), patch.object(
            assistant_service.asset_registry,
            "build_tts_url",
            return_value="http://localhost/tts_123.wav",
        ):
            result = assistant_service.run_assistant_turn(
                {
                    "nfc_tag_id": "tag-1",
                    "device_id": "browser-1",
                    "text_input": "hello",
                }
            )

        self.assertEqual(captured_payload["session_state"], {"mode": "router"})
        self.assertEqual(captured_payload["user_id"], "resolved-user")
        self.assertEqual(result["playback"]["tts"]["url"], "http://localhost/tts_123.wav")

    def test_run_assistant_turn_enriches_media_commands_for_device(self) -> None:
        media_record = SimpleNamespace(
            asset_id="media_456",
            metadata={"title": "Lo-fi", "source": "youtube"},
        )

        with patch.object(assistant_service.device_session_store, "get", return_value=None), patch.object(
            assistant_service.device_session_store,
            "set",
        ), patch.object(
            assistant_service,
            "run_pipeline",
            return_value={
                "tts_text": "Đang phát cho bạn",
                "status": "completed",
                "route": {"group": "media"},
                "session_state": {"mode": "router"},
                "commands": [
                    {
                        "type": "audio_stream",
                        "stream_url": "https://upstream.example/lofi.m4a",
                        "title": "Lo-fi",
                        "source": "youtube",
                    }
                ],
            },
        ), patch.object(
            assistant_service.tts_service,
            "synthesize",
            return_value=SimpleNamespace(
                text="Đang phát cho bạn",
                spoken_text="Dang phat cho ban",
                file_path=Path("/tmp/fake_tts.wav"),
                duration_seconds=1.0,
                voice_name="voice-a",
                sample_rate=16000,
                channels=1,
            ),
        ), patch.object(
            assistant_service.asset_registry,
            "register_tts_file",
            return_value=SimpleNamespace(asset_id="tts_999"),
        ), patch.object(
            assistant_service.asset_registry,
            "build_tts_url",
            return_value="http://localhost/tts_999.wav",
        ), patch.object(
            assistant_service.asset_registry,
            "register_media_source",
            return_value=media_record,
        ), patch.object(
            assistant_service.asset_registry,
            "build_media_url",
            return_value="http://localhost/media_456.wav",
        ):
            result = assistant_service.run_assistant_turn(
                {
                    "user_id": "user-1",
                    "device_id": "browser-1",
                    "text_input": "phát lo-fi",
                }
            )

        self.assertEqual(result["playback"]["media_after_tts"]["stream_url"], "http://localhost/media_456.wav")
        self.assertEqual(result["commands_for_device"][0]["transcoded_stream_url"], "http://localhost/media_456.wav")
        self.assertEqual(result["esp_messages"][0]["type"], "audio_session_state")
        self.assertEqual(result["esp_messages"][1]["type"], "assistant_playback")


if __name__ == "__main__":
    unittest.main()

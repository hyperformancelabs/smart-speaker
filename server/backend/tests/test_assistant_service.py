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
                    "capture_token": "cap-1",
                    "text_input": "hello",
                }
            )

        self.assertEqual(captured_payload["session_state"], {"mode": "router"})
        self.assertEqual(captured_payload["user_id"], "resolved-user")
        self.assertEqual(result["playback"]["tts"]["url"], "http://localhost/tts_123.wav")

    def test_run_assistant_turn_replaces_placeholder_user_id_from_nfc_profile(self) -> None:
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

        with patch.object(assistant_service.device_session_store, "get", return_value=None), patch.object(
            assistant_service.device_session_store,
            "set",
        ), patch.object(
            assistant_service,
            "run_pipeline",
            side_effect=fake_run_pipeline,
        ), patch.object(
            assistant_service,
            "get_user_by_nfc_tag",
            return_value={"user_id": "resolved-user-uuid"},
        ), patch.object(
            assistant_service.tts_service,
            "synthesize",
            return_value=synthesized,
        ), patch.object(
            assistant_service.asset_registry,
            "register_tts_file",
            return_value=SimpleNamespace(asset_id="tts_456"),
        ), patch.object(
            assistant_service.asset_registry,
            "build_tts_url",
            return_value="http://localhost/tts_456.wav",
        ):
            assistant_service.run_assistant_turn(
                {
                    "user_id": "server_test_user",
                    "nfc_tag_id": "15:CF:D0:06",
                    "device_id": "browser-1",
                    "text_input": "hello",
                }
            )

        self.assertEqual(captured_payload["user_id"], "resolved-user-uuid")

    def test_run_assistant_turn_enriches_media_commands_for_device(self) -> None:
        media_record = SimpleNamespace(
            asset_id="media_456",
            metadata={
                "title": "Lo-fi",
                "source": "youtube",
                "transcode_source_type": "proxy",
            },
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
                    "capture_token": "cap-2",
                    "public_base_url": "http://192.168.1.8:8387",
                    "text_input": "phát lo-fi",
                }
            )

        self.assertEqual(result["playback"]["media_after_tts"]["stream_url"], "http://localhost/media_456.wav")
        self.assertEqual(result["commands_for_device"][0]["transcoded_stream_url"], "http://localhost/media_456.wav")
        self.assertEqual(result["esp_messages"][0]["type"], "audio_session_state")
        self.assertEqual(result["esp_messages"][0]["capture_token"], "cap-2")
        self.assertEqual(result["esp_messages"][1]["type"], "assistant_playback")
        self.assertEqual(result["esp_messages"][1]["capture_token"], "cap-2")
        self.assertEqual(result["esp_messages"][1]["final_state"], "streaming")

    def test_prepare_media_command_prefers_upstream_stream_for_transcoding(self) -> None:
        media_record = SimpleNamespace(
            asset_id="media_upstream",
            metadata={
                "title": "Lo-fi",
                "source": "youtube",
                "transcode_source_type": "upstream",
            },
        )

        with patch.object(
            assistant_service.asset_registry,
            "register_media_source",
            return_value=media_record,
        ) as register_media_source_mock, patch.object(
            assistant_service.asset_registry,
            "build_media_url",
            return_value="http://192.168.1.8:8387/api/assets/media/media_upstream.wav",
        ):
            normalized, playback = assistant_service._prepare_media_command(
                {
                    "type": "audio_stream",
                    "proxy_url": "http://localhost:8387/api/media/youtube/stream?video_id=abc&mode=audio",
                    "stream_url": "http://localhost:8387/api/media/youtube/stream?video_id=abc&mode=audio",
                    "upstream_stream_url": "https://rr1---sn.example.googlevideo.com/videoplayback?id=abc",
                    "title": "Lo-fi",
                    "source": "youtube",
                },
                public_base_url="http://192.168.1.8:8387",
            )

        self.assertIsNotNone(normalized)
        self.assertIsNotNone(playback)
        register_media_source_mock.assert_called_once()
        self.assertEqual(
            register_media_source_mock.call_args.args[0],
            "https://rr1---sn.example.googlevideo.com/videoplayback?id=abc",
        )
        self.assertEqual(
            register_media_source_mock.call_args.kwargs["metadata"]["transcode_source_type"],
            "upstream",
        )
        self.assertEqual(
            register_media_source_mock.call_args.kwargs["metadata"]["proxy_source_url"],
            "http://localhost:8387/api/media/youtube/stream?video_id=abc&mode=audio",
        )
        self.assertEqual(playback["transcode_source_type"], "upstream")
        self.assertEqual(
            playback["transcode_source_url"],
            "https://rr1---sn.example.googlevideo.com/videoplayback?id=abc",
        )

    def test_run_assistant_turn_passes_public_base_url_to_asset_registry(self) -> None:
        with patch.object(assistant_service.device_session_store, "get", return_value=None), patch.object(
            assistant_service.device_session_store,
            "set",
        ), patch.object(
            assistant_service,
            "run_pipeline",
            return_value={
                "tts_text": "Xin chào bạn",
                "status": "completed",
                "route": {"group": "conversation"},
                "session_state": {"mode": "router"},
                "commands": [
                    {
                        "type": "audio_stream",
                        "stream_url": "https://upstream.example/song.m4a",
                        "title": "Song",
                        "source": "youtube",
                    }
                ],
            },
        ), patch.object(
            assistant_service.tts_service,
            "synthesize",
            return_value=SimpleNamespace(
                text="Xin chào bạn",
                spoken_text="Xin chao ban",
                file_path=Path("/tmp/fake_tts.wav"),
                duration_seconds=1.0,
                voice_name="voice-a",
                sample_rate=16000,
                channels=1,
            ),
        ), patch.object(
            assistant_service.asset_registry,
            "register_tts_file",
            return_value=SimpleNamespace(asset_id="tts_abc"),
        ), patch.object(
            assistant_service.asset_registry,
            "build_tts_url",
            return_value="http://192.168.1.8:8387/api/assets/tts/tts_abc.wav",
        ) as build_tts_url_mock, patch.object(
            assistant_service.asset_registry,
            "register_media_source",
            return_value=SimpleNamespace(asset_id="media_def", metadata={"title": "Song", "source": "youtube"}),
        ), patch.object(
            assistant_service.asset_registry,
            "build_media_url",
            return_value="http://192.168.1.8:8387/api/assets/media/media_def.wav",
        ) as build_media_url_mock:
            assistant_service.run_assistant_turn(
                {
                    "user_id": "user-1",
                    "device_id": "esp-1",
                    "public_base_url": "http://192.168.1.8:8387",
                    "text_input": "chào bạn",
                }
            )

        build_tts_url_mock.assert_called_once_with("tts_abc", base_url="http://192.168.1.8:8387")
        build_media_url_mock.assert_called_once_with("media_def", base_url="http://192.168.1.8:8387")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

import groq_whisper_stt


class GroqWhisperSttTests(unittest.TestCase):
    def tearDown(self) -> None:
        groq_whisper_stt._GROQ_CLIENT = None

    def test_get_groq_client_uses_configured_sdk_options(self) -> None:
        created_clients: list[dict[str, object]] = []

        class FakeGroq:
            def __init__(self, **kwargs):
                created_clients.append(dict(kwargs))

        with patch.dict(
            sys.modules,
            {"groq": SimpleNamespace(Groq=FakeGroq)},
        ), patch.object(groq_whisper_stt, "GROQ_API_KEY", "gsk_test"), patch.object(
            groq_whisper_stt,
            "GROQ_STT_BASE_URL",
            "https://api.groq.example/openai/v1",
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_TIMEOUT_SECONDS",
            12.5,
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_MAX_RETRIES",
            4,
        ):
            groq_whisper_stt._GROQ_CLIENT = None
            groq_whisper_stt.get_groq_client()

        self.assertEqual(
            created_clients,
            [
                {
                    "api_key": "gsk_test",
                    "base_url": "https://api.groq.example/openai/v1",
                    "timeout": 12.5,
                    "max_retries": 4,
                }
            ],
        )

    def test_transcribe_audio_file_builds_request_from_env_config(self) -> None:
        create_mock = Mock(
            return_value=SimpleNamespace(
                text="  Xin   chao  ban  ",
                language="vi",
            )
        )
        fake_client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=create_mock)
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".wav") as temp_audio, patch.object(
            groq_whisper_stt,
            "get_groq_client",
            return_value=fake_client,
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_MODEL",
            "whisper-large-v3",
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_LANGUAGE",
            "vi",
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_PROMPT",
            "Tên riêng: Phát, Groq",
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_RESPONSE_FORMAT",
            "verbose_json",
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_TEMPERATURE",
            0.0,
        ), patch.object(
            groq_whisper_stt,
            "GROQ_STT_TIMESTAMP_GRANULARITIES",
            ("word", "segment"),
        ):
            temp_audio.write(b"RIFFdemo")
            temp_audio.flush()

            result = groq_whisper_stt.transcribe_audio_file(Path(temp_audio.name))

        self.assertEqual(result.text, "Xin chao ban")
        self.assertEqual(result.language, "vi")
        create_mock.assert_called_once()

        request_kwargs = create_mock.call_args.kwargs
        self.assertEqual(request_kwargs["model"], "whisper-large-v3")
        self.assertEqual(request_kwargs["language"], "vi")
        self.assertEqual(request_kwargs["prompt"], "Tên riêng: Phát, Groq")
        self.assertEqual(request_kwargs["response_format"], "verbose_json")
        self.assertEqual(request_kwargs["temperature"], 0.0)
        self.assertEqual(request_kwargs["timestamp_granularities"], ["word", "segment"])
        self.assertEqual(request_kwargs["file"][0], Path(temp_audio.name).name)
        self.assertEqual(request_kwargs["file"][1], b"RIFFdemo")


if __name__ == "__main__":
    unittest.main()

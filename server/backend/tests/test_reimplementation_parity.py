from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_ROOT = REPO_ROOT / ".local" / "llm-orches"
SERVER_BACKEND_ROOT = REPO_ROOT / "server" / "backend"
SERVER_DATABASE_ROOT = REPO_ROOT / "server" / "database"

IDENTICAL_BACKEND_PATHS = [
    "assistant_core/state.py",
    "assistant_core/nodes.py",
    "assistant_core/graph.py",
    "assistant_core/runtime.py",
    "assistant_core/utils.py",
    "assistant_core/wrapper.py",
    "assistant_core/prompts.py",
    "assistant_tools/common.py",
    "assistant_tools/registry.py",
    "assistant_tools/information.py",
    "assistant_tools/media.py",
    "assistant_tools/schema.py",
    "profile_schema.py",
    "web_search_tool.py",
    "content_fetch_tool.py",
    "youtube_stream_tool.py",
]

IDENTICAL_DATABASE_PATHS = [
    "app.py",
    "models.py",
    "schema.sql",
    "Procfile",
    "requirements.txt",
]

EXPECTED_SERVER_EXTENSIONS = {
    "config.py": [
        "VOICE_BACKEND_PUBLIC_BASE_URL",
        "TTS_STORAGE_DIR",
        "MEDIA_STORAGE_DIR",
    ],
    "assistant_tools/backend_tools.py": [
        '"device_payload": {',
        '"type": "alarm"',
        '"type": "timer"',
    ],
    "app.py": [
        "/api/process-command",
        "/api/dev/assistant-turn",
        "/dev/assistant",
    ],
}


class ReimplementationParityTests(unittest.TestCase):
    def test_backend_reference_modules_match_byte_for_byte(self) -> None:
        for relative_path in IDENTICAL_BACKEND_PATHS:
            with self.subTest(relative_path=relative_path):
                reference_bytes = (REFERENCE_ROOT / relative_path).read_bytes()
                server_bytes = (SERVER_BACKEND_ROOT / relative_path).read_bytes()
                self.assertEqual(server_bytes, reference_bytes)

    def test_database_reference_modules_match_byte_for_byte(self) -> None:
        for relative_path in IDENTICAL_DATABASE_PATHS:
            with self.subTest(relative_path=relative_path):
                reference_bytes = (REFERENCE_ROOT / "database" / relative_path).read_bytes()
                server_bytes = (SERVER_DATABASE_ROOT / relative_path).read_bytes()
                self.assertEqual(server_bytes, reference_bytes)

    def test_server_specific_files_keep_expected_extensions(self) -> None:
        for relative_path, expected_snippets in EXPECTED_SERVER_EXTENSIONS.items():
            with self.subTest(relative_path=relative_path):
                content = (SERVER_BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
                for snippet in expected_snippets:
                    self.assertIn(snippet, content)


if __name__ == "__main__":
    unittest.main()

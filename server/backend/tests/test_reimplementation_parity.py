from __future__ import annotations

from pathlib import Path
import importlib
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_BACKEND_ROOT = REPO_ROOT / "server" / "backend"
SERVER_DATABASE_ROOT = REPO_ROOT / "server" / "database"

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
    def test_backend_runtime_modules_import(self) -> None:
        modules = [
            "assistant_core.runtime",
            "assistant_core.wrapper",
            "assistant_core.graph",
            "assistant_core.nodes",
            "assistant_service",
        ]
        for module_name in modules:
            with self.subTest(module_name=module_name):
                imported = importlib.import_module(module_name)
                self.assertIsNotNone(imported)

    def test_server_specific_files_keep_expected_extensions(self) -> None:
        for relative_path, expected_snippets in EXPECTED_SERVER_EXTENSIONS.items():
            with self.subTest(relative_path=relative_path):
                content = (SERVER_BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
                for snippet in expected_snippets:
                    self.assertIn(snippet, content)


if __name__ == "__main__":
    unittest.main()

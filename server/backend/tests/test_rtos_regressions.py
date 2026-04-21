from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEDULE_SERVICE = REPO_ROOT / "src" / "schedule" / "schedule_service.cpp"
APP_TASKS = REPO_ROOT / "src" / "rtos" / "app_tasks.cpp"
VOICE_BACKEND_SERVICE = REPO_ROOT / "src" / "net" / "voice_backend_service.cpp"


class RtosRegressionTests(unittest.TestCase):
    def test_schedule_service_uses_local_device_endpoints(self) -> None:
        source = SCHEDULE_SERVICE.read_text(encoding="utf-8")

        self.assertIn("String url = DEVICE_API_URL;", source)
        self.assertIn("const String url = String(DEVICE_VOICE_BACKEND_URL) + kDeviceAnnouncePath;", source)
        self.assertNotIn("String url = SERVER_URL;", source)

    def test_profile_lookup_queues_schedule_sync_in_background(self) -> None:
        source = APP_TASKS.read_text(encoding="utf-8")

        self.assertIn('scheduleRequestSync(lookupRequest.uid, "nfc_login");', source)
        self.assertNotIn('scheduleSyncForUid(lookupRequest.uid, "nfc_login");', source)

    def test_alert_recovery_returns_to_wait_wakeword_instead_of_idle(self) -> None:
        source = SCHEDULE_SERVICE.read_text(encoding="utf-8")

        self.assertIn("runtime::setAudioSessionMode(AudioSessionMode::WaitWakeword);", source)
        self.assertNotIn("runtime::setAudioSessionMode(AudioSessionMode::Idle);", source)

    def test_voice_backend_terminal_wait_wakeword_clears_capture_and_restores_standby(self) -> None:
        source = VOICE_BACKEND_SERVICE.read_text(encoding="utf-8")

        self.assertIn('extractJsonBoolField(message, "stop_capture", stopCapture);', source)
        self.assertIn(
            "if (stopCapture && nextState == ExternalAudioSessionState::WaitWakeword) {",
            source,
        )
        self.assertIn("voiceBackendInvalidateCaptureToken();", source)
        self.assertIn("runtime::setAudioSessionMode(AudioSessionMode::WaitWakeword);", source)

    def test_ui_task_only_consumes_external_state_when_it_can_apply_it(self) -> None:
        source = APP_TASKS.read_text(encoding="utf-8")

        self.assertIn("const bool canApplyExternalState =", source)
        self.assertIn(
            "if (canApplyExternalState && runtime::consumeExternalAudioSessionState(nextExternalState)) {",
            source,
        )
        self.assertNotIn(
            "if (runtime::consumeExternalAudioSessionState(nextExternalState) &&",
            source,
        )


if __name__ == "__main__":
    unittest.main()

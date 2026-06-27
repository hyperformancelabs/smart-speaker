from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEDULE_SERVICE = REPO_ROOT / "src" / "schedule" / "schedule_service.cpp"
APP_TASKS = REPO_ROOT / "src" / "rtos" / "app_tasks.cpp"
APP_RUNTIME = REPO_ROOT / "src" / "rtos" / "app_runtime.cpp"
VOICE_BACKEND_SERVICE = REPO_ROOT / "src" / "net" / "voice_backend_service.cpp"
AUDIO_SERVICE = REPO_ROOT / "src" / "audio" / "audio_service.cpp"
APP_CONFIG = REPO_ROOT / "src" / "app_config.h"
PLATFORMIO_INI = REPO_ROOT / "platformio.ini"


class RtosRegressionTests(unittest.TestCase):
    def test_schedule_service_uses_local_device_endpoints(self) -> None:
        source = SCHEDULE_SERVICE.read_text(encoding="utf-8")

        self.assertIn("String url = DEVICE_API_URL;", source)
        self.assertIn("const String url = String(DEVICE_VOICE_BACKEND_URL) + kDeviceAnnouncePath;", source)
        self.assertNotIn("String url = SERVER_URL;", source)

    def test_profile_lookup_finishes_schedule_sync_before_publishing_result(self) -> None:
        source = APP_TASKS.read_text(encoding="utf-8")

        sync_index = source.index('scheduleSyncForUid(lookupRequest.uid, "nfc_login");')
        publish_index = source.index("runtime::publishProfileLookupResult(lookupResult);")

        self.assertLess(sync_index, publish_index)
        self.assertNotIn('scheduleRequestSync(lookupRequest.uid, "nfc_login");', source)

    def test_alert_recovery_requests_wait_wakeword_without_direct_runtime_mutation(self) -> None:
        source = SCHEDULE_SERVICE.read_text(encoding="utf-8")

        self.assertIn(
            "appRequestExternalAudioSessionState(ExternalAudioSessionState::WaitWakeword);",
            source,
        )
        self.assertNotIn("runtime::setAudioSessionMode(AudioSessionMode::WaitWakeword);", source)
        self.assertNotIn("runtime::setAudioSessionMode(AudioSessionMode::Idle);", source)

    def test_alert_flag_clears_before_schedule_reporting_blocks_recovery(self) -> None:
        source = SCHEDULE_SERVICE.read_text(encoding="utf-8")

        report_index = source.index("reportConsumedSchedules(dueEntries, dueCount);")
        clear_index = source.index("setAlertState(false, false);")

        self.assertLess(
            clear_index,
            report_index,
            "alert state must clear before schedule event reporting so wakeword resumes immediately",
        )

    def test_voice_backend_terminal_wait_wakeword_clears_capture_without_direct_runtime_mutation(self) -> None:
        source = VOICE_BACKEND_SERVICE.read_text(encoding="utf-8")

        self.assertIn('extractJsonBoolField(message, "stop_capture", stopCapture);', source)
        self.assertIn(
            "if (stopCapture && nextState == ExternalAudioSessionState::WaitWakeword) {",
            source,
        )
        self.assertIn("voiceBackendInvalidateCaptureToken();", source)
        self.assertNotIn("runtime::setAudioSessionMode(AudioSessionMode::WaitWakeword);", source)

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

    def test_wait_wakeword_transition_cleans_runtime_before_starting_detection(self) -> None:
        source = APP_TASKS.read_text(encoding="utf-8")
        set_ui_mode = source[
            source.index("void setUiMode(") : source.index("void transitionToWakeword(")
        ]

        idle_index = set_ui_mode.index("runtime::setAudioSessionMode(AudioSessionMode::Idle);")
        cleanup_index = set_ui_mode.index("prepareWakewordRuntime();")
        wait_index = set_ui_mode.index("runtime::setAudioSessionMode(AudioSessionMode::WaitWakeword);")

        self.assertLess(idle_index, cleanup_index)
        self.assertLess(cleanup_index, wait_index)
        self.assertIn("vTaskDelay(pdMS_TO_TICKS(kWakewordPrepareMs));", set_ui_mode)
        self.assertIn("runtime::resetAssistantPlaybackQueue();", source)
        self.assertIn("runtime::resetBeepQueue();", source)
        self.assertIn("runtime::resetStreamAudioQueue();", source)
        self.assertIn("runtime::resetWakewordAudioQueue();", source)
        self.assertIn("runtime::resetProfileLookupQueues();", source)

    def test_wait_wakeword_keeps_background_tasks_out_of_sleep(self) -> None:
        app_tasks = APP_TASKS.read_text(encoding="utf-8")
        schedule = SCHEDULE_SERVICE.read_text(encoding="utf-8")

        self.assertIn(
            "if (!runtime::isAudioSessionActive() || runtime::isWakewordDetectionActive()) {",
            app_tasks,
        )
        self.assertIn("!runtime::isAudioSessionActive()", schedule)
        self.assertIn("shouldDeferScheduleSyncForWakeword()", schedule)
        self.assertIn("deferredSync = event;", schedule)
        self.assertIn("kScheduleWakewordSyncPollMs", schedule)

    def test_queued_beeps_do_not_interrupt_active_audio_sessions(self) -> None:
        source = APP_TASKS.read_text(encoding="utf-8")
        beep_task = source[source.index("void beepTask(") : source.index("void createTask(")]

        self.assertIn("if (runtime::isAudioSessionActive()) {", beep_task)
        self.assertIn("continue;", beep_task)
        self.assertLess(
            beep_task.index("if (runtime::isAudioSessionActive()) {"),
            beep_task.index("audioBeep(request.freq, request.durationMs);"),
        )

    def test_audio_route_uses_split_rx_tx_driver_to_preserve_boot_heap(self) -> None:
        source = AUDIO_SERVICE.read_text(encoding="utf-8")

        self.assertIn("buildCaptureConfig()", source)
        self.assertIn("buildPlaybackConfig()", source)
        self.assertIn("I2S_MODE_MASTER | I2S_MODE_RX", source)
        self.assertIn("I2S_MODE_MASTER | I2S_MODE_TX", source)
        self.assertNotIn("I2S_MODE_TX | I2S_MODE_RX", source)

    def test_wakeword_memory_pressure_is_kept_below_i2s_dma_budget(self) -> None:
        app_config = APP_CONFIG.read_text(encoding="utf-8")
        platformio = PLATFORMIO_INI.read_text(encoding="utf-8")

        self.assertIn("constexpr int MIC_DMA_CNT = 4;", app_config)
        self.assertIn("-DEIDSP_QUANTIZE_FILTERBANK=1", platformio)

    def test_runtime_can_drop_work_queues_before_sleep(self) -> None:
        source = APP_RUNTIME.read_text(encoding="utf-8")

        self.assertIn("void resetAssistantPlaybackQueue()", source)
        self.assertIn("xQueueReset(gPlaybackQueue);", source)
        self.assertIn("void resetProfileLookupQueues()", source)
        self.assertIn("xQueueReset(gProfileLookupRequestQueue);", source)
        self.assertIn("xQueueReset(gProfileLookupResultQueue);", source)


if __name__ == "__main__":
    unittest.main()

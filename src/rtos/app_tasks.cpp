#include "rtos/app_tasks.h"

#include <cctype>
#include <cstring>

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "app_config.h"
#include "audio/audio_service.h"
#include "audio/playback_service.h"
#include "net/voice_backend_service.h"
#include "net/wifi_service.h"
#include "net/ws_service.h"
#include "rtos/app_runtime.h"
#include "secrets.h"
#include "schedule/schedule_service.h"
#include "sensors/rfid_service.h"
#include "ui/oled_view.h"
#include "ui/serial_telemetry.h"
#include "wakeword/wakeword_service.h"

namespace {
namespace runtime = app_runtime;
using AudioSessionMode = runtime::AudioSessionMode;

constexpr BaseType_t kNetworkCore = 0;
constexpr BaseType_t kAudioCore = 1;

constexpr UBaseType_t kCaptureTaskPriority = 4;
constexpr UBaseType_t kWakewordTaskPriority = 3;
constexpr UBaseType_t kNetworkTaskPriority = 2;
constexpr UBaseType_t kProfileTaskPriority = 1;
constexpr UBaseType_t kUiTaskPriority = 1;
constexpr UBaseType_t kBeepTaskPriority = 1;
constexpr uint32_t kNetworkTaskStackBytes = 12 * 1024;

constexpr uint32_t kUiIntervalMs = 200;
constexpr uint32_t kUiSleepMs = 20;
constexpr uint32_t kNetworkSleepMs = 5;
constexpr uint32_t kProfileTaskPollMs = 250;
constexpr unsigned long kWifiReconnectKickMs = 1000;
constexpr unsigned long kRegisterPromptRecheckMs = 3000;
constexpr int kRfidBeepFreq = 900;
constexpr int kRfidBeepMs = 80;
constexpr unsigned long kGreetingDurationMs = 3000;
constexpr unsigned long kWakewordPrepareMs = 60;

enum class UiMode {
    Splash,
    WifiReconnect,
    AwaitNfc,
    Loading,
    LookupError,
    RegisterPrompt,
    Greeting,
    WaitWakeword,
    Streaming,
    Thinking,
    Speaking,
};

bool gTasksStarted = false;

const char *uiModeName(UiMode mode) {
    switch (mode) {
        case UiMode::Splash:
            return "splash";
        case UiMode::WifiReconnect:
            return "wifi_reconnect";
        case UiMode::AwaitNfc:
            return "await_nfc";
        case UiMode::Loading:
            return "loading";
        case UiMode::LookupError:
            return "lookup_error";
        case UiMode::RegisterPrompt:
            return "register_prompt";
        case UiMode::Greeting:
            return "greeting";
        case UiMode::WaitWakeword:
            return "wait_wakeword";
        case UiMode::Streaming:
            return "streaming";
        case UiMode::Thinking:
            return "thinking";
        case UiMode::Speaking:
            return "speaking";
    }

    return "unknown";
}

void copyText(char dest[], size_t destSize, const char *src) {
    if (destSize == 0) {
        return;
    }

    if (src == nullptr) {
        src = "";
    }

    std::strncpy(dest, src, destSize - 1);
    dest[destSize - 1] = '\0';
}

void buildRegisterQrUrl(char dest[], size_t destSize, const char *uid) {
    if (destSize == 0) {
        return;
    }

    dest[0] = '\0';
    String qrUrl = SERVER_URL;
    qrUrl += "/REGISTER";

    if (uid == nullptr || uid[0] == '\0') {
        copyText(dest, destSize, qrUrl.c_str());
        return;
    }

    qrUrl += "/";
    for (size_t i = 0; uid[i] != '\0'; ++i) {
        const unsigned char ch = static_cast<unsigned char>(uid[i]);
        if (ch != ':') {
            qrUrl += static_cast<char>(std::toupper(ch));
        }
    }

    copyText(dest, destSize, qrUrl.c_str());
}

AudioSessionMode audioSessionModeForUi(UiMode uiMode) {
    switch (uiMode) {
        case UiMode::WaitWakeword:
            return AudioSessionMode::WaitWakeword;
        case UiMode::Streaming:
            return AudioSessionMode::Streaming;
        case UiMode::Thinking:
            return AudioSessionMode::Thinking;
        case UiMode::Speaking:
            return AudioSessionMode::Speaking;
        case UiMode::Splash:
        case UiMode::WifiReconnect:
        case UiMode::AwaitNfc:
        case UiMode::Loading:
        case UiMode::LookupError:
        case UiMode::RegisterPrompt:
        case UiMode::Greeting:
            return AudioSessionMode::Idle;
    }

    return AudioSessionMode::Idle;
}

UiMode uiModeForExternalAudioSessionState(ExternalAudioSessionState state) {
    switch (state) {
        case ExternalAudioSessionState::WaitWakeword:
            return UiMode::WaitWakeword;
        case ExternalAudioSessionState::Streaming:
            return UiMode::Streaming;
        case ExternalAudioSessionState::Thinking:
            return UiMode::Thinking;
        case ExternalAudioSessionState::Speaking:
            return UiMode::Speaking;
    }

    return UiMode::WaitWakeword;
}

bool uiModeCanApplyExternalAudioSessionState(UiMode uiMode) {
    switch (uiMode) {
        case UiMode::WaitWakeword:
        case UiMode::Streaming:
        case UiMode::Thinking:
        case UiMode::Speaking:
            return true;
        case UiMode::Splash:
        case UiMode::WifiReconnect:
        case UiMode::AwaitNfc:
        case UiMode::Loading:
        case UiMode::LookupError:
        case UiMode::RegisterPrompt:
        case UiMode::Greeting:
            return false;
    }

    return false;
}

bool shouldPollRfid(UiMode uiMode, bool profileLookupPending) {
    if (profileLookupPending) {
        return false;
    }

    switch (uiMode) {
        case UiMode::AwaitNfc:
        case UiMode::LookupError:
        case UiMode::RegisterPrompt:
        case UiMode::WaitWakeword:
        case UiMode::Streaming:
            return true;
        case UiMode::Thinking:
        case UiMode::Speaking:
        case UiMode::Splash:
        case UiMode::WifiReconnect:
        case UiMode::Loading:
        case UiMode::Greeting:
            return false;
    }

    return false;
}

bool shouldShowWifiReconnect(UiMode uiMode,
                             bool profileLookupPending,
                             WifiConnectionState wifiState) {
    if (wifiState == WifiConnectionState::Ready || profileLookupPending) {
        return false;
    }

    switch (uiMode) {
        case UiMode::AwaitNfc:
        case UiMode::LookupError:
        case UiMode::RegisterPrompt:
        case UiMode::WaitWakeword:
        case UiMode::Streaming:
        case UiMode::Thinking:
        case UiMode::Speaking:
        case UiMode::WifiReconnect:
            return true;
        case UiMode::Splash:
        case UiMode::Loading:
        case UiMode::Greeting:
            return false;
    }

    return false;
}

void prepareWakewordRuntime() {
    runtime::clearPendingExternalAudioSessionState();
    voiceBackendInvalidateCaptureToken();
    runtime::resetAssistantPlaybackQueue();
    runtime::resetBeepQueue();
    runtime::resetStreamAudioQueue();
    runtime::resetWakewordAudioQueue();
    runtime::resetProfileLookupQueues();
    runtime::storePlaybackAudio(nullptr, 0);
    audioResetWsFrames();
}

void setUiMode(UiMode &uiMode, UiMode nextMode, unsigned long &lastUiFrameMs) {
    const bool enteringWakeword = nextMode == UiMode::WaitWakeword;

    if (uiMode == nextMode) {
        if (enteringWakeword) {
            runtime::setAudioSessionMode(AudioSessionMode::Idle);
            prepareWakewordRuntime();
            vTaskDelay(pdMS_TO_TICKS(kWakewordPrepareMs));
            runtime::setAudioSessionMode(AudioSessionMode::WaitWakeword);
        }
        return;
    }

    Serial.printf("ui: %s -> %s\n", uiModeName(uiMode), uiModeName(nextMode));
    if (enteringWakeword) {
        runtime::setAudioSessionMode(AudioSessionMode::Idle);
        prepareWakewordRuntime();
        vTaskDelay(pdMS_TO_TICKS(kWakewordPrepareMs));
    }
    uiMode = nextMode;
    runtime::setAudioSessionMode(audioSessionModeForUi(nextMode));
    lastUiFrameMs = 0;
}

void transitionToWakeword(UiMode &uiMode, unsigned long &lastUiFrameMs) {
    setUiMode(uiMode, UiMode::WaitWakeword, lastUiFrameMs);
}

bool handleStartupUi(unsigned long splashStartedMs,
                     unsigned long &lastStartupFrameMs,
                     bool &wifiReadyBeeped,
                     bool &startupShowingError) {
    const unsigned long now = millis();
    const unsigned long elapsed = now - splashStartedMs;
    const WifiConnectionState wifiState = wifiGetConnectionState();

    if (!wifiReadyBeeped && elapsed >= STARTUP_SPLASH_MS &&
        wifiState == WifiConnectionState::Ready) {
        runtime::queueBeep(WIFI_CONNECTED_BEEP_FREQ, WIFI_CONNECTED_BEEP_MS);
        wifiReadyBeeped = true;
    }

    if (elapsed >= STARTUP_SPLASH_MS && wifiState == WifiConnectionState::Ready) {
        return false;
    }

    const bool shouldShowLoading =
        elapsed < STARTUP_SPLASH_MS || wifiState == WifiConnectionState::Connecting;

    if (shouldShowLoading) {
        if (startupShowingError || lastStartupFrameMs == 0 ||
            now - lastStartupFrameMs >= STARTUP_SPINNER_INTERVAL_MS) {
            oledDrawStartup(elapsed);
            lastStartupFrameMs = now;
            startupShowingError = false;
        }

        return true;
    }

    if (!startupShowingError) {
        oledDrawStartupConnectionError();
        startupShowingError = true;
    }

    return true;
}

void audioCaptureTask(void *param) {
    (void)param;

    AudioChunk chunk = {};

    for (;;) {
        if (scheduleAlertActive()) {
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        if (!runtime::isMicrophoneCaptureActive()) {
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        int rawLen = 0;
        audioReadMic(chunk.samples, rawLen);
        if (rawLen <= 0) {
            vTaskDelay(pdMS_TO_TICKS(1));
            continue;
        }

        chunk.len = static_cast<uint16_t>(rawLen);
        chunk.capturedMs = millis();

        if (runtime::isStreamingActive()) {
            runtime::storeLatestAudio(chunk);
        }
        if (runtime::isWakewordDetectionActive()) {
            runtime::pushWakewordAudio(chunk);
        }
        if (runtime::isStreamingActive()) {
            runtime::pushStreamAudio(chunk);
        }
    }
}

void wakewordTask(void *param) {
    (void)param;

    AudioChunk chunk = {};
    WakewordInfo wakeword = {};
    bool wakewordActive = false;

    for (;;) {
        if (scheduleAlertActive()) {
            if (wakewordActive) {
                wakewordActive = false;
                wakeword = {};
                runtime::storeWakewordState(wakeword);
                runtime::resetWakewordAudioQueue();
            }
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        if (!runtime::isWakewordDetectionActive()) {
            if (wakewordActive) {
                wakewordActive = false;
                wakeword = {};
                runtime::storeWakewordState(wakeword);
                runtime::resetWakewordAudioQueue();
            }
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        if (!wakewordActive) {
            wakewordInit(wakeword);
            runtime::storeWakewordState(wakeword);
            wakewordActive = true;
        }

        if (!runtime::waitWakewordAudio(chunk, pdMS_TO_TICKS(kUiSleepMs))) {
            continue;
        }

        if (wakewordProcessSamples(chunk.samples, chunk.len, wakeword)) {
            runtime::queueBeep(WAKEWORD_BEEP_FREQ, WAKEWORD_BEEP_MS);
            runtime::signalWakewordTransition();
        }

        runtime::storeWakewordState(wakeword);
    }
}

void networkTask(void *param) {
    (void)param;

    AudioChunk chunk = {};
    bool streamingActive = false;
    AssistantPlaybackRequest playbackRequest = {};
    bool hasPlaybackRequest = false;

    for (;;) {
        if (scheduleAlertActive()) {
            if (streamingActive) {
                streamingActive = false;
                runtime::resetStreamAudioQueue();
                audioResetWsFrames();
            }
            hasPlaybackRequest = false;
            runtime::storePlaybackAudio(nullptr, 0);
            vTaskDelay(pdMS_TO_TICKS(kNetworkSleepMs));
            continue;
        }

        if (!runtime::isAudioSessionActive() || runtime::isWakewordDetectionActive()) {
            if (streamingActive) {
                streamingActive = false;
                runtime::resetStreamAudioQueue();
                audioResetWsFrames();
            }
            hasPlaybackRequest = false;
            runtime::storePlaybackAudio(nullptr, 0);
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        wifiEnsureConnected();
        wsLoop();

        AssistantPlaybackRequest nextPlayback = {};
        if (runtime::tryPopAssistantPlayback(nextPlayback)) {
            playbackRequest = nextPlayback;
            hasPlaybackRequest = true;
            Serial.printf("playback: queued request tts=%s media=%s\n",
                          playbackRequest.ttsUrl[0] != '\0' ? "yes" : "no",
                          playbackRequest.mediaUrl[0] != '\0' ? "yes" : "no");
        }

        if (hasPlaybackRequest &&
            voiceBackendCaptureTokenMatches(playbackRequest.captureToken) &&
            !runtime::isSpeakingActive()) {
            Serial.println("playback: forcing speaking state for queued playback");
            appRequestExternalAudioSessionState(ExternalAudioSessionState::Speaking);
        }

        if (runtime::isSpeakingActive()) {
            if (streamingActive) {
                streamingActive = false;
                runtime::resetStreamAudioQueue();
                audioResetWsFrames();
            }

            if (hasPlaybackRequest && !voiceBackendCaptureTokenMatches(playbackRequest.captureToken)) {
                hasPlaybackRequest = false;
                runtime::storePlaybackAudio(nullptr, 0);
            }

            if (hasPlaybackRequest) {
                const AssistantPlaybackRequest activePlayback = playbackRequest;
                hasPlaybackRequest = false;
                const bool completed = playbackRunAssistantRequest(activePlayback);
                if (completed && runtime::isSpeakingActive() &&
                    voiceBackendCaptureTokenMatches(activePlayback.captureToken)) {
                    appRequestExternalAudioSessionState(activePlayback.finalState);
                }
                continue;
            }

            vTaskDelay(pdMS_TO_TICKS(kNetworkSleepMs));
            continue;
        }

        if (!runtime::isStreamingActive()) {
            if (streamingActive) {
                streamingActive = false;
                runtime::resetStreamAudioQueue();
                audioResetWsFrames();
            }
            if (hasPlaybackRequest && !voiceBackendCaptureTokenMatches(playbackRequest.captureToken)) {
                hasPlaybackRequest = false;
            }
            runtime::storePlaybackAudio(nullptr, 0);

            vTaskDelay(pdMS_TO_TICKS(kNetworkSleepMs));
            continue;
        }

        if (!streamingActive) {
            audioResetWsFrames();
            if (!voiceBackendStartCapture()) {
                vTaskDelay(pdMS_TO_TICKS(200));
                continue;
            }
            streamingActive = true;
        }

        bool drainedAnyChunk = false;
        while (runtime::tryPopStreamAudio(chunk)) {
            audioFeedWsFrames(chunk.samples, chunk.len);
            drainedAnyChunk = true;
            wsLoop();
        }

        if (!drainedAnyChunk) {
            vTaskDelay(pdMS_TO_TICKS(kNetworkSleepMs));
        } else {
            taskYIELD();
        }
    }
}

void profileLookupTask(void *param) {
    (void)param;

    runtime::ProfileLookupRequest lookupRequest = {};
    runtime::ProfileLookupResult lookupResult = {};

    for (;;) {
        if (!runtime::waitProfileLookup(lookupRequest, pdMS_TO_TICKS(kProfileTaskPollMs))) {
            continue;
        }

        while (scheduleAlertActive()) {
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
        }
        while (runtime::isWakewordDetectionActive()) {
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
        }

        wifiEnsureConnected();
        scheduleAnnounceDevice(lookupRequest.uid);

        lookupResult = {};
        copyText(lookupResult.uid, sizeof(lookupResult.uid), lookupRequest.uid);
        lookupResult.requestOk = profileFetchStatus(lookupRequest.uid, lookupResult.status);
        if (lookupResult.requestOk && profileIsComplete(lookupResult.status)) {
            scheduleSyncForUid(lookupRequest.uid, "nfc_login");
        }
        runtime::publishProfileLookupResult(lookupResult);
    }
}

void uiTask(void *param) {
    (void)param;

    unsigned long splashStartedMs = millis();
    unsigned long lastStartupFrameMs = 0;
    unsigned long lastUiFrameMs = 0;
    bool wifiReadyBeeped = false;
    bool startupShowingError = false;
    char uid[32] = {};
    UiMode uiMode = UiMode::Splash;
    bool startupCompleted = false;
    unsigned long loadingAnimationStartedMs = 0;
    unsigned long greetingStartedMs = 0;
    unsigned long reconnectStartedMs = 0;
    unsigned long lastWifiReconnectKickMs = 0;
    char greetingName[64] = {};
    char registerUrl[160] = {};
    char pendingLookupUid[32] = {};
    unsigned long lastRegisterPromptLookupMs = 0;
    bool profileLookupPending = false;
    UiMode reconnectResumeMode = UiMode::AwaitNfc;

    runtime::setAudioSessionMode(AudioSessionMode::Idle);

    for (;;) {
        if (!startupCompleted) {
            const bool startupActive = handleStartupUi(
                splashStartedMs, lastStartupFrameMs, wifiReadyBeeped, startupShowingError);
            if (startupActive) {
                uiMode = UiMode::Splash;
                vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
                continue;
            }

            startupCompleted = true;
            setUiMode(uiMode, UiMode::AwaitNfc, lastUiFrameMs);
        }

        const unsigned long now = millis();
        const WifiConnectionState wifiState = wifiGetConnectionState();

        if (shouldShowWifiReconnect(uiMode, profileLookupPending, wifiState)) {
            if (uiMode != UiMode::WifiReconnect) {
                reconnectResumeMode = uiMode;
                reconnectStartedMs = now;
                lastWifiReconnectKickMs = 0;
                setUiMode(uiMode, UiMode::WifiReconnect, lastUiFrameMs);
            }

            const bool shouldKickReconnect =
                lastWifiReconnectKickMs == 0 ||
                (wifiState == WifiConnectionState::Failed &&
                 now - lastWifiReconnectKickMs >= kWifiReconnectKickMs);
            if (shouldKickReconnect) {
                wifiForceReconnect();
                lastWifiReconnectKickMs = now;
            }
        } else if (uiMode == UiMode::WifiReconnect && wifiState == WifiConnectionState::Ready) {
            setUiMode(uiMode, reconnectResumeMode, lastUiFrameMs);
        }

        if (scheduleAlertActive()) {
            if (rfidPoll(uid, sizeof(uid))) {
                runtime::storeLastUid(uid);
                scheduleDismissActiveAlert();
                copyText(pendingLookupUid, sizeof(pendingLookupUid), uid);
                profileLookupPending = true;
                lastRegisterPromptLookupMs = now;
                runtime::queueProfileLookup(uid);
                loadingAnimationStartedMs = now;
                setUiMode(uiMode, UiMode::Loading, lastUiFrameMs);
            }

            if (lastUiFrameMs == 0 || now - lastUiFrameMs >= kUiIntervalMs) {
                oledDrawThinkingFace(now);
                lastUiFrameMs = now;
            }

            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        if ((uiMode == UiMode::Thinking || uiMode == UiMode::Speaking) &&
            rfidPoll(uid, sizeof(uid))) {
            runtime::storeLastUid(uid);
            runtime::queueBeep(kRfidBeepFreq, kRfidBeepMs);
            Serial.printf("active-mode: interrupted by nfc %s\n", uid);
            runtime::clearPendingExternalAudioSessionState();
            voiceBackendInvalidateCaptureToken();
            transitionToWakeword(uiMode, lastUiFrameMs);
            continue;
        }

        if (shouldPollRfid(uiMode, profileLookupPending) && rfidPoll(uid, sizeof(uid))) {
            runtime::storeLastUid(uid);
            runtime::queueBeep(kRfidBeepFreq, kRfidBeepMs);
            copyText(pendingLookupUid, sizeof(pendingLookupUid), uid);
            profileLookupPending = true;
            lastRegisterPromptLookupMs = now;
            runtime::queueProfileLookup(uid);
            loadingAnimationStartedMs = now;
            setUiMode(uiMode, UiMode::Loading, lastUiFrameMs);
        }

        if (uiMode == UiMode::RegisterPrompt && !profileLookupPending &&
            pendingLookupUid[0] != '\0' &&
            (lastRegisterPromptLookupMs == 0 ||
             now - lastRegisterPromptLookupMs >= kRegisterPromptRecheckMs)) {
            profileLookupPending = true;
            lastRegisterPromptLookupMs = now;
            runtime::queueProfileLookup(pendingLookupUid);
        }

        runtime::ProfileLookupResult lookupResult = {};
        if (runtime::tryPopProfileLookupResult(lookupResult) &&
            std::strcmp(lookupResult.uid, pendingLookupUid) == 0) {
            profileLookupPending = false;

            if (!lookupResult.requestOk) {
                setUiMode(uiMode, UiMode::LookupError, lastUiFrameMs);
            } else if (profileIsComplete(lookupResult.status)) {
                copyText(greetingName, sizeof(greetingName), lookupResult.status.name);
                greetingStartedMs = now;
                setUiMode(uiMode, UiMode::Greeting, lastUiFrameMs);
            } else {
                buildRegisterQrUrl(registerUrl, sizeof(registerUrl), lookupResult.uid);
                setUiMode(uiMode, UiMode::RegisterPrompt, lastUiFrameMs);
            }
        }

        if (uiMode == UiMode::Greeting &&
            greetingStartedMs > 0 &&
            now - greetingStartedMs >= kGreetingDurationMs) {
            transitionToWakeword(uiMode, lastUiFrameMs);
        }

        if (uiMode == UiMode::WaitWakeword && runtime::consumeWakewordTransition()) {
            setUiMode(uiMode, UiMode::Streaming, lastUiFrameMs);
        }

        const bool canApplyExternalState = uiModeCanApplyExternalAudioSessionState(uiMode);
        ExternalAudioSessionState nextExternalState = ExternalAudioSessionState::WaitWakeword;
        if (canApplyExternalState && runtime::consumeExternalAudioSessionState(nextExternalState)) {
            if (nextExternalState == ExternalAudioSessionState::WaitWakeword) {
                transitionToWakeword(uiMode, lastUiFrameMs);
            } else {
                setUiMode(uiMode, uiModeForExternalAudioSessionState(nextExternalState), lastUiFrameMs);
            }
        }

        if (lastUiFrameMs == 0 || now - lastUiFrameMs >= kUiIntervalMs) {
            const AppState snapshot = runtime::loadAppStateSnapshot();

            switch (uiMode) {
                case UiMode::WifiReconnect:
                    oledDrawWifiReconnect(now - reconnectStartedMs);
                    break;
                case UiMode::AwaitNfc:
                    oledDrawAwaitNfc();
                    break;
                case UiMode::Loading:
                    oledDrawLoading(now - loadingAnimationStartedMs);
                    break;
                case UiMode::LookupError:
                    oledDrawLookupError();
                    break;
                case UiMode::RegisterPrompt:
                    oledDrawRegistrationPrompt(registerUrl);
                    break;
                case UiMode::Greeting:
                    oledDrawGreeting(greetingName);
                    break;
                case UiMode::WaitWakeword:
                    oledDrawWakewordSleep();
                    break;
                case UiMode::Streaming:
                    oledDrawStreamingFace(snapshot.latestAudio.samples, snapshot.latestAudio.len);
                    serialSendPlotter(snapshot.latestAudio.samples, snapshot.latestAudio.len, 0);
                    break;
                case UiMode::Thinking:
                    oledDrawThinkingFace(now);
                    break;
                case UiMode::Speaking:
                    oledDrawSpeakingFace(snapshot.playbackAudio.samples,
                                         snapshot.playbackAudio.len,
                                         now);
                    serialSendPlotter(snapshot.playbackAudio.samples, snapshot.playbackAudio.len, 0);
                    break;
                case UiMode::Splash:
                    break;
            }

            lastUiFrameMs = now;
        }

        vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
    }
}

void beepTask(void *param) {
    (void)param;

    runtime::BeepRequest request = {};

    for (;;) {
        if (scheduleAlertActive()) {
            runtime::resetBeepQueue();
            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        if (!runtime::waitBeep(request, portMAX_DELAY)) {
            continue;
        }

        if (runtime::isAudioSessionActive()) {
            continue;
        }

        audioBeep(request.freq, request.durationMs);
    }
}

void createTask(TaskFunction_t taskFn,
                const char *name,
                uint32_t stackSize,
                UBaseType_t priority,
                BaseType_t coreId) {
    if (xTaskCreatePinnedToCore(taskFn, name, stackSize, nullptr, priority, nullptr, coreId) ==
        pdPASS) {
        return;
    }

    Serial.printf("Failed to create task: %s\n", name);
    for (;;) {
        delay(1000);
    }
}
}  // namespace

void appTasksStart() {
    if (gTasksStarted) {
        return;
    }

    if (!runtime::init()) {
        Serial.println("Failed to allocate RTOS primitives");
        for (;;) {
            delay(1000);
        }
    }

    gTasksStarted = true;

    createTask(audioCaptureTask, "audio_capture", 4096, kCaptureTaskPriority, kAudioCore);
    createTask(wakewordTask, "wakeword", 16384, kWakewordTaskPriority, kAudioCore);
    createTask(networkTask, "network", kNetworkTaskStackBytes, kNetworkTaskPriority, kNetworkCore);
    createTask(profileLookupTask, "profile_lookup", 8192, kProfileTaskPriority, kNetworkCore);
    createTask(uiTask, "ui", 6144, kUiTaskPriority, kNetworkCore);
    createTask(beepTask, "beep", 4096, kBeepTaskPriority, kNetworkCore);
    scheduleInit();
}

void appRequestExternalAudioSessionState(ExternalAudioSessionState nextState) {
    runtime::requestExternalAudioSessionState(nextState);
}

void appQueueAssistantPlayback(const AssistantPlaybackRequest &request) {
    runtime::queueAssistantPlayback(request);
}

const char *appExternalAudioSessionStateName(ExternalAudioSessionState state) {
    switch (state) {
        case ExternalAudioSessionState::WaitWakeword:
            return "wait_wakeword";
        case ExternalAudioSessionState::Streaming:
            return "streaming";
        case ExternalAudioSessionState::Thinking:
            return "thinking";
        case ExternalAudioSessionState::Speaking:
            return "speaking";
    }

    return "wait_wakeword";
}

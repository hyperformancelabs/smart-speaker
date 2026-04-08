#include "rtos/app_tasks.h"

#include <cctype>
#include <cstring>

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "app_config.h"
#include "app_state.h"
#include "audio/audio_service.h"
#include "net/profile_service.h"
#include "net/wifi_service.h"
#include "net/ws_service.h"
#include "secrets.h"
#include "sensors/rfid_service.h"
#include "ui/oled_view.h"
#include "ui/serial_telemetry.h"
#include "wakeword/wakeword_service.h"

namespace {
constexpr BaseType_t kNetworkCore = 0;
constexpr BaseType_t kAudioCore = 1;

constexpr UBaseType_t kCaptureTaskPriority = 4;
constexpr UBaseType_t kWakewordTaskPriority = 3;
constexpr UBaseType_t kNetworkTaskPriority = 2;
constexpr UBaseType_t kProfileTaskPriority = 1;
constexpr UBaseType_t kUiTaskPriority = 1;
constexpr UBaseType_t kBeepTaskPriority = 1;

constexpr uint32_t kUiIntervalMs = 200;
constexpr uint32_t kUiSleepMs = 20;
constexpr uint32_t kNetworkSleepMs = 5;
constexpr uint32_t kProfileTaskPollMs = 250;
constexpr unsigned long kWifiReconnectKickMs = 1000;
constexpr unsigned long kProfileWarmupRetryMs = 3000;
constexpr unsigned long kRegisterPromptRecheckMs = 3000;
constexpr size_t kAudioQueueDepth = 8;
constexpr size_t kBeepQueueDepth = 6;
constexpr size_t kProfileLookupQueueDepth = 1;
constexpr int kRfidBeepFreq = 900;
constexpr int kRfidBeepMs = 80;
constexpr unsigned long kGreetingDurationMs = 3000;

enum class UiMode {
    Splash,
    WifiReconnect,
    AwaitNfc,
    Loading,
    LookupError,
    RegisterPrompt,
    Greeting,
    Main,
};

struct BeepRequest {
    int freq = 0;
    int durationMs = 0;
};

struct ProfileLookupRequest {
    char uid[32] = {};
};

struct ProfileLookupResult {
    char uid[32] = {};
    bool requestOk = false;
    ProfileStatus status = {};
};

AppState gAppState = {};
SemaphoreHandle_t gStateMutex = nullptr;
QueueHandle_t gWakewordQueue = nullptr;
QueueHandle_t gStreamQueue = nullptr;
QueueHandle_t gBeepQueue = nullptr;
QueueHandle_t gProfileLookupRequestQueue = nullptr;
QueueHandle_t gProfileLookupResultQueue = nullptr;
bool gTasksStarted = false;
volatile bool gMainFeaturesActive = false;

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

void storeLatestAudio(const AudioChunk &chunk) {
    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.latestAudio = chunk;
    xSemaphoreGive(gStateMutex);
}

void storeWakewordState(const WakewordInfo &wakeword) {
    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.wakeword = wakeword;
    xSemaphoreGive(gStateMutex);
}

void storeLastUid(const char *uid) {
    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    copyText(gAppState.lastUid, sizeof(gAppState.lastUid), uid);
    xSemaphoreGive(gStateMutex);
}

AppState loadAppStateSnapshot() {
    AppState snapshot = {};

    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return snapshot;
    }

    snapshot = gAppState;
    xSemaphoreGive(gStateMutex);
    return snapshot;
}

void pushLatestAudio(QueueHandle_t queue, const AudioChunk &chunk) {
    if (queue == nullptr) {
        return;
    }

    if (xQueueSend(queue, &chunk, 0) == pdPASS) {
        return;
    }

    AudioChunk dropped = {};
    xQueueReceive(queue, &dropped, 0);
    xQueueSend(queue, &chunk, 0);
}

void queueBeep(int freq, int durationMs) {
    if (gBeepQueue == nullptr) {
        return;
    }

    BeepRequest request = {};
    request.freq = freq;
    request.durationMs = durationMs;
    if (xQueueSend(gBeepQueue, &request, 0) == pdPASS) {
        return;
    }

    BeepRequest dropped = {};
    xQueueReceive(gBeepQueue, &dropped, 0);
    xQueueSend(gBeepQueue, &request, 0);
}

void queueProfileLookup(const char *uid) {
    if (gProfileLookupRequestQueue == nullptr || uid == nullptr || uid[0] == '\0') {
        return;
    }

    ProfileLookupRequest request = {};
    copyText(request.uid, sizeof(request.uid), uid);
    xQueueOverwrite(gProfileLookupRequestQueue, &request);
}

bool pollProfileLookupResult(ProfileLookupResult &result) {
    if (gProfileLookupResultQueue == nullptr) {
        return false;
    }

    return xQueueReceive(gProfileLookupResultQueue, &result, 0) == pdPASS;
}

bool areMainFeaturesActive() {
    return gMainFeaturesActive;
}

void resetRealtimeAppState() {
    if (gStateMutex == nullptr) {
        return;
    }

    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.latestAudio = {};
    gAppState.wakeword = {};
    xSemaphoreGive(gStateMutex);
}

bool shouldPollRfid(UiMode uiMode, bool profileLookupPending) {
    if (profileLookupPending) {
        return false;
    }

    switch (uiMode) {
        case UiMode::AwaitNfc:
        case UiMode::LookupError:
        case UiMode::RegisterPrompt:
        case UiMode::Main:
            return true;
        case UiMode::Splash:
        case UiMode::WifiReconnect:
        case UiMode::Loading:
        case UiMode::Greeting:
            return false;
    }

    return false;
}

bool shouldShowWifiReconnect(UiMode uiMode, bool profileLookupPending, WifiConnectionState wifiState) {
    if (wifiState == WifiConnectionState::Ready || profileLookupPending) {
        return false;
    }

    switch (uiMode) {
        case UiMode::AwaitNfc:
        case UiMode::LookupError:
        case UiMode::RegisterPrompt:
        case UiMode::Main:
        case UiMode::WifiReconnect:
            return true;
        case UiMode::Splash:
        case UiMode::Loading:
        case UiMode::Greeting:
            return false;
    }

    return false;
}

void setUiMode(UiMode &uiMode, UiMode nextMode, unsigned long &lastUiFrameMs) {
    if (uiMode == nextMode) {
        return;
    }

    uiMode = nextMode;
    gMainFeaturesActive = (nextMode == UiMode::Main);
    lastUiFrameMs = 0;

    if (!gMainFeaturesActive) {
        resetRealtimeAppState();
    }
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
        queueBeep(WIFI_CONNECTED_BEEP_FREQ, WIFI_CONNECTED_BEEP_MS);
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
        if (!areMainFeaturesActive()) {
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

        storeLatestAudio(chunk);
        pushLatestAudio(gWakewordQueue, chunk);
        pushLatestAudio(gStreamQueue, chunk);
    }
}

void wakewordTask(void *param) {
    (void)param;

    AudioChunk chunk = {};
    WakewordInfo wakeword = {};
    bool wakewordActive = false;

    for (;;) {
        if (!areMainFeaturesActive()) {
            if (wakewordActive) {
                wakewordActive = false;
                wakeword = {};
                storeWakewordState(wakeword);
                if (gWakewordQueue != nullptr) {
                    xQueueReset(gWakewordQueue);
                }
            }

            vTaskDelay(pdMS_TO_TICKS(kUiSleepMs));
            continue;
        }

        if (!wakewordActive) {
            wakewordInit(wakeword);
            storeWakewordState(wakeword);
            wakewordActive = true;
        }

        if (xQueueReceive(gWakewordQueue, &chunk, pdMS_TO_TICKS(kUiSleepMs)) != pdPASS) {
            continue;
        }

        if (wakewordProcessSamples(chunk.samples, chunk.len, wakeword)) {
            queueBeep(WAKEWORD_BEEP_FREQ, WAKEWORD_BEEP_MS);
        }

        storeWakewordState(wakeword);
    }
}

void networkTask(void *param) {
    (void)param;

    AudioChunk chunk = {};
    bool streamingActive = false;

    for (;;) {
        wifiEnsureConnected();

        if (!areMainFeaturesActive()) {
            if (streamingActive) {
                streamingActive = false;
                if (gStreamQueue != nullptr) {
                    xQueueReset(gStreamQueue);
                }
            }

            vTaskDelay(pdMS_TO_TICKS(kNetworkSleepMs));
            continue;
        }

        streamingActive = true;
        wsLoop();

        bool drainedAnyChunk = false;
        while (xQueueReceive(gStreamQueue, &chunk, 0) == pdPASS) {
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

    ProfileLookupRequest lookupRequest = {};
    ProfileLookupResult lookupResult = {};
    bool wifiWasReady = false;
    bool warmupPending = true;
    unsigned long lastWarmupAttemptMs = 0;

    for (;;) {
        const bool wifiReady = wifiIsReady();
        if (wifiReady && !wifiWasReady) {
            warmupPending = true;
        }
        wifiWasReady = wifiReady;

        if (xQueueReceive(gProfileLookupRequestQueue, &lookupRequest, pdMS_TO_TICKS(kProfileTaskPollMs)) !=
            pdPASS) {
            if (!warmupPending || !wifiReady) {
                continue;
            }

            const unsigned long now = millis();
            if (lastWarmupAttemptMs != 0 && now - lastWarmupAttemptMs < kProfileWarmupRetryMs) {
                continue;
            }

            lastWarmupAttemptMs = now;
            warmupPending = !profileWarmupConnection();
            continue;
        }

        wifiEnsureConnected();

        lookupResult = {};
        copyText(lookupResult.uid, sizeof(lookupResult.uid), lookupRequest.uid);
        lookupResult.requestOk = profileFetchStatus(lookupRequest.uid, lookupResult.status);
        if (lookupResult.requestOk) {
            warmupPending = false;
        }
        xQueueOverwrite(gProfileLookupResultQueue, &lookupResult);
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
    // Only used to animate the spinner; loading duration is controlled by
    // the pending lookup/result flow, not by a timeout.
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

    gMainFeaturesActive = false;

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

        if (shouldPollRfid(uiMode, profileLookupPending) && rfidPoll(uid, sizeof(uid))) {
            storeLastUid(uid);
            queueBeep(kRfidBeepFreq, kRfidBeepMs);
            copyText(pendingLookupUid, sizeof(pendingLookupUid), uid);
            profileLookupPending = true;
            lastRegisterPromptLookupMs = now;
            queueProfileLookup(uid);
            loadingAnimationStartedMs = now;
            setUiMode(uiMode, UiMode::Loading, lastUiFrameMs);
        }

        if (uiMode == UiMode::RegisterPrompt && !profileLookupPending &&
            pendingLookupUid[0] != '\0' &&
            (lastRegisterPromptLookupMs == 0 ||
             now - lastRegisterPromptLookupMs >= kRegisterPromptRecheckMs)) {
            profileLookupPending = true;
            lastRegisterPromptLookupMs = now;
            queueProfileLookup(pendingLookupUid);
        }

        ProfileLookupResult lookupResult = {};
        if (pollProfileLookupResult(lookupResult) &&
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
            setUiMode(uiMode, UiMode::Main, lastUiFrameMs);
        }

        if (lastUiFrameMs == 0 || now - lastUiFrameMs >= kUiIntervalMs) {
            const AppState snapshot = loadAppStateSnapshot();

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
                case UiMode::Main:
                    oledDraw(snapshot.latestAudio.samples, snapshot.latestAudio.len,
                             snapshot.wakeword, snapshot.lastUid);
                    serialSendPlotter(snapshot.latestAudio.samples, snapshot.latestAudio.len, 0);
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

    BeepRequest request = {};

    for (;;) {
        if (xQueueReceive(gBeepQueue, &request, portMAX_DELAY) != pdPASS) {
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
}

void appTasksStart() {
    if (gTasksStarted) {
        return;
    }

    gStateMutex = xSemaphoreCreateMutex();
    gWakewordQueue = xQueueCreate(kAudioQueueDepth, sizeof(AudioChunk));
    gStreamQueue = xQueueCreate(kAudioQueueDepth, sizeof(AudioChunk));
    gBeepQueue = xQueueCreate(kBeepQueueDepth, sizeof(BeepRequest));
    gProfileLookupRequestQueue =
        xQueueCreate(kProfileLookupQueueDepth, sizeof(ProfileLookupRequest));
    gProfileLookupResultQueue =
        xQueueCreate(kProfileLookupQueueDepth, sizeof(ProfileLookupResult));

    if (gStateMutex == nullptr || gWakewordQueue == nullptr || gStreamQueue == nullptr ||
        gBeepQueue == nullptr || gProfileLookupRequestQueue == nullptr ||
        gProfileLookupResultQueue == nullptr) {
        Serial.println("Failed to allocate RTOS primitives");
        for (;;) {
            delay(1000);
        }
    }

    gTasksStarted = true;

    // Keep capture/inference on the application core so UI and networking jitter
    // cannot block the audio ingestion path.
    createTask(audioCaptureTask, "audio_capture", 4096, kCaptureTaskPriority, kAudioCore);
    createTask(wakewordTask, "wakeword", 16384, kWakewordTaskPriority, kAudioCore);

    // Keep frame streaming responsive by moving the blocking HTTPS profile lookup
    // into its own task on the network core.
    createTask(networkTask, "network", 8192, kNetworkTaskPriority, kNetworkCore);
    createTask(profileLookupTask, "profile_lookup", 8192, kProfileTaskPriority, kNetworkCore);
    createTask(uiTask, "ui", 6144, kUiTaskPriority, kNetworkCore);
    createTask(beepTask, "beep", 4096, kBeepTaskPriority, kNetworkCore);
}

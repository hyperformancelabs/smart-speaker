#include "rtos/app_tasks.h"

#include <cstring>

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "app_config.h"
#include "app_state.h"
#include "audio/audio_service.h"
#include "net/wifi_service.h"
#include "net/ws_service.h"
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
constexpr UBaseType_t kUiTaskPriority = 1;
constexpr UBaseType_t kBeepTaskPriority = 1;

constexpr uint32_t kUiIntervalMs = 200;
constexpr uint32_t kUiSleepMs = 20;
constexpr uint32_t kNetworkSleepMs = 5;
constexpr size_t kAudioQueueDepth = 8;
constexpr size_t kBeepQueueDepth = 6;
constexpr int kRfidBeepFreq = 900;
constexpr int kRfidBeepMs = 80;

struct BeepRequest {
    int freq = 0;
    int durationMs = 0;
};

AppState gAppState = {};
SemaphoreHandle_t gStateMutex = nullptr;
QueueHandle_t gWakewordQueue = nullptr;
QueueHandle_t gStreamQueue = nullptr;
QueueHandle_t gBeepQueue = nullptr;
bool gTasksStarted = false;

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

    wakewordInit(wakeword);
    storeWakewordState(wakeword);

    for (;;) {
        if (xQueueReceive(gWakewordQueue, &chunk, portMAX_DELAY) != pdPASS) {
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

    for (;;) {
        wsLoop();
        wifiEnsureConnected();

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

void uiTask(void *param) {
    (void)param;

    unsigned long splashStartedMs = millis();
    unsigned long lastStartupFrameMs = 0;
    unsigned long lastUiFrameMs = 0;
    bool wifiReadyBeeped = false;
    bool startupShowingError = false;
    int pendingCardEvent = 0;
    char uid[32] = {};

    for (;;) {
        if (rfidPoll(uid, sizeof(uid))) {
            storeLastUid(uid);
            pendingCardEvent = 1;
            queueBeep(kRfidBeepFreq, kRfidBeepMs);
        }

        const bool startupActive = handleStartupUi(
            splashStartedMs, lastStartupFrameMs, wifiReadyBeeped, startupShowingError);

        const unsigned long now = millis();
        if (!startupActive && (lastUiFrameMs == 0 || now - lastUiFrameMs >= kUiIntervalMs)) {
            const AppState snapshot = loadAppStateSnapshot();
            oledDraw(snapshot.latestAudio.samples, snapshot.latestAudio.len, snapshot.wakeword,
                     snapshot.lastUid);
            serialSendPlotter(snapshot.latestAudio.samples, snapshot.latestAudio.len,
                              pendingCardEvent);
            pendingCardEvent = 0;
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

    if (gStateMutex == nullptr || gWakewordQueue == nullptr || gStreamQueue == nullptr ||
        gBeepQueue == nullptr) {
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

    // Serialize Wi-Fi/WebSocket work on one core and leave UI/RFID at lower priority.
    createTask(networkTask, "network", 4096, kNetworkTaskPriority, kNetworkCore);
    createTask(uiTask, "ui", 6144, kUiTaskPriority, kNetworkCore);
    createTask(beepTask, "beep", 4096, kBeepTaskPriority, kNetworkCore);
}

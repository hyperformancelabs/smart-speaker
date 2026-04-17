#include "rtos/app_runtime.h"

#include <cstring>

#include <Arduino.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

#include "audio/audio_service.h"

namespace app_runtime {
namespace {
constexpr size_t kAudioQueueDepth = 32;
constexpr size_t kBeepQueueDepth = 6;
constexpr size_t kProfileLookupQueueDepth = 1;
constexpr size_t kPlaybackQueueDepth = 1;
constexpr int kNoPendingExternalAudioSessionState = -1;

AppState gAppState = {};
SemaphoreHandle_t gStateMutex = nullptr;
QueueHandle_t gWakewordQueue = nullptr;
QueueHandle_t gStreamQueue = nullptr;
QueueHandle_t gBeepQueue = nullptr;
QueueHandle_t gProfileLookupRequestQueue = nullptr;
QueueHandle_t gProfileLookupResultQueue = nullptr;
QueueHandle_t gPlaybackQueue = nullptr;
bool gInitialized = false;
portMUX_TYPE gRuntimeMux = portMUX_INITIALIZER_UNLOCKED;
AudioSessionMode gAudioSessionMode = AudioSessionMode::Idle;
bool gWakewordTransitionPending = false;
int gPendingExternalAudioSessionState = kNoPendingExternalAudioSessionState;

enum class DesiredAudioRoute : uint8_t {
    None,
    Capture,
    Playback,
};

void copyText(char dest[], size_t destSize, const char *src) {
    if (dest == nullptr || destSize == 0) {
        return;
    }

    if (src == nullptr) {
        src = "";
    }

    std::strncpy(dest, src, destSize - 1);
    dest[destSize - 1] = '\0';
}

template <typename Item>
void pushBoundedQueue(QueueHandle_t queue, const Item &item) {
    if (queue == nullptr) {
        return;
    }

    if (xQueueSend(queue, &item, 0) == pdPASS) {
        return;
    }

    Item dropped = {};
    xQueueReceive(queue, &dropped, 0);
    xQueueSend(queue, &item, 0);
}

DesiredAudioRoute desiredRouteForMode(AudioSessionMode mode) {
    switch (mode) {
        case AudioSessionMode::WaitWakeword:
        case AudioSessionMode::Streaming:
        case AudioSessionMode::Thinking:
            return DesiredAudioRoute::Capture;
        case AudioSessionMode::Speaking:
            return DesiredAudioRoute::Playback;
        case AudioSessionMode::Idle:
            return DesiredAudioRoute::None;
    }

    return DesiredAudioRoute::None;
}
}  // namespace

bool init() {
    if (gInitialized) {
        return true;
    }

    gStateMutex = xSemaphoreCreateMutex();
    gWakewordQueue = xQueueCreate(kAudioQueueDepth, sizeof(AudioChunk));
    gStreamQueue = xQueueCreate(kAudioQueueDepth, sizeof(AudioChunk));
    gBeepQueue = xQueueCreate(kBeepQueueDepth, sizeof(BeepRequest));
    gPlaybackQueue = xQueueCreate(kPlaybackQueueDepth, sizeof(AssistantPlaybackRequest));
    gProfileLookupRequestQueue =
        xQueueCreate(kProfileLookupQueueDepth, sizeof(ProfileLookupRequest));
    gProfileLookupResultQueue =
        xQueueCreate(kProfileLookupQueueDepth, sizeof(ProfileLookupResult));

    gInitialized = gStateMutex != nullptr && gWakewordQueue != nullptr && gStreamQueue != nullptr &&
                   gBeepQueue != nullptr && gPlaybackQueue != nullptr &&
                   gProfileLookupRequestQueue != nullptr && gProfileLookupResultQueue != nullptr;

    return gInitialized;
}

void storeLatestAudio(const AudioChunk &chunk) {
    if (gStateMutex == nullptr || xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.latestAudio = chunk;
    xSemaphoreGive(gStateMutex);
}

void storePlaybackAudio(const int16_t samples[], int sampleCount) {
    if (gStateMutex == nullptr || xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.playbackAudio = {};
    if (samples != nullptr && sampleCount > 0) {
        const int cappedCount = sampleCount < MIC_DMA_LEN ? sampleCount : MIC_DMA_LEN;
        memcpy(gAppState.playbackAudio.samples,
               samples,
               static_cast<size_t>(cappedCount) * sizeof(int16_t));
        gAppState.playbackAudio.len = static_cast<uint16_t>(cappedCount);
        gAppState.playbackAudio.capturedMs = millis();
    }

    xSemaphoreGive(gStateMutex);
}

void storeWakewordState(const WakewordInfo &wakeword) {
    if (gStateMutex == nullptr || xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.wakeword = wakeword;
    xSemaphoreGive(gStateMutex);
}

void storeLastUid(const char *uid) {
    if (gStateMutex == nullptr || xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    copyText(gAppState.lastUid, sizeof(gAppState.lastUid), uid);
    xSemaphoreGive(gStateMutex);
}

AppState loadAppStateSnapshot() {
    AppState snapshot = {};

    if (gStateMutex == nullptr || xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return snapshot;
    }

    snapshot = gAppState;
    xSemaphoreGive(gStateMutex);
    return snapshot;
}

void clearRealtimeAppState() {
    if (gStateMutex == nullptr || xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.latestAudio = {};
    gAppState.playbackAudio = {};
    gAppState.wakeword = {};
    xSemaphoreGive(gStateMutex);
}

void pushWakewordAudio(const AudioChunk &chunk) {
    pushBoundedQueue(gWakewordQueue, chunk);
}

bool waitWakewordAudio(AudioChunk &chunk, TickType_t timeoutTicks) {
    return gWakewordQueue != nullptr &&
           xQueueReceive(gWakewordQueue, &chunk, timeoutTicks) == pdPASS;
}

void resetWakewordAudioQueue() {
    if (gWakewordQueue != nullptr) {
        xQueueReset(gWakewordQueue);
    }
}

void pushStreamAudio(const AudioChunk &chunk) {
    pushBoundedQueue(gStreamQueue, chunk);
}

bool tryPopStreamAudio(AudioChunk &chunk) {
    return gStreamQueue != nullptr && xQueueReceive(gStreamQueue, &chunk, 0) == pdPASS;
}

void resetStreamAudioQueue() {
    if (gStreamQueue != nullptr) {
        xQueueReset(gStreamQueue);
    }
}

void queueBeep(int freq, int durationMs) {
    BeepRequest request = {};
    request.freq = freq;
    request.durationMs = durationMs;
    pushBoundedQueue(gBeepQueue, request);
}

bool waitBeep(BeepRequest &request, TickType_t timeoutTicks) {
    return gBeepQueue != nullptr &&
           xQueueReceive(gBeepQueue, &request, timeoutTicks) == pdPASS;
}

void queueProfileLookup(const char *uid) {
    if (gProfileLookupRequestQueue == nullptr || uid == nullptr || uid[0] == '\0') {
        return;
    }

    ProfileLookupRequest request = {};
    copyText(request.uid, sizeof(request.uid), uid);
    xQueueOverwrite(gProfileLookupRequestQueue, &request);
}

bool waitProfileLookup(ProfileLookupRequest &request, TickType_t timeoutTicks) {
    return gProfileLookupRequestQueue != nullptr &&
           xQueueReceive(gProfileLookupRequestQueue, &request, timeoutTicks) == pdPASS;
}

void publishProfileLookupResult(const ProfileLookupResult &result) {
    if (gProfileLookupResultQueue != nullptr) {
        xQueueOverwrite(gProfileLookupResultQueue, &result);
    }
}

bool tryPopProfileLookupResult(ProfileLookupResult &result) {
    return gProfileLookupResultQueue != nullptr &&
           xQueueReceive(gProfileLookupResultQueue, &result, 0) == pdPASS;
}

void queueAssistantPlayback(const AssistantPlaybackRequest &request) {
    if (gPlaybackQueue != nullptr) {
        xQueueOverwrite(gPlaybackQueue, &request);
    }
}

bool tryPopAssistantPlayback(AssistantPlaybackRequest &request) {
    return gPlaybackQueue != nullptr && xQueueReceive(gPlaybackQueue, &request, 0) == pdPASS;
}

void setAudioSessionMode(AudioSessionMode nextMode) {
    AudioSessionMode previousMode = AudioSessionMode::Idle;

    taskENTER_CRITICAL(&gRuntimeMux);
    previousMode = gAudioSessionMode;
    if (previousMode == nextMode) {
        taskEXIT_CRITICAL(&gRuntimeMux);
        return;
    }

    gAudioSessionMode = nextMode;
    if (nextMode != AudioSessionMode::WaitWakeword) {
        gWakewordTransitionPending = false;
    }
    taskEXIT_CRITICAL(&gRuntimeMux);

    if (nextMode == AudioSessionMode::Idle) {
        clearRealtimeAppState();
    }

    const DesiredAudioRoute previousRoute = desiredRouteForMode(previousMode);
    const DesiredAudioRoute nextRoute = desiredRouteForMode(nextMode);
    if (previousRoute == nextRoute) {
        return;
    }

    if (nextRoute == DesiredAudioRoute::Playback) {
        audioSetRouteMode(AudioRouteMode::Playback);
    } else if (nextRoute == DesiredAudioRoute::Capture) {
        audioSetRouteMode(AudioRouteMode::Capture);
    }
}

AudioSessionMode audioSessionMode() {
    taskENTER_CRITICAL(&gRuntimeMux);
    const AudioSessionMode currentMode = gAudioSessionMode;
    taskEXIT_CRITICAL(&gRuntimeMux);
    return currentMode;
}

bool isAudioSessionActive() {
    return audioSessionMode() != AudioSessionMode::Idle;
}

bool isMicrophoneCaptureActive() {
    const AudioSessionMode mode = audioSessionMode();
    return mode == AudioSessionMode::WaitWakeword || mode == AudioSessionMode::Streaming;
}

bool isWakewordDetectionActive() {
    return audioSessionMode() == AudioSessionMode::WaitWakeword;
}

bool isStreamingActive() {
    return audioSessionMode() == AudioSessionMode::Streaming;
}

bool isSpeakingActive() {
    return audioSessionMode() == AudioSessionMode::Speaking;
}

void signalWakewordTransition() {
    taskENTER_CRITICAL(&gRuntimeMux);
    gWakewordTransitionPending = true;
    taskEXIT_CRITICAL(&gRuntimeMux);
}

bool consumeWakewordTransition() {
    taskENTER_CRITICAL(&gRuntimeMux);
    const bool pending = gWakewordTransitionPending;
    gWakewordTransitionPending = false;
    taskEXIT_CRITICAL(&gRuntimeMux);
    return pending;
}

void requestExternalAudioSessionState(ExternalAudioSessionState nextState) {
    taskENTER_CRITICAL(&gRuntimeMux);
    gPendingExternalAudioSessionState = static_cast<int>(nextState);
    taskEXIT_CRITICAL(&gRuntimeMux);
}

bool consumeExternalAudioSessionState(ExternalAudioSessionState &nextState) {
    taskENTER_CRITICAL(&gRuntimeMux);
    const int pendingState = gPendingExternalAudioSessionState;
    if (pendingState != kNoPendingExternalAudioSessionState) {
        gPendingExternalAudioSessionState = kNoPendingExternalAudioSessionState;
    }
    taskEXIT_CRITICAL(&gRuntimeMux);

    if (pendingState == kNoPendingExternalAudioSessionState) {
        return false;
    }

    nextState = static_cast<ExternalAudioSessionState>(pendingState);
    return true;
}

void clearPendingExternalAudioSessionState() {
    taskENTER_CRITICAL(&gRuntimeMux);
    gPendingExternalAudioSessionState = kNoPendingExternalAudioSessionState;
    taskEXIT_CRITICAL(&gRuntimeMux);
}

}  // namespace app_runtime

#include "rtos/app_tasks.h"

#include <cctype>
#include <cstring>

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "app_config.h"
#include "app_state.h"
#include "audio/audio_service.h"
#include "net/profile_service.h"
#include "net/voice_backend_service.h"
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
constexpr uint32_t kNetworkTaskStackBytes = 12 * 1024;

constexpr uint32_t kUiIntervalMs = 200;
constexpr uint32_t kUiSleepMs = 20;
constexpr uint32_t kNetworkSleepMs = 5;
constexpr uint32_t kProfileTaskPollMs = 250;
constexpr unsigned long kWifiReconnectKickMs = 1000;
constexpr unsigned long kRegisterPromptRecheckMs = 3000;
constexpr size_t kAudioQueueDepth = 32;
constexpr size_t kBeepQueueDepth = 6;
constexpr size_t kProfileLookupQueueDepth = 1;
constexpr size_t kPlaybackQueueDepth = 1;
constexpr int kRfidBeepFreq = 900;
constexpr int kRfidBeepMs = 80;
constexpr unsigned long kGreetingDurationMs = 3000;
constexpr int kNoPendingExternalAudioSessionState = -1;
constexpr uint16_t kPlaybackHttpConnectTimeoutMs = 2500;
constexpr uint16_t kPlaybackHttpReadTimeoutMs = 15000;
constexpr uint16_t kPlaybackStreamStartTimeoutMs = 8000;
constexpr uint16_t kPlaybackStreamDisconnectGraceMs = 750;
constexpr size_t kPlaybackReadChunkBytes = 1024;
constexpr unsigned long kPlaybackWifiReadyWaitMs = 1500;

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

enum class AudioSessionMode {
    Idle,
    WaitWakeword,
    Streaming,
    Thinking,
    Speaking,
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
QueueHandle_t gPlaybackQueue = nullptr;
bool gTasksStarted = false;
volatile AudioSessionMode gAudioSessionMode = AudioSessionMode::Idle;
volatile bool gWakewordTransitionPending = false;
portMUX_TYPE gExternalAudioSessionStateMux = portMUX_INITIALIZER_UNLOCKED;
volatile int gPendingExternalAudioSessionState = kNoPendingExternalAudioSessionState;
uint8_t gPlaybackCombined[kPlaybackReadChunkBytes + 4] = {};
uint8_t gPlaybackRemainder[4] = {};
int16_t gPlaybackOutputSamples[(kPlaybackReadChunkBytes / sizeof(int16_t) + 4) * 2] = {};
int16_t gPlaybackPreviewSamples[MIC_DMA_LEN] = {};

void resetRealtimeAppState();

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

void storeLatestAudio(const AudioChunk &chunk) {
    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
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
        memcpy(gAppState.playbackAudio.samples, samples, static_cast<size_t>(cappedCount) * sizeof(int16_t));
        gAppState.playbackAudio.len = static_cast<uint16_t>(cappedCount);
        gAppState.playbackAudio.capturedMs = millis();
    }

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

void queueAssistantPlayback(const AssistantPlaybackRequest &request) {
    if (gPlaybackQueue == nullptr) {
        return;
    }

    xQueueOverwrite(gPlaybackQueue, &request);
}

bool pollAssistantPlayback(AssistantPlaybackRequest &request) {
    if (gPlaybackQueue == nullptr) {
        return false;
    }

    return xQueueReceive(gPlaybackQueue, &request, 0) == pdPASS;
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

void clearWakewordTransition() {
    gWakewordTransitionPending = false;
}

void signalWakewordTransition() {
    gWakewordTransitionPending = true;
}

bool consumeWakewordTransition() {
    if (!gWakewordTransitionPending) {
        return false;
    }

    gWakewordTransitionPending = false;
    return true;
}

bool consumeExternalAudioSessionState(ExternalAudioSessionState &nextState) {
    int pendingState = kNoPendingExternalAudioSessionState;

    taskENTER_CRITICAL(&gExternalAudioSessionStateMux);
    pendingState = gPendingExternalAudioSessionState;
    if (pendingState != kNoPendingExternalAudioSessionState) {
        gPendingExternalAudioSessionState = kNoPendingExternalAudioSessionState;
    }
    taskEXIT_CRITICAL(&gExternalAudioSessionStateMux);

    if (pendingState == kNoPendingExternalAudioSessionState) {
        return false;
    }

    nextState = static_cast<ExternalAudioSessionState>(pendingState);
    return true;
}

void clearPendingExternalAudioSessionState() {
    taskENTER_CRITICAL(&gExternalAudioSessionStateMux);
    gPendingExternalAudioSessionState = kNoPendingExternalAudioSessionState;
    taskEXIT_CRITICAL(&gExternalAudioSessionStateMux);
}

void setAudioSessionMode(AudioSessionMode nextMode) {
    if (gAudioSessionMode == nextMode) {
        return;
    }

    const bool leavingStreaming =
        gAudioSessionMode == AudioSessionMode::Streaming &&
        nextMode != AudioSessionMode::Streaming;

    gAudioSessionMode = nextMode;

    if (nextMode != AudioSessionMode::WaitWakeword) {
        clearWakewordTransition();
    }

    if (nextMode == AudioSessionMode::Idle) {
        resetRealtimeAppState();
    }

    if (leavingStreaming) {
        audioResetWsFrames();
    }

    if (nextMode == AudioSessionMode::Speaking) {
        audioSetRouteMode(AudioRouteMode::Playback);
    } else if (nextMode == AudioSessionMode::WaitWakeword ||
               nextMode == AudioSessionMode::Streaming ||
               nextMode == AudioSessionMode::Thinking) {
        audioSetRouteMode(AudioRouteMode::Capture);
    }
}

bool isAudioSessionActive() {
    return gAudioSessionMode != AudioSessionMode::Idle;
}

bool isMicrophoneCaptureActive() {
    return gAudioSessionMode == AudioSessionMode::WaitWakeword ||
           gAudioSessionMode == AudioSessionMode::Streaming;
}

bool isWakewordDetectionActive() {
    return gAudioSessionMode == AudioSessionMode::WaitWakeword;
}

bool isStreamingActive() {
    return gAudioSessionMode == AudioSessionMode::Streaming;
}

bool isSpeakingActive() {
    return gAudioSessionMode == AudioSessionMode::Speaking;
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

void resetRealtimeAppState() {
    if (gStateMutex == nullptr) {
        return;
    }

    if (xSemaphoreTake(gStateMutex, portMAX_DELAY) != pdTRUE) {
        return;
    }

    gAppState.latestAudio = {};
    gAppState.playbackAudio = {};
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
        case UiMode::WaitWakeword:
        case UiMode::Streaming:
            return true;
        case UiMode::Thinking:
        case UiMode::Speaking:
            return false;
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

void setUiMode(UiMode &uiMode, UiMode nextMode, unsigned long &lastUiFrameMs) {
    if (uiMode == nextMode) {
        return;
    }

    Serial.printf("ui: %s -> %s\n", uiModeName(uiMode), uiModeName(nextMode));
    uiMode = nextMode;
    setAudioSessionMode(audioSessionModeForUi(nextMode));
    if (nextMode == UiMode::WaitWakeword) {
        clearPendingExternalAudioSessionState();
        voiceBackendInvalidateCaptureToken();
    }
    lastUiFrameMs = 0;
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

bool shouldCancelPlayback(const AssistantPlaybackRequest &request) {
    return !isSpeakingActive() || !voiceBackendCaptureTokenMatches(request.captureToken);
}

uint16_t readLe16(const uint8_t *data) {
    return static_cast<uint16_t>(data[0]) |
           (static_cast<uint16_t>(data[1]) << 8);
}

uint32_t readLe32(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

struct WavStreamInfo {
    uint16_t audioFormat = 0;
    uint16_t channels = 0;
    uint32_t sampleRate = 0;
    uint16_t bitsPerSample = 0;
};

bool readExactFromStream(Stream &stream,
                         uint8_t *buffer,
                         size_t length,
                         const AssistantPlaybackRequest &request) {
    size_t filled = 0;
    unsigned long lastProgressMs = millis();

    while (filled < length) {
        if (shouldCancelPlayback(request)) {
            return false;
        }

        const int availableBytes = stream.available();
        if (availableBytes <= 0) {
            if (millis() - lastProgressMs >= kPlaybackHttpReadTimeoutMs) {
                return false;
            }

            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        const size_t chunkBytes =
            static_cast<size_t>(availableBytes) < (length - filled)
                ? static_cast<size_t>(availableBytes)
                : (length - filled);
        const size_t readBytes =
            stream.readBytes(reinterpret_cast<char *>(buffer + filled), chunkBytes);
        if (readBytes == 0) {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }

        filled += readBytes;
        lastProgressMs = millis();
    }

    return true;
}

bool skipStreamBytes(Stream &stream,
                     size_t bytesToSkip,
                     const AssistantPlaybackRequest &request) {
    uint8_t scratch[64] = {};
    while (bytesToSkip > 0) {
        const size_t chunkBytes = bytesToSkip < sizeof(scratch) ? bytesToSkip : sizeof(scratch);
        if (!readExactFromStream(stream, scratch, chunkBytes, request)) {
            return false;
        }
        bytesToSkip -= chunkBytes;
    }

    return true;
}

bool readWavHeader(Stream &stream,
                   const AssistantPlaybackRequest &request,
                   WavStreamInfo &info) {
    uint8_t riffHeader[12] = {};
    if (!readExactFromStream(stream, riffHeader, sizeof(riffHeader), request)) {
        return false;
    }

    if (memcmp(riffHeader, "RIFF", 4) != 0 || memcmp(riffHeader + 8, "WAVE", 4) != 0) {
        Serial.println("playback: unsupported WAV header");
        return false;
    }

    bool haveFormat = false;
    for (;;) {
        uint8_t chunkHeader[8] = {};
        if (!readExactFromStream(stream, chunkHeader, sizeof(chunkHeader), request)) {
            return false;
        }

        const uint32_t chunkSize = readLe32(chunkHeader + 4);
        const bool paddedChunk = (chunkSize % 2U) != 0U;

        if (memcmp(chunkHeader, "fmt ", 4) == 0) {
            if (chunkSize < 16U) {
                Serial.println("playback: invalid fmt chunk");
                return false;
            }

            uint8_t formatChunk[16] = {};
            if (!readExactFromStream(stream, formatChunk, sizeof(formatChunk), request)) {
                return false;
            }

            info.audioFormat = readLe16(formatChunk + 0);
            info.channels = readLe16(formatChunk + 2);
            info.sampleRate = readLe32(formatChunk + 4);
            info.bitsPerSample = readLe16(formatChunk + 14);
            haveFormat = true;

            if (chunkSize > sizeof(formatChunk) &&
                !skipStreamBytes(stream, chunkSize - sizeof(formatChunk), request)) {
                return false;
            }
        } else if (memcmp(chunkHeader, "data", 4) == 0) {
            if (!haveFormat) {
                Serial.println("playback: missing fmt before data");
                return false;
            }

            if (info.audioFormat != 1 || info.bitsPerSample != 16 ||
                (info.channels != 1 && info.channels != 2) ||
                info.sampleRate != static_cast<uint32_t>(SPK_SAMPLE_RATE)) {
                Serial.printf(
                    "playback: unsupported format=%u channels=%u rate=%lu bits=%u\n",
                    info.audioFormat,
                    info.channels,
                    static_cast<unsigned long>(info.sampleRate),
                    info.bitsPerSample);
                return false;
            }

            Serial.printf("playback: wav fmt channels=%u rate=%lu bits=%u\n",
                          info.channels,
                          static_cast<unsigned long>(info.sampleRate),
                          info.bitsPerSample);
            return true;
        } else {
            if (!skipStreamBytes(stream, chunkSize, request)) {
                return false;
            }
        }

        if (paddedChunk && !skipStreamBytes(stream, 1, request)) {
            return false;
        }
    }
}

void writePlaybackChunk(const uint8_t *pcmBytes,
                        size_t byteCount,
                        const WavStreamInfo &info) {
    if (pcmBytes == nullptr || byteCount == 0) {
        return;
    }

    const size_t frameBytes = static_cast<size_t>(info.channels) * sizeof(int16_t);
    if (frameBytes == 0 || byteCount < frameBytes) {
        return;
    }

    const size_t frameCount = byteCount / frameBytes;
    size_t outputCount = 0;
    int previewCount = 0;

    for (size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
        const size_t offset = frameIndex * frameBytes;
        const int16_t left =
            static_cast<int16_t>(readLe16(pcmBytes + offset));
        int16_t right = left;
        if (info.channels == 2) {
            right = static_cast<int16_t>(readLe16(pcmBytes + offset + sizeof(int16_t)));
        }

        gPlaybackOutputSamples[outputCount++] = left;
        gPlaybackOutputSamples[outputCount++] = right;
        if (previewCount < MIC_DMA_LEN) {
            gPlaybackPreviewSamples[previewCount++] =
                static_cast<int16_t>((static_cast<int32_t>(left) + static_cast<int32_t>(right)) / 2);
        }
    }

    audioWriteOutputSamples(gPlaybackOutputSamples, outputCount);
    storePlaybackAudio(gPlaybackPreviewSamples, previewCount);
}

class WavPlaybackSink : public Stream {
public:
    explicit WavPlaybackSink(const AssistantPlaybackRequest &request)
        : mRequest(request) {}

    using Print::write;

    int available() override {
        return 0;
    }

    int read() override {
        return -1;
    }

    int peek() override {
        return -1;
    }

    void flush() override {
        finish();
    }

    size_t write(uint8_t value) override {
        return write(&value, 1);
    }

    size_t write(const uint8_t *buffer, size_t size) override {
        if (buffer == nullptr || size == 0) {
            return 0;
        }

        size_t offset = 0;
        while (offset < size) {
            if (mCanceled || mError) {
                return offset;
            }
            if (shouldCancelPlayback(mRequest)) {
                mCanceled = true;
                return offset;
            }

            switch (mState) {
                case State::RiffHeader:
                    offset += appendPending(buffer + offset, size - offset, 12);
                    if (mPendingLen == 12) {
                        if (memcmp(mPending, "RIFF", 4) != 0 ||
                            memcmp(mPending + 8, "WAVE", 4) != 0) {
                            setError("unsupported WAV header");
                            return offset;
                        }
                        mPendingLen = 0;
                        mState = State::ChunkHeader;
                    }
                    break;

                case State::ChunkHeader:
                    offset += appendPending(buffer + offset, size - offset, 8);
                    if (mPendingLen == 8) {
                        memcpy(mChunkId, mPending, sizeof(mChunkId));
                        mChunkSize = readLe32(mPending + 4);
                        mChunkHasPad = (mChunkSize % 2U) != 0U;
                        mPendingLen = 0;

                        if (memcmp(mChunkId, "fmt ", 4) == 0) {
                            if (mChunkSize < 16U) {
                                setError("invalid fmt chunk");
                                return offset;
                            }
                            mState = State::FmtBody;
                        } else if (memcmp(mChunkId, "data", 4) == 0) {
                            if (!mHaveFormat) {
                                setError("missing fmt before data");
                                return offset;
                            }
                            mSawDataChunk = true;
                            mDataHasKnownLength = mChunkSize != 0xFFFFFFFFU;
                            mDataBytesRemaining = mChunkSize;
                            Serial.printf("playback: wav fmt channels=%u rate=%lu bits=%u\n",
                                          mInfo.channels,
                                          static_cast<unsigned long>(mInfo.sampleRate),
                                          mInfo.bitsPerSample);
                            mState = State::Data;
                        } else {
                            mSkipBytesRemaining =
                                static_cast<size_t>(mChunkSize) + (mChunkHasPad ? 1U : 0U);
                            mState = State::SkipBytes;
                        }
                    }
                    break;

                case State::FmtBody:
                    offset += appendPending(buffer + offset, size - offset, 16);
                    if (mPendingLen == 16) {
                        mInfo.audioFormat = readLe16(mPending + 0);
                        mInfo.channels = readLe16(mPending + 2);
                        mInfo.sampleRate = readLe32(mPending + 4);
                        mInfo.bitsPerSample = readLe16(mPending + 14);
                        mPendingLen = 0;

                        if (mInfo.audioFormat != 1 || mInfo.bitsPerSample != 16 ||
                            (mInfo.channels != 1 && mInfo.channels != 2) ||
                            mInfo.sampleRate != static_cast<uint32_t>(SPK_SAMPLE_RATE)) {
                            char bufferMsg[96] = {};
                            snprintf(bufferMsg,
                                     sizeof(bufferMsg),
                                     "unsupported format=%u channels=%u rate=%lu bits=%u",
                                     mInfo.audioFormat,
                                     mInfo.channels,
                                     static_cast<unsigned long>(mInfo.sampleRate),
                                     mInfo.bitsPerSample);
                            setError(bufferMsg);
                            return offset;
                        }

                        mHaveFormat = true;
                        mSkipBytesRemaining =
                            static_cast<size_t>(mChunkSize - 16U) + (mChunkHasPad ? 1U : 0U);
                        mState =
                            mSkipBytesRemaining > 0 ? State::SkipBytes : State::ChunkHeader;
                    }
                    break;

                case State::SkipBytes: {
                    const size_t skipBytes =
                        (size - offset) < mSkipBytesRemaining ? (size - offset) : mSkipBytesRemaining;
                    offset += skipBytes;
                    mSkipBytesRemaining -= skipBytes;
                    if (mSkipBytesRemaining == 0) {
                        mState = State::ChunkHeader;
                    }
                    break;
                }

                case State::Data: {
                    size_t consumable = size - offset;
                    if (mDataHasKnownLength &&
                        consumable > static_cast<size_t>(mDataBytesRemaining)) {
                        consumable = static_cast<size_t>(mDataBytesRemaining);
                    }

                    if (consumable == 0) {
                        if (mDataHasKnownLength && mDataBytesRemaining == 0) {
                            mSkipBytesRemaining = mChunkHasPad ? 1U : 0U;
                            mState =
                                mSkipBytesRemaining > 0 ? State::SkipBytes : State::ChunkHeader;
                            continue;
                        }
                        return offset;
                    }

                    consumePcmBytes(buffer + offset, consumable);
                    offset += consumable;
                    mSawPayloadData = true;

                    if (mDataHasKnownLength) {
                        mDataBytesRemaining -= static_cast<uint32_t>(consumable);
                        if (mDataBytesRemaining == 0) {
                            mSkipBytesRemaining = mChunkHasPad ? 1U : 0U;
                            mState =
                                mSkipBytesRemaining > 0 ? State::SkipBytes : State::ChunkHeader;
                        }
                    }
                    break;
                }
            }
        }

        return size;
    }

    bool finish() {
        if (mFinished) {
            return !mError && !mCanceled && mSawDataChunk && mSawPayloadData;
        }

        mFinished = true;
        flushPlayablePcm();

        if (mCanceled) {
            return false;
        }
        if (!mSawDataChunk) {
            setError("missing WAV data chunk");
        } else if (!mSawPayloadData) {
            setError("WAV payload empty");
        }

        return !mError;
    }

    const char *errorMessage() const {
        return mErrorMessage[0] != '\0' ? mErrorMessage : "unknown playback error";
    }

private:
    enum class State {
        RiffHeader,
        ChunkHeader,
        FmtBody,
        SkipBytes,
        Data,
    };

    size_t appendPending(const uint8_t *buffer, size_t availableBytes, size_t targetBytes) {
        const size_t neededBytes = targetBytes - mPendingLen;
        const size_t copyBytes = availableBytes < neededBytes ? availableBytes : neededBytes;
        memcpy(mPending + mPendingLen, buffer, copyBytes);
        mPendingLen += copyBytes;
        return copyBytes;
    }

    void setError(const char *message) {
        if (mError) {
            return;
        }

        mError = true;
        copyText(mErrorMessage, sizeof(mErrorMessage), message);
        Serial.printf("playback: %s\n", mErrorMessage);
    }

    void consumePcmBytes(const uint8_t *buffer, size_t size) {
        size_t offset = 0;
        while (offset < size) {
            const size_t writable =
                (sizeof(mPcmBuffer) - mPcmBufferLen) < (size - offset)
                    ? (sizeof(mPcmBuffer) - mPcmBufferLen)
                    : (size - offset);
            memcpy(mPcmBuffer + mPcmBufferLen, buffer + offset, writable);
            mPcmBufferLen += writable;
            offset += writable;
            flushPlayablePcm();
        }
    }

    void flushPlayablePcm() {
        const size_t frameBytes = static_cast<size_t>(mInfo.channels) * sizeof(int16_t);
        if (frameBytes == 0 || mPcmBufferLen < frameBytes) {
            return;
        }

        const size_t playableBytes = (mPcmBufferLen / frameBytes) * frameBytes;
        if (playableBytes == 0) {
            return;
        }

        writePlaybackChunk(mPcmBuffer, playableBytes, mInfo);
        const size_t remainingBytes = mPcmBufferLen - playableBytes;
        if (remainingBytes > 0) {
            memmove(mPcmBuffer, mPcmBuffer + playableBytes, remainingBytes);
        }
        mPcmBufferLen = remainingBytes;
    }

    const AssistantPlaybackRequest &mRequest;
    State mState = State::RiffHeader;
    WavStreamInfo mInfo = {};
    uint8_t mPending[16] = {};
    size_t mPendingLen = 0;
    uint8_t mChunkId[4] = {};
    uint32_t mChunkSize = 0;
    bool mChunkHasPad = false;
    bool mHaveFormat = false;
    bool mSawDataChunk = false;
    bool mSawPayloadData = false;
    bool mDataHasKnownLength = false;
    uint32_t mDataBytesRemaining = 0;
    size_t mSkipBytesRemaining = 0;
    uint8_t mPcmBuffer[kPlaybackReadChunkBytes + 4] = {};
    size_t mPcmBufferLen = 0;
    bool mCanceled = false;
    bool mError = false;
    bool mFinished = false;
    char mErrorMessage[96] = {};
};

bool playIdentityWavStream(Stream &stream,
                           HTTPClient &http,
                           const AssistantPlaybackRequest &request) {
    WavStreamInfo info = {};
    if (!readWavHeader(stream, request, info)) {
        return false;
    }

    size_t remainderLen = 0;
    const size_t frameBytes = static_cast<size_t>(info.channels) * sizeof(int16_t);
    unsigned long lastDataMs = millis();
    bool sawPayloadData = false;

    while (http.connected() || stream.available() > 0) {
        if (shouldCancelPlayback(request)) {
            return false;
        }

        const int availableBytes = stream.available();
        if (availableBytes <= 0) {
            if (millis() - lastDataMs >= kPlaybackHttpReadTimeoutMs) {
                break;
            }

            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        const size_t payloadBytes =
            static_cast<size_t>(availableBytes) < kPlaybackReadChunkBytes
                ? static_cast<size_t>(availableBytes)
                : kPlaybackReadChunkBytes;

        memcpy(gPlaybackCombined, gPlaybackRemainder, remainderLen);
        const size_t readBytes = stream.readBytes(
            reinterpret_cast<char *>(gPlaybackCombined + remainderLen),
            payloadBytes);
        if (readBytes == 0) {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }

        sawPayloadData = true;
        lastDataMs = millis();
        const size_t totalBytes = remainderLen + readBytes;
        const size_t playableBytes = (totalBytes / frameBytes) * frameBytes;
        if (playableBytes > 0) {
            writePlaybackChunk(gPlaybackCombined, playableBytes, info);
        }

        remainderLen = totalBytes - playableBytes;
        if (remainderLen > 0) {
            memcpy(gPlaybackRemainder, gPlaybackCombined + playableBytes, remainderLen);
        }
    }

    if (remainderLen > 0) {
        writePlaybackChunk(gPlaybackRemainder, remainderLen - (remainderLen % frameBytes), info);
    }

    if (!sawPayloadData) {
        Serial.println("playback: identity WAV stream ended before payload data arrived");
        return false;
    }

    return !shouldCancelPlayback(request);
}

bool playWavStream(HTTPClient &http, const AssistantPlaybackRequest &request) {
    const int code = http.GET();
    if (code != HTTP_CODE_OK) {
        if (code < 0) {
            Serial.printf("playback: request failed %s (%d)\n",
                          HTTPClient::errorToString(code).c_str(),
                          code);
        } else {
            Serial.printf("playback: HTTP %d\n", code);
        }
        return false;
    }

    if (http.getSize() > 0) {
        Stream *stream = http.getStreamPtr();
        if (stream == nullptr) {
            Serial.println("playback: missing identity response stream");
            return false;
        }

        Serial.printf("playback: using identity stream path size=%d\n", http.getSize());
        return playIdentityWavStream(*stream, http, request);
    }

    WavPlaybackSink sink(request);
    Serial.println("playback: using chunked/unknown-length stream path");
    const int writtenBytes = http.writeToStream(&sink);
    const bool finished = sink.finish();

    if (writtenBytes < 0) {
        Serial.printf("playback: stream transfer failed %s (%d)\n",
                      HTTPClient::errorToString(writtenBytes).c_str(),
                      writtenBytes);
        return false;
    }

    if (!finished) {
        Serial.printf("playback: sink failed %s\n", sink.errorMessage());
        return false;
    }

    return !shouldCancelPlayback(request);
}

bool playWavUrl(const char *url, const AssistantPlaybackRequest &request) {
    if (url == nullptr || url[0] == '\0') {
        return true;
    }

    if (!wifiWaitUntilReady(kPlaybackWifiReadyWaitMs)) {
        Serial.println("playback: Wi-Fi not ready");
        return false;
    }

    const String playbackUrl(url);
    const bool useTls = playbackUrl.startsWith("https://");
    Serial.printf("playback: begin %s free_heap=%u stack_high_water=%u\n",
                  playbackUrl.c_str(),
                  ESP.getFreeHeap(),
                  static_cast<unsigned>(uxTaskGetStackHighWaterMark(nullptr)));

    if (useTls) {
        WiFiClientSecure client;
        client.setInsecure();
        HTTPClient http;
        http.setConnectTimeout(kPlaybackHttpConnectTimeoutMs);
        http.setTimeout(kPlaybackHttpReadTimeoutMs);
        if (!http.begin(client, playbackUrl)) {
            Serial.printf("playback: failed to begin %s\n", playbackUrl.c_str());
            return false;
        }

        const bool ok = playWavStream(http, request);
        http.end();
        return ok;
    }

    WiFiClient client;
    HTTPClient http;
    http.setConnectTimeout(kPlaybackHttpConnectTimeoutMs);
    http.setTimeout(kPlaybackHttpReadTimeoutMs);
    if (!http.begin(client, playbackUrl)) {
        Serial.printf("playback: failed to begin %s\n", playbackUrl.c_str());
        return false;
    }

    const bool ok = playWavStream(http, request);
    http.end();
    return ok;
}

bool runAssistantPlayback(const AssistantPlaybackRequest &request) {
    bool ttsOk = true;
    bool mediaOk = true;

    if (request.ttsUrl[0] != '\0') {
        Serial.printf("playback: starting tts url=%s\n", request.ttsUrl);
        ttsOk = playWavUrl(request.ttsUrl, request);
        Serial.printf("playback: tts %s\n", ttsOk ? "completed" : "failed");
    }
    if (!shouldCancelPlayback(request) && request.mediaUrl[0] != '\0') {
        Serial.printf("playback: starting media title=%s url=%s\n",
                      request.mediaTitle[0] != '\0' ? request.mediaTitle : "<untitled>",
                      request.mediaUrl);
        mediaOk = playWavUrl(request.mediaUrl, request);
        Serial.printf("playback: media %s title=%s\n",
                      mediaOk ? "completed" : "failed",
                      request.mediaTitle[0] != '\0' ? request.mediaTitle : "<untitled>");
    }

    storePlaybackAudio(nullptr, 0);
    if (!ttsOk || !mediaOk) {
        Serial.printf("playback: stage result tts_ok=%s media_ok=%s\n",
                      ttsOk ? "yes" : "no",
                      mediaOk ? "yes" : "no");
    }
    return !shouldCancelPlayback(request);
}

void audioCaptureTask(void *param) {
    (void)param;

    AudioChunk chunk = {};

    for (;;) {
        if (!isMicrophoneCaptureActive()) {
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

        if (isStreamingActive()) {
            storeLatestAudio(chunk);
        }
        if (isWakewordDetectionActive()) {
            pushLatestAudio(gWakewordQueue, chunk);
        }
        if (isStreamingActive()) {
            pushLatestAudio(gStreamQueue, chunk);
        }
    }
}

void wakewordTask(void *param) {
    (void)param;

    AudioChunk chunk = {};
    WakewordInfo wakeword = {};
    bool wakewordActive = false;

    for (;;) {
        if (!isWakewordDetectionActive()) {
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
            signalWakewordTransition();
        }

        storeWakewordState(wakeword);
    }
}

void networkTask(void *param) {
    (void)param;

    AudioChunk chunk = {};
    bool streamingActive = false;
    AssistantPlaybackRequest playbackRequest = {};
    bool hasPlaybackRequest = false;

    for (;;) {
        wifiEnsureConnected();
        wsLoop();

        AssistantPlaybackRequest nextPlayback = {};
        if (pollAssistantPlayback(nextPlayback)) {
            playbackRequest = nextPlayback;
            hasPlaybackRequest = true;
            Serial.printf("playback: queued request tts=%s media=%s\n",
                          playbackRequest.ttsUrl[0] != '\0' ? "yes" : "no",
                          playbackRequest.mediaUrl[0] != '\0' ? "yes" : "no");
        }

        if (hasPlaybackRequest &&
            voiceBackendCaptureTokenMatches(playbackRequest.captureToken) &&
            !isSpeakingActive()) {
            Serial.println("playback: forcing speaking state for queued playback");
            appRequestExternalAudioSessionState(ExternalAudioSessionState::Speaking);
        }

        if (isSpeakingActive()) {
            if (streamingActive) {
                streamingActive = false;
                if (gStreamQueue != nullptr) {
                    xQueueReset(gStreamQueue);
                }
                audioResetWsFrames();
            }

            if (hasPlaybackRequest && !voiceBackendCaptureTokenMatches(playbackRequest.captureToken)) {
                hasPlaybackRequest = false;
                storePlaybackAudio(nullptr, 0);
            }

            if (hasPlaybackRequest) {
                const AssistantPlaybackRequest activePlayback = playbackRequest;
                hasPlaybackRequest = false;
                const bool completed = runAssistantPlayback(activePlayback);
                if (completed && isSpeakingActive() &&
                    voiceBackendCaptureTokenMatches(activePlayback.captureToken)) {
                    appRequestExternalAudioSessionState(activePlayback.finalState);
                }
                continue;
            }

            vTaskDelay(pdMS_TO_TICKS(kNetworkSleepMs));
            continue;
        }

        if (!isStreamingActive()) {
            if (streamingActive) {
                streamingActive = false;
                if (gStreamQueue != nullptr) {
                    xQueueReset(gStreamQueue);
                }
                audioResetWsFrames();
            }
            if (hasPlaybackRequest && !voiceBackendCaptureTokenMatches(playbackRequest.captureToken)) {
                hasPlaybackRequest = false;
            }
            storePlaybackAudio(nullptr, 0);

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

    for (;;) {
        if (xQueueReceive(gProfileLookupRequestQueue, &lookupRequest, pdMS_TO_TICKS(kProfileTaskPollMs)) !=
            pdPASS) {
            continue;
        }

        wifiEnsureConnected();

        lookupResult = {};
        copyText(lookupResult.uid, sizeof(lookupResult.uid), lookupRequest.uid);
        lookupResult.requestOk = profileFetchStatus(lookupRequest.uid, lookupResult.status);
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

    setAudioSessionMode(AudioSessionMode::Idle);

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

        if ((uiMode == UiMode::Thinking || uiMode == UiMode::Speaking) &&
            rfidPoll(uid, sizeof(uid))) {
            storeLastUid(uid);
            queueBeep(kRfidBeepFreq, kRfidBeepMs);
            Serial.printf("active-mode: interrupted by nfc %s\n", uid);
            clearPendingExternalAudioSessionState();
            voiceBackendInvalidateCaptureToken();
            setUiMode(uiMode, UiMode::Streaming, lastUiFrameMs);
            continue;
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
            setUiMode(uiMode, UiMode::WaitWakeword, lastUiFrameMs);
        }

        if (uiMode == UiMode::WaitWakeword && consumeWakewordTransition()) {
            setUiMode(uiMode, UiMode::Streaming, lastUiFrameMs);
        }

        ExternalAudioSessionState nextExternalState = ExternalAudioSessionState::WaitWakeword;
        if (consumeExternalAudioSessionState(nextExternalState) &&
            (uiMode == UiMode::WaitWakeword || uiMode == UiMode::Streaming ||
             uiMode == UiMode::Thinking || uiMode == UiMode::Speaking)) {
            setUiMode(uiMode, uiModeForExternalAudioSessionState(nextExternalState), lastUiFrameMs);
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
                    oledDrawSpeakingFace(
                        snapshot.playbackAudio.samples,
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
    gPlaybackQueue = xQueueCreate(kPlaybackQueueDepth, sizeof(AssistantPlaybackRequest));
    gProfileLookupRequestQueue =
        xQueueCreate(kProfileLookupQueueDepth, sizeof(ProfileLookupRequest));
    gProfileLookupResultQueue =
        xQueueCreate(kProfileLookupQueueDepth, sizeof(ProfileLookupResult));

    if (gStateMutex == nullptr || gWakewordQueue == nullptr || gStreamQueue == nullptr ||
        gBeepQueue == nullptr || gPlaybackQueue == nullptr ||
        gProfileLookupRequestQueue == nullptr || gProfileLookupResultQueue == nullptr) {
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
    createTask(networkTask, "network", kNetworkTaskStackBytes, kNetworkTaskPriority, kNetworkCore);
    createTask(profileLookupTask, "profile_lookup", 8192, kProfileTaskPriority, kNetworkCore);
    createTask(uiTask, "ui", 6144, kUiTaskPriority, kNetworkCore);
    createTask(beepTask, "beep", 4096, kBeepTaskPriority, kNetworkCore);
}

void appRequestExternalAudioSessionState(ExternalAudioSessionState nextState) {
    taskENTER_CRITICAL(&gExternalAudioSessionStateMux);
    gPendingExternalAudioSessionState = static_cast<int>(nextState);
    taskEXIT_CRITICAL(&gExternalAudioSessionStateMux);
}

void appQueueAssistantPlayback(const AssistantPlaybackRequest &request) {
    queueAssistantPlayback(request);
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

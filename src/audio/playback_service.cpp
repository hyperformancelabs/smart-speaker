#include "audio/playback_service.h"

#include <cstring>

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "app_config.h"
#include "audio/audio_service.h"
#include "net/voice_backend_service.h"
#include "net/wifi_service.h"
#include "rtos/app_runtime.h"

namespace {
constexpr uint16_t kPlaybackHttpConnectTimeoutMs = 2500;
constexpr uint16_t kPlaybackHttpReadTimeoutMs = 15000;
constexpr size_t kPlaybackReadChunkBytes = 1024;
constexpr unsigned long kPlaybackWifiReadyWaitMs = 1500;

uint8_t gPlaybackCombined[kPlaybackReadChunkBytes + 4] = {};
uint8_t gPlaybackRemainder[4] = {};
int16_t gPlaybackOutputSamples[(kPlaybackReadChunkBytes / sizeof(int16_t) + 4) * 2] = {};
int16_t gPlaybackPreviewSamples[MIC_DMA_LEN] = {};

struct WavStreamInfo {
    uint16_t audioFormat = 0;
    uint16_t channels = 0;
    uint32_t sampleRate = 0;
    uint16_t bitsPerSample = 0;
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

bool shouldCancelPlayback(const AssistantPlaybackRequest &request) {
    return !app_runtime::isSpeakingActive() || !voiceBackendCaptureTokenMatches(request.captureToken);
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
                Serial.printf("playback: unsupported format=%u channels=%u rate=%lu bits=%u\n",
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
        } else if (!skipStreamBytes(stream, chunkSize, request)) {
            return false;
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
        const int16_t left = static_cast<int16_t>(readLe16(pcmBytes + offset));
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
    app_runtime::storePlaybackAudio(gPlaybackPreviewSamples, previewCount);
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
}  // namespace

bool playbackRunAssistantRequest(const AssistantPlaybackRequest &request) {
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

    app_runtime::storePlaybackAudio(nullptr, 0);
    if (!ttsOk || !mediaOk) {
        Serial.printf("playback: stage result tts_ok=%s media_ok=%s\n",
                      ttsOk ? "yes" : "no",
                      mediaOk ? "yes" : "no");
    }
    return !shouldCancelPlayback(request);
}

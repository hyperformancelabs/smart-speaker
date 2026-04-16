#include "audio/audio_service.h"

#include <math.h>

#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "driver/i2s.h"

#include "app_config.h"
#include "net/ws_service.h"

namespace {
enum class AudioDriverMode {
    Uninitialized,
    Capture,
    Playback,
};

constexpr TickType_t kAudioIoTimeoutTicks = pdMS_TO_TICKS(20);
constexpr TickType_t kAmplifierSettleTicks = pdMS_TO_TICKS(20);
constexpr int kMicrophoneGain = 6;

int16_t gWsFrame[FRAME_SAMPLES] = {};
int gWsFill = 0;
SemaphoreHandle_t gAudioMutex = nullptr;
AudioDriverMode gDriverMode = AudioDriverMode::Uninitialized;

void setAmplifierEnabled(bool enabled);

void ensureAudioMutex() {
    if (gAudioMutex != nullptr) {
        return;
    }

    gAudioMutex = xSemaphoreCreateMutex();
}

bool lockAudioMutex(TickType_t timeoutTicks = portMAX_DELAY) {
    ensureAudioMutex();
    if (gAudioMutex == nullptr) {
        return false;
    }

    return xSemaphoreTake(gAudioMutex, timeoutTicks) == pdTRUE;
}

void unlockAudioMutex() {
    if (gAudioMutex != nullptr) {
        xSemaphoreGive(gAudioMutex);
    }
}

i2s_config_t buildCaptureConfig() {
    i2s_config_t cfg = {};
    cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
    cfg.sample_rate = MIC_SAMPLE_RATE;
    cfg.use_apll = true;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = MIC_DMA_CNT;
    cfg.dma_buf_len = MIC_DMA_LEN;
    cfg.tx_desc_auto_clear = false;
    return cfg;
}

i2s_pin_config_t buildCapturePins() {
    i2s_pin_config_t pinCfg = {};
    pinCfg.bck_io_num = PIN_MIC_BCLK;
    pinCfg.ws_io_num = PIN_MIC_WS;
    pinCfg.data_out_num = I2S_PIN_NO_CHANGE;
    pinCfg.data_in_num = PIN_MIC_SD;
    return pinCfg;
}

i2s_config_t buildPlaybackConfig() {
    i2s_config_t cfg = {};
    cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX);
    cfg.sample_rate = SPK_SAMPLE_RATE;
    cfg.use_apll = true;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = 8;
    cfg.dma_buf_len = 256;
    cfg.tx_desc_auto_clear = true;
    return cfg;
}

i2s_pin_config_t buildPlaybackPins() {
    i2s_pin_config_t pinCfg = {};
    pinCfg.bck_io_num = PIN_SPK_BCLK;
    pinCfg.ws_io_num = PIN_SPK_LRC;
    pinCfg.data_out_num = PIN_SPK_DIN;
    pinCfg.data_in_num = I2S_PIN_NO_CHANGE;
    return pinCfg;
}

void installDriverLocked(AudioDriverMode nextMode) {
    if (gDriverMode == nextMode) {
        return;
    }

    i2s_driver_uninstall(I2S_PORT);

    i2s_config_t cfg = {};
    i2s_pin_config_t pins = {};
    if (nextMode == AudioDriverMode::Capture) {
        cfg = buildCaptureConfig();
        pins = buildCapturePins();
    } else {
        cfg = buildPlaybackConfig();
        pins = buildPlaybackPins();
    }

    const esp_err_t installErr = i2s_driver_install(I2S_PORT, &cfg, 0, nullptr);
    if (installErr != ESP_OK) {
        Serial.printf("audio: i2s_driver_install failed mode=%d err=%d\n",
                      static_cast<int>(nextMode),
                      static_cast<int>(installErr));
        gDriverMode = AudioDriverMode::Uninitialized;
        return;
    }

    const esp_err_t pinErr = i2s_set_pin(I2S_PORT, &pins);
    if (pinErr != ESP_OK) {
        Serial.printf("audio: i2s_set_pin failed mode=%d err=%d\n",
                      static_cast<int>(nextMode),
                      static_cast<int>(pinErr));
        i2s_driver_uninstall(I2S_PORT);
        gDriverMode = AudioDriverMode::Uninitialized;
        return;
    }

    setAmplifierEnabled(nextMode == AudioDriverMode::Playback);
    i2s_zero_dma_buffer(I2S_PORT);
    gDriverMode = nextMode;
    Serial.printf("audio: switched route to %s\n",
                  nextMode == AudioDriverMode::Capture ? "capture" : "playback");
}

AudioDriverMode currentDriverModeLocked() {
    return gDriverMode;
}

void setAmplifierEnabled(bool enabled) {
    digitalWrite(PIN_AMP_SD, enabled ? HIGH : LOW);
}
}

void audioPrepareOutput() {
    pinMode(PIN_AMP_SD, OUTPUT);
    setAmplifierEnabled(false);
    delay(200);
}

void audioEnableOutput() {
    if (!lockAudioMutex()) {
        return;
    }

    setAmplifierEnabled(currentDriverModeLocked() == AudioDriverMode::Playback);
    unlockAudioMutex();
}

void audioLogBootDiagnostics() {
    Serial.printf("boot: reset_reason=%d free_heap=%u\n",
                  static_cast<int>(esp_reset_reason()),
                  ESP.getFreeHeap());
}

void audioInit() {
    ensureAudioMutex();
    audioSetRouteMode(AudioRouteMode::Capture);
}

void audioSetRouteMode(AudioRouteMode mode) {
    const AudioDriverMode nextMode =
        mode == AudioRouteMode::Capture ? AudioDriverMode::Capture : AudioDriverMode::Playback;

    if (!lockAudioMutex()) {
        return;
    }

    installDriverLocked(nextMode);
    unlockAudioMutex();
}

void audioWriteOutputSamples(const int16_t samples[], size_t sampleCount) {
    if (samples == nullptr || sampleCount == 0) {
        return;
    }

    if (!lockAudioMutex()) {
        return;
    }

    if (currentDriverModeLocked() != AudioDriverMode::Playback) {
        unlockAudioMutex();
        return;
    }

    size_t bytesWritten = 0;
    i2s_write(I2S_PORT, samples, sampleCount * sizeof(int16_t), &bytesWritten, portMAX_DELAY);
    unlockAudioMutex();
}

void audioBeep(int freq, int ms) {
    if (freq <= 0 || ms <= 0) {
        return;
    }

    if (!lockAudioMutex()) {
        return;
    }

    const AudioDriverMode previousMode = currentDriverModeLocked();
    installDriverLocked(AudioDriverMode::Playback);
    unlockAudioMutex();
    vTaskDelay(kAmplifierSettleTicks);

    int total = (SPK_SAMPLE_RATE * ms) / 1000;
    int16_t buf[256 * 2];
    double phase = 0;
    const double inc = 2.0 * M_PI * freq / SPK_SAMPLE_RATE;

    while (total > 0) {
        const int n = min(total, 256);
        for (int i = 0; i < n; i++) {
            const int16_t s = static_cast<int16_t>(sin(phase) * 7000);
            phase += inc;
            buf[i * 2] = s;
            buf[i * 2 + 1] = s;
        }
        audioWriteOutputSamples(buf, static_cast<size_t>(n) * 2U);
        total -= n;
    }

    vTaskDelay(pdMS_TO_TICKS(8));

    if (previousMode == AudioDriverMode::Capture) {
        audioSetRouteMode(AudioRouteMode::Capture);
    }
}

void audioReadMic(int16_t rawOut[], int &rawLen) {
    rawLen = 0;
    if (rawOut == nullptr) {
        return;
    }

    if (!lockAudioMutex(kAudioIoTimeoutTicks)) {
        return;
    }

    if (currentDriverModeLocked() != AudioDriverMode::Capture) {
        unlockAudioMutex();
        return;
    }

    static int32_t samples[MIC_DMA_LEN] = {};
    size_t bytesRead = 0;
    const esp_err_t err = i2s_read(
        I2S_PORT,
        samples,
        sizeof(samples),
        &bytesRead,
        kAudioIoTimeoutTicks);
    unlockAudioMutex();

    if (err != ESP_OK || bytesRead == 0) {
        return;
    }

    rawLen = bytesRead / 4;
    if (rawLen > MIC_DMA_LEN) {
        rawLen = MIC_DMA_LEN;
    }

    for (int i = 0; i < rawLen; i++) {
        int32_t s = samples[i];
        s >>= 8;
        s += (s >= 0) ? 0x80 : -0x80;
        s >>= 8;
        s *= kMicrophoneGain;

        if (s > 32767) {
            s = 32767;
        }
        if (s < -32768) {
            s = -32768;
        }

        rawOut[i] = static_cast<int16_t>(s);
    }
}

void audioResetWsFrames() {
    gWsFill = 0;
}

void audioFeedWsFrames(const int16_t rawData[], int rawLen) {
    for (int i = 0; i < rawLen; i++) {
        gWsFrame[gWsFill++] = rawData[i];
        if (gWsFill == FRAME_SAMPLES) {
            wsSendAudioFrame(gWsFrame, FRAME_SAMPLES);
            gWsFill = 0;
        }
    }
}

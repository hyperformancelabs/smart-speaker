#include "audio/audio_service.h"

#include <math.h>
#include "driver/i2s.h"

#include "app_config.h"
#include "net/ws_service.h"

void audioPrepareOutput() {
    pinMode(PIN_AMP_SD, OUTPUT);
    digitalWrite(PIN_AMP_SD, LOW);
    delay(200);
}

void audioEnableOutput() {
    digitalWrite(PIN_AMP_SD, HIGH);
}

void audioInit(bool recordMode) {
    i2s_config_t cfg = {};
    cfg.mode = recordMode
        ? (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX)
        : (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_RX);
    cfg.sample_rate = MIC_SAMPLE_RATE;
    cfg.use_apll = true;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = MIC_DMA_CNT;
    cfg.dma_buf_len = MIC_DMA_LEN;
    cfg.tx_desc_auto_clear = true;

    i2s_pin_config_t pinCfg = {};
    pinCfg.bck_io_num = PIN_SPK_BCLK;
    pinCfg.ws_io_num = PIN_SPK_LRC;
    pinCfg.data_out_num = recordMode ? I2S_PIN_NO_CHANGE : PIN_SPK_DIN;
    pinCfg.data_in_num = PIN_MIC_SD;

    i2s_driver_uninstall(I2S_PORT);
    i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
    i2s_set_pin(I2S_PORT, &pinCfg);
    i2s_zero_dma_buffer(I2S_PORT);
}

void audioBeep(int freq, int ms) {
    int total = (SPK_SAMPLE_RATE * ms) / 1000;
    int16_t buf[256 * 2];
    double phase = 0;
    double inc = 2.0 * M_PI * freq / SPK_SAMPLE_RATE;

    while (total > 0) {
        int n = min(total, 256);
        for (int i = 0; i < n; i++) {
            int16_t s = (int16_t)(sin(phase) * 7000);
            phase += inc;
            buf[i * 2] = s;
            buf[i * 2 + 1] = s;
        }
        size_t bytesWritten = 0;
        i2s_write(I2S_PORT, buf, n * 2 * sizeof(int16_t), &bytesWritten, portMAX_DELAY);
        total -= n;
    }
}

void audioReadMic(int16_t rawOut[], int &rawLen) {
    static int32_t samples[MIC_DMA_LEN];
    size_t bytesRead = 0;

    esp_err_t err = i2s_read(I2S_PORT, samples, sizeof(samples), &bytesRead, portMAX_DELAY);
    if (err != ESP_OK || bytesRead == 0) {
        rawLen = 0;
        return;
    }

    rawLen = bytesRead / 4;
    if (rawLen > MIC_DMA_LEN) rawLen = MIC_DMA_LEN;

    const int gain = 2;

    for (int i = 0; i < rawLen; i++) {
        int32_t s = samples[i];

        s >>= 8;
        s += (s >= 0) ? 0x80 : -0x80;
        s >>= 8;

        s *= gain;

        if (s > 32767) s = 32767;
        if (s < -32768) s = -32768;

        rawOut[i] = (int16_t)s;
    }
}

void audioFeedWsFrames(const int16_t rawData[], int rawLen) {
    static int16_t frame[FRAME_SAMPLES];
    static int fill = 0;

    for (int i = 0; i < rawLen; i++) {
        frame[fill++] = rawData[i];
        if (fill == FRAME_SAMPLES) {
            wsSendAudioFrame(frame, FRAME_SAMPLES);
            fill = 0;
        }
    }
}

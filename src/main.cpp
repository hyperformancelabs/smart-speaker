#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "driver/i2s.h"
#include <math.h>

// --- Pin Mapping ---

// OLED (I2C)
#define PIN_OLED_SDA  21
#define PIN_OLED_SCL  22

// RFID RC522 (SPI)
#define PIN_RFID_SS    5
#define PIN_RFID_RST   4
// Default SPI: SCK=18, MISO=19, MOSI=23

// INMP441 Microphone (I2S RX)
#define PIN_MIC_BCLK  14
#define PIN_MIC_WS    33
#define PIN_MIC_SD    32
#define I2S_MIC       I2S_NUM_0

// MAX98357A Speaker (I2S TX)
#define PIN_SPK_DIN   25
#define PIN_SPK_BCLK  26
#define PIN_SPK_LRC   27
#define PIN_AMP_SD    13
#define I2S_SPK       I2S_NUM_1

// --- Device Configurations ---

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

#define MIC_SAMPLE_RATE 16000
#define MIC_DMA_LEN     256
#define MIC_DMA_CNT     4

#define SPK_SAMPLE_RATE 16000

// --- Sound Functions ---

void i2s_mic_init() {
    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
    cfg.sample_rate = MIC_SAMPLE_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = MIC_DMA_CNT;
    cfg.dma_buf_len = MIC_DMA_LEN;

    i2s_pin_config_t pin_cfg = {};
    pin_cfg.bck_io_num = PIN_MIC_BCLK;
    pin_cfg.ws_io_num  = PIN_MIC_WS;
    pin_cfg.data_in_num = PIN_MIC_SD;
    pin_cfg.data_out_num = I2S_PIN_NO_CHANGE;

    i2s_driver_uninstall(I2S_MIC);
    i2s_driver_install(I2S_MIC, &cfg, 0, NULL);
    i2s_set_pin(I2S_MIC, &pin_cfg);
    i2s_zero_dma_buffer(I2S_MIC);
}

void i2s_spk_init() {
    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
    cfg.sample_rate = SPK_SAMPLE_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.dma_buf_count = 8;
    cfg.dma_buf_len = 256;
    cfg.tx_desc_auto_clear = true;

    i2s_pin_config_t pin_cfg = {};
    pin_cfg.bck_io_num = PIN_SPK_BCLK;
    pin_cfg.ws_io_num  = PIN_SPK_LRC;
    pin_cfg.data_out_num = PIN_SPK_DIN;
    pin_cfg.data_in_num  = I2S_PIN_NO_CHANGE;

    i2s_driver_uninstall(I2S_SPK);
    i2s_driver_install(I2S_SPK, &cfg, 0, NULL);
    i2s_set_pin(I2S_SPK, &pin_cfg);
    i2s_zero_dma_buffer(I2S_SPK);
}

void spk_beep(int freq = 1200, int ms = 80) {
    int total = (SPK_SAMPLE_RATE * ms) / 1000;
    int16_t buf[256 * 2];
    double phase = 0;
    double inc = 2.0 * M_PI * freq / SPK_SAMPLE_RATE;

    while (total > 0) {
        int n = min(total, 256);
        for (int i = 0; i < n; i++) {
            int16_t s = sin(phase) * 7000;
            phase += inc;
            buf[i * 2] = s;
            buf[i * 2 + 1] = s;
        }
        size_t w;
        i2s_write(I2S_SPK, buf, n * 2 * sizeof(int16_t), &w, portMAX_DELAY);
        total -= n;
    }
}

void read_mic(int &rms_out, int &peak_out) {
    static int32_t samples[MIC_DMA_LEN];
    size_t bytes_read = 0;

    esp_err_t err = i2s_read(I2S_MIC, samples, sizeof(samples), &bytes_read, pdMS_TO_TICKS(50));
    if (err != ESP_OK || bytes_read == 0) {
        rms_out = peak_out = 0;
        return;
    }

    int n = bytes_read / 4;
    int64_t sum_sq = 0;
    int32_t peak = 0;

    for (int i = 0; i < n; i++) {
        int32_t v = samples[i] >> 8;
        int32_t av = abs(v);
        if (av > peak) peak = av;
        sum_sq += (int64_t)v * v;
    }

    rms_out = (int)sqrt((double)sum_sq / n);
    peak_out = peak;
}

// --- Display Functions ---

void oled_draw(int rms, int peak, const String &uid) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("ESP32 AUDIO + NFC");

    display.setCursor(0, 14);
    display.print("RMS: ");
    display.println(rms);

    display.setCursor(0, 26);
    display.print("Peak:");
    display.println(peak);

    display.setCursor(0, 38);
    display.println("UID:");
    display.setCursor(0, 50);
    display.println(uid);

    display.display();
}

// --- Main Program ---

void setup() {
    Serial.begin(115200);

    // Initial Amp state
    pinMode(PIN_AMP_SD, OUTPUT);
    digitalWrite(PIN_AMP_SD, LOW);
    delay(200);

    // OLED initialization
    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
    }

    // RFID initialization
    SPI.begin(18, 19, 23, PIN_RFID_SS);
    SPI.setFrequency(1000000); 
    rfid.PCD_Init();

    // Audio initialization
    i2s_mic_init();
    i2s_spk_init();

    // Enable Amp and beep
    digitalWrite(PIN_AMP_SD, HIGH);
    delay(50);
    spk_beep(900, 80);

    Serial.println("System READY.");
}

void loop() {
    static String last_uid = "(no card)";
    static int rms_smooth = 0;

    int rms, peak;
    read_mic(rms, peak);

    rms_smooth = (rms_smooth * 8 + rms * 2) / 10;

    int card_event = 0;
    if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
        last_uid = "";
        for (byte i = 0; i < rfid.uid.size; i++) {
            if (rfid.uid.uidByte[i] < 0x10) last_uid += "0";
            last_uid += String(rfid.uid.uidByte[i], HEX);
            if (i != rfid.uid.size - 1) last_uid += ":";
        }
        last_uid.toUpperCase();

        card_event = 1;
        spk_beep(1200, 100);

        rfid.PICC_HaltA();
        rfid.PCD_StopCrypto1();
    }

    oled_draw(rms_smooth, peak, last_uid);

    // Serial Plotter Output
    Serial.print(">");
    Serial.print("rms:");
    Serial.print(rms_smooth);
    Serial.print(",peak:");
    Serial.print(peak);
    Serial.print(",card:");
    Serial.println(card_event);

    delay(20);
}

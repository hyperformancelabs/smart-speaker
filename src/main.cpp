#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include <MFRC522.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "driver/i2s.h"
#include <math.h>
#include "secrets.h"

#define PIN_OLED_SDA  21
#define PIN_OLED_SCL  22

#define PIN_RFID_SS    16
#define PIN_RFID_RST   17

#define PIN_MIC_BCLK  26
#define PIN_MIC_WS    27
#define PIN_MIC_SD    32

#define PIN_SPK_DIN   25
#define PIN_SPK_BCLK  26
#define PIN_SPK_LRC   27
#define PIN_AMP_SD    13

#define I2S_PORT      I2S_NUM_0

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

#define MIC_SAMPLE_RATE 16000
#define MIC_DMA_LEN     256
#define MIC_DMA_CNT     4

#define SPK_SAMPLE_RATE 16000
#define SERIAL_BAUD_RATE 115200
#define SERIAL_RAW_LINES 32
#define WS_PORT          81
#define WS_RAW_POINTS    24
#define WIFI_TIMEOUT_MS  15000
#define WIFI_RETRY_MS    5000

WebSocketsServer ws_server(WS_PORT);
unsigned long last_wifi_retry_ms = 0;

void wifi_connect() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < WIFI_TIMEOUT_MS) {
        delay(250);
    }
}

void wifi_ensure_connected() {
    if (WiFi.status() == WL_CONNECTED) return;

    unsigned long now = millis();
    if (now - last_wifi_retry_ms < WIFI_RETRY_MS) return;

    last_wifi_retry_ms = now;
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void ws_on_event(uint8_t client_id, WStype_t type, uint8_t *payload, size_t length) {
    (void)payload;
    (void)length;

    if (type == WStype_CONNECTED) {
        ws_server.sendTXT(client_id, "{\"type\":\"hello\",\"transport\":\"ws\"}");
    }
}

void ws_send_telemetry(const int16_t raw_data[], int raw_len, int card_event, const String &uid) {
    if (WiFi.status() != WL_CONNECTED) return;

    char msg[512];
    int used = snprintf(msg, sizeof(msg), "{\"raw\":[");
    if (used < 0 || used >= (int)sizeof(msg)) return;

    int points = min(raw_len, WS_RAW_POINTS);
    for (int i = 0; i < points; i++) {
        int idx = (i * raw_len) / points;
        int written = snprintf(
            msg + used,
            sizeof(msg) - used,
            "%d%s",
            (int)raw_data[idx],
            (i == points - 1) ? "" : ","
        );
        if (written < 0 || written >= (int)(sizeof(msg) - used)) return;
        used += written;
    }

    int written = snprintf(
        msg + used,
        sizeof(msg) - used,
        "],\"card\":%d,\"uid\":\"%s\"}",
        card_event,
        uid.c_str()
    );
    if (written < 0 || written >= (int)(sizeof(msg) - used)) return;

    ws_server.broadcastTXT(msg);
}

void serial_send_plotter(const int16_t raw_data[], int raw_len, int card_event) {
    int points = min(raw_len, SERIAL_RAW_LINES);
    if (points <= 0) {
        Serial.println(">raw:0");
    } else {
        for (int i = 0; i < points; i++) {
            int idx = (i * raw_len) / points;
            if (idx >= raw_len) idx = raw_len - 1;
            Serial.print(">raw:");
            Serial.println(raw_data[idx]);
        }
    }

    Serial.print(">card:");
    Serial.println(card_event);
}

void i2s_init() {
    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_RX);
    cfg.sample_rate = MIC_SAMPLE_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = MIC_DMA_CNT;
    cfg.dma_buf_len = MIC_DMA_LEN;
    cfg.tx_desc_auto_clear = true;

    i2s_pin_config_t pin_cfg = {};
    pin_cfg.bck_io_num = PIN_SPK_BCLK;
    pin_cfg.ws_io_num  = PIN_SPK_LRC;
    pin_cfg.data_out_num = PIN_SPK_DIN;
    pin_cfg.data_in_num  = PIN_MIC_SD;

    i2s_driver_uninstall(I2S_PORT);
    i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
    i2s_set_pin(I2S_PORT, &pin_cfg);
    i2s_zero_dma_buffer(I2S_PORT);
}

void spk_beep(int freq = 1200, int ms = 80) {
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
        size_t w;
        i2s_write(I2S_PORT, buf, n * 2 * sizeof(int16_t), &w, portMAX_DELAY);
        total -= n;
    }
}

void read_mic(int16_t raw_out[], int &raw_len) {
    static int32_t samples[MIC_DMA_LEN];
    size_t bytes_read = 0;

    esp_err_t err = i2s_read(I2S_PORT, samples, sizeof(samples), &bytes_read, pdMS_TO_TICKS(50));
    if (err != ESP_OK || bytes_read == 0) {
        raw_len = 0;
        return;
    }

    raw_len = bytes_read / 4;
    if (raw_len > MIC_DMA_LEN) raw_len = MIC_DMA_LEN;

    for (int i = 0; i < raw_len; i++) {
        int32_t s24 = samples[i] >> 8;
        raw_out[i] = (int16_t)(s24 >> 8);
    }
}

void oled_draw(const int16_t raw_data[], int raw_len, const String &uid) {
    const int wave_left = 0;
    const int wave_right = SCREEN_WIDTH - 1;
    const int wave_top = 20;
    const int wave_bottom = 47;

    display.clearDisplay();
    display.setCursor(0, 0);
    if (WiFi.status() == WL_CONNECTED) {
        display.print("WS:");
        display.println(WiFi.localIP());
    } else {
        display.println("WS: CONNECTING...");
    }

    display.setCursor(0, 10);
    display.print("RAW0:");
    display.println(raw_len > 0 ? raw_data[0] : 0);

    display.drawRect(wave_left, wave_top, SCREEN_WIDTH, wave_bottom - wave_top + 1, SSD1306_WHITE);
    int mid = (wave_top + wave_bottom) / 2;
    display.drawFastHLine(wave_left + 1, mid, SCREEN_WIDTH - 2, SSD1306_WHITE);

    if (raw_len > 1) {
        int prev_y = map((long)raw_data[0], -32768, 32767, wave_bottom - 1, wave_top + 1);
        for (int x = 1; x <= wave_right - 1; x++) {
            int idx = ((x - 1) * raw_len) / (SCREEN_WIDTH - 2);
            if (idx >= raw_len) idx = raw_len - 1;
            int y = map((long)raw_data[idx], -32768, 32767, wave_bottom - 1, wave_top + 1);
            display.drawLine(x, prev_y, x + 1, y, SSD1306_WHITE);
            prev_y = y;
        }
    }

    display.setCursor(0, 54);
    display.print("UID:");
    display.println(uid);

    display.display();
}

void setup() {
    Serial.begin(SERIAL_BAUD_RATE);

    pinMode(PIN_AMP_SD, OUTPUT);
    digitalWrite(PIN_AMP_SD, LOW);
    delay(200);

    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
    }

    SPI.begin(18, 19, 23, PIN_RFID_SS);
    SPI.setFrequency(1000000);
    rfid.PCD_Init();

    i2s_init();

    wifi_connect();
    ws_server.begin();
    ws_server.onEvent(ws_on_event);

    digitalWrite(PIN_AMP_SD, HIGH);
    delay(50);
    spk_beep(900, 80);
}

void loop() {
    static String last_uid = "(no card)";
    static int16_t raw_data[MIC_DMA_LEN];

    ws_server.loop();
    wifi_ensure_connected();

    int raw_len = 0;
    read_mic(raw_data, raw_len);

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

    oled_draw(raw_data, raw_len, last_uid);

    ws_send_telemetry(raw_data, raw_len, card_event, last_uid);
    serial_send_plotter(raw_data, raw_len, card_event);

    delay(20);
}
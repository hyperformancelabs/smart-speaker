#include "ui/oled_view.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <qrcode.h>

#include "app_config.h"
#include "net/wifi_service.h"

namespace {
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
constexpr uint8_t kSpinnerDotCount = 8;
constexpr int8_t kSpinnerOffsetX[kSpinnerDotCount] = {0, 5, 8, 5, 0, -5, -8, -5};
constexpr int8_t kSpinnerOffsetY[kSpinnerDotCount] = {-8, -5, 0, 5, 8, 5, 0, -5};
constexpr int kRegistrationQrSize = SCREEN_HEIGHT;
constexpr int kRegistrationQrQuietModules = 1;
constexpr int kRegistrationTextGap = 4;

struct QrRenderArea {
    int originX = 0;
    int originY = 0;
    int width = 0;
    int height = 0;
};

struct QrRenderLayout {
    int moduleCount = 0;
    int quietModules = 0;
    int pixels = 0;
    int offsetX = 0;
    int offsetY = 0;
};

QrRenderArea gQrRenderArea = {};
QrRenderLayout gQrRenderLayout = {};

void drawCenteredLines(const char *const lines[], uint8_t lineCount, int startY, int lineGap) {
    display.clearDisplay();
    display.setTextSize(1);

    for (uint8_t i = 0; i < lineCount; i++) {
        int16_t textX1 = 0;
        int16_t textY1 = 0;
        uint16_t textWidth = 0;
        uint16_t textHeight = 0;
        display.getTextBounds(lines[i], 0, 0, &textX1, &textY1, &textWidth, &textHeight);
        const int x = (SCREEN_WIDTH - textWidth) / 2;
        const int y = startY + (i * lineGap);

        display.setCursor(x, y);
        display.print(lines[i]);
    }

    display.display();
}

void drawStartupSpinner(int centerX, int centerY, uint8_t activeDot) {
    uint8_t trailDot = (activeDot + kSpinnerDotCount - 1) % kSpinnerDotCount;

    for (uint8_t i = 0; i < kSpinnerDotCount; i++) {
        int x = centerX + kSpinnerOffsetX[i];
        int y = centerY + kSpinnerOffsetY[i];

        if (i == activeDot) {
            display.fillCircle(x, y, 2, SSD1306_WHITE);
        } else if (i == trailDot) {
            display.drawCircle(x, y, 2, SSD1306_WHITE);
        } else {
            display.drawPixel(x, y, SSD1306_WHITE);
        }
    }
}

int mapQrModuleEdgeToPixels(int edge, int totalModules, int pixels) {
    if (totalModules <= 0 || pixels <= 0) {
        return 0;
    }

    return (edge * pixels) / totalModules;
}

QrRenderLayout computeQrRenderLayout(int moduleCount, const QrRenderArea &area) {
    QrRenderLayout layout = {};
    layout.moduleCount = moduleCount;
    layout.quietModules = kRegistrationQrQuietModules;
    layout.pixels = area.width < area.height ? area.width : area.height;
    layout.offsetX = area.originX;
    layout.offsetY = area.originY;
    return layout;
}

void renderQrCode(esp_qrcode_handle_t qrcode) {
    gQrRenderLayout = computeQrRenderLayout(esp_qrcode_get_size(qrcode), gQrRenderArea);
    const int totalModules = gQrRenderLayout.moduleCount + (gQrRenderLayout.quietModules * 2);
    if (gQrRenderLayout.moduleCount <= 0 || totalModules <= 0 || gQrRenderLayout.pixels <= 0) {
        return;
    }

    display.fillRect(
        gQrRenderLayout.offsetX,
        gQrRenderLayout.offsetY,
        gQrRenderLayout.pixels,
        gQrRenderLayout.pixels,
        SSD1306_WHITE);

    for (int y = 0; y < gQrRenderLayout.moduleCount; y++) {
        for (int x = 0; x < gQrRenderLayout.moduleCount; x++) {
            if (!esp_qrcode_get_module(qrcode, x, y)) {
                continue;
            }

            const int pixelX0 = gQrRenderLayout.offsetX +
                                mapQrModuleEdgeToPixels(
                                    x + gQrRenderLayout.quietModules,
                                    totalModules,
                                    gQrRenderLayout.pixels);
            const int pixelY0 = gQrRenderLayout.offsetY +
                                mapQrModuleEdgeToPixels(
                                    y + gQrRenderLayout.quietModules,
                                    totalModules,
                                    gQrRenderLayout.pixels);
            const int pixelX1 = gQrRenderLayout.offsetX +
                                mapQrModuleEdgeToPixels(
                                    x + gQrRenderLayout.quietModules + 1,
                                    totalModules,
                                    gQrRenderLayout.pixels);
            const int pixelY1 = gQrRenderLayout.offsetY +
                                mapQrModuleEdgeToPixels(
                                    y + gQrRenderLayout.quietModules + 1,
                                    totalModules,
                                    gQrRenderLayout.pixels);

            display.fillRect(
                pixelX0,
                pixelY0,
                pixelX1 > pixelX0 ? pixelX1 - pixelX0 : 1,
                pixelY1 > pixelY0 ? pixelY1 - pixelY0 : 1,
                SSD1306_BLACK);
        }
    }
}

QrRenderLayout drawQrCodeAt(const char *text, int originX, int originY, int availableWidth, int availableHeight) {
    if (text == nullptr || text[0] == '\0') {
        return {};
    }

    gQrRenderArea.originX = originX;
    gQrRenderArea.originY = originY;
    gQrRenderArea.width = availableWidth;
    gQrRenderArea.height = availableHeight;
    gQrRenderLayout = {};

    esp_qrcode_config_t cfg = ESP_QRCODE_CONFIG_DEFAULT();
    cfg.max_qrcode_version = 6;
    cfg.qrcode_ecc_level = ESP_QRCODE_ECC_LOW;
    cfg.display_func = renderQrCode;

    esp_qrcode_generate(&cfg, text);
    return gQrRenderLayout;
}
}

void oledInit() {
    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
        display.setTextWrap(false);
    }
}

void oledDrawStartup(unsigned long elapsedMs) {
    const char *title = "SS Project";
    const int spinnerSize = 18;
    const int gap = 8;

    int16_t textX1 = 0;
    int16_t textY1 = 0;
    uint16_t textWidth = 0;
    uint16_t textHeight = 0;

    display.clearDisplay();
    display.setTextSize(1);
    display.getTextBounds(title, 0, 0, &textX1, &textY1, &textWidth, &textHeight);

    const int groupWidth = spinnerSize + gap + textWidth;
    const int groupLeft = (SCREEN_WIDTH - groupWidth) / 2;
    const int spinnerCenterX = groupLeft + spinnerSize / 2;
    const int spinnerCenterY = SCREEN_HEIGHT / 2;
    const int titleX = groupLeft + spinnerSize + gap;
    const int titleY = spinnerCenterY - (textHeight / 2);
    const uint8_t activeDot = (elapsedMs / STARTUP_SPINNER_INTERVAL_MS) % kSpinnerDotCount;

    drawStartupSpinner(spinnerCenterX, spinnerCenterY, activeDot);

    display.setCursor(titleX, titleY);
    display.print(title);

    display.display();
}

void oledDrawStartupConnectionError() {
    const char *line1 = "No internet";
    const char *line2 = "connection.";
    const char *line3 = "Please check Wi-Fi.";
    const char *lines[] = {line1, line2, line3};

    drawCenteredLines(lines, 3, 18, 12);
}

void oledDrawWifiReconnect(unsigned long elapsedMs) {
    const char *title = "Reconnecting";
    const char *subtitle = "Wi-Fi...";
    const uint8_t activeDot = (elapsedMs / STARTUP_SPINNER_INTERVAL_MS) % kSpinnerDotCount;

    int16_t titleX1 = 0;
    int16_t titleY1 = 0;
    uint16_t titleWidth = 0;
    uint16_t titleHeight = 0;
    int16_t subtitleX1 = 0;
    int16_t subtitleY1 = 0;
    uint16_t subtitleWidth = 0;
    uint16_t subtitleHeight = 0;

    display.clearDisplay();
    display.setFont();
    display.setTextSize(1);

    drawStartupSpinner(SCREEN_WIDTH / 2, 18, activeDot);

    display.getTextBounds(title, 0, 0, &titleX1, &titleY1, &titleWidth, &titleHeight);
    display.setCursor((SCREEN_WIDTH - titleWidth) / 2, 36);
    display.print(title);

    display.getTextBounds(subtitle, 0, 0, &subtitleX1, &subtitleY1, &subtitleWidth, &subtitleHeight);
    display.setCursor((SCREEN_WIDTH - subtitleWidth) / 2, 48);
    display.print(subtitle);

    display.display();
}

void oledDrawAwaitNfc() {
    const char *lines[] = {"Please tap NFC"};
    drawCenteredLines(lines, 1, 28, 12);
}

void oledDrawLoading(unsigned long elapsedMs) {
    const char *waitText = "Please wait ...";
    const uint8_t activeDot = (elapsedMs / STARTUP_SPINNER_INTERVAL_MS) % kSpinnerDotCount;
    constexpr int spinnerCenterX = SCREEN_WIDTH / 2;
    constexpr int spinnerCenterY = 22;
    constexpr int waitTextY = 44;

    int16_t waitTextX1 = 0;
    int16_t waitTextY1 = 0;
    uint16_t waitTextWidth = 0;
    uint16_t waitTextHeight = 0;

    display.clearDisplay();
    display.setFont();
    display.setTextSize(1);

    drawStartupSpinner(spinnerCenterX, spinnerCenterY, activeDot);

    display.getTextBounds(waitText, 0, 0, &waitTextX1, &waitTextY1, &waitTextWidth, &waitTextHeight);
    display.setCursor((SCREEN_WIDTH - waitTextWidth) / 2, waitTextY);
    display.print(waitText);

    display.display();
}

void oledDrawLookupError() {
    const char *lines[] = {
        "Cannot reach server.",
        "Tap NFC again.",
    };
    drawCenteredLines(lines, 2, 22, 12);
}

void oledDrawRegistrationPrompt(const char *registerUrl) {
    display.clearDisplay();
    const QrRenderLayout qrLayout =
        drawQrCodeAt(registerUrl, 0, 0, kRegistrationQrSize, kRegistrationQrSize);
    int textX = qrLayout.offsetX + qrLayout.pixels + kRegistrationTextGap;
    if (textX < kRegistrationQrSize) {
        textX = kRegistrationQrSize;
    }

    display.setTextSize(1);
    display.setCursor(textX, 16);
    display.println("Scan this");
    display.setCursor(textX, 28);
    display.println("QR code to");
    display.setCursor(textX, 40);
    display.println("register!");
    display.display();
}

void oledDrawGreeting(const char *name) {
    display.clearDisplay();
    display.setTextSize(1);

    String greeting = "Hi";
    if (name != nullptr && name[0] != '\0') {
        greeting += " ";
        greeting += name;
    }
    greeting += "!";

    int16_t textX1 = 0;
    int16_t textY1 = 0;
    uint16_t textWidth = 0;
    uint16_t textHeight = 0;
    display.getTextBounds(greeting.c_str(), 0, 0, &textX1, &textY1, &textWidth, &textHeight);
    display.setCursor((SCREEN_WIDTH - textWidth) / 2, (SCREEN_HEIGHT - textHeight) / 2);
    display.print(greeting);
    display.display();
}

void oledDraw(const int16_t rawData[], int rawLen, const WakewordInfo &wakeword, const char *uid) {
    const int waveLeft = 0;
    const int waveRight = SCREEN_WIDTH - 1;
    const int waveTop = 20;
    const int waveBottom = 47;
    const bool recentWakeword =
        wakeword.lastDetectionMs > 0 &&
        millis() - wakeword.lastDetectionMs < WAKEWORD_DETECTION_COOLDOWN_MS;

    display.clearDisplay();
    display.setCursor(0, 0);
    if (wifiIsReady()) {
        display.print("WS:");
        display.println(wifiGetIpAddress());
    } else {
        display.println("WS: CONNECTING...");
    }

    display.setCursor(0, 10);
    display.print("WW:");
    if (!wakeword.hasInference) {
        display.println("warming...");
    } else if (recentWakeword) {
        display.print("WAKEUP ");
        display.println(wakeword.wakeupScore, 2);
    } else {
        display.print(wakeword.topLabel);
        display.print(" ");
        display.println(wakeword.topScore, 2);
    }

    display.drawRect(waveLeft, waveTop, SCREEN_WIDTH, waveBottom - waveTop + 1, SSD1306_WHITE);
    int mid = (waveTop + waveBottom) / 2;
    display.drawFastHLine(waveLeft + 1, mid, SCREEN_WIDTH - 2, SSD1306_WHITE);

    if (rawLen > 1) {
        int prevY = map((long)rawData[0], -32768, 32767, waveBottom - 1, waveTop + 1);
        for (int x = 1; x <= waveRight - 1; x++) {
            int idx = ((x - 1) * rawLen) / (SCREEN_WIDTH - 2);
            if (idx >= rawLen) idx = rawLen - 1;
            int y = map((long)rawData[idx], -32768, 32767, waveBottom - 1, waveTop + 1);
            display.drawLine(x, prevY, x + 1, y, SSD1306_WHITE);
            prevY = y;
        }
    }

    display.setCursor(0, 54);
    display.print("UID:");
    display.println(uid != nullptr ? uid : "");

    display.display();
}

#include "ui/oled_view.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <qrcode.h>

#include "app_config.h"

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
constexpr int kRobotHeadX = 14;
constexpr int kRobotHeadY = 14;
constexpr int kRobotHeadWidth = 100;
constexpr int kRobotHeadHeight = 44;
constexpr int kRobotAntennaX = SCREEN_WIDTH / 2;
constexpr int kLeftEyeCenterX = 40;
constexpr int kRightEyeCenterX = 88;
constexpr int kEyeCenterY = 29;
constexpr int kMouthBoxX = 32;
constexpr int kMouthBoxY = 39;
constexpr int kMouthBoxWidth = 64;
constexpr int kMouthBoxHeight = 13;
constexpr int kSleepMouthX = 42;
constexpr int kSleepMouthY = 41;
constexpr int kSleepMouthWidth = 44;
constexpr int kSleepMouthHeight = 9;

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

void drawRobotHeadFrame() {
    display.fillRoundRect(kRobotHeadX - 4, kRobotHeadY + 13, 5, 12, 2, SSD1306_WHITE);
    display.fillRoundRect(
        kRobotHeadX + kRobotHeadWidth - 1, kRobotHeadY + 13, 5, 12, 2, SSD1306_WHITE);
    display.drawRoundRect(
        kRobotHeadX, kRobotHeadY, kRobotHeadWidth, kRobotHeadHeight, 11, SSD1306_WHITE);
    display.drawRoundRect(
        kRobotHeadX + 3, kRobotHeadY + 3, kRobotHeadWidth - 6, kRobotHeadHeight - 6, 8, SSD1306_WHITE);
    display.drawLine(kRobotAntennaX, 8, kRobotAntennaX, kRobotHeadY, SSD1306_WHITE);
    display.fillCircle(kRobotAntennaX, 5, 2, SSD1306_WHITE);
    display.drawPixel(kRobotHeadX + 20, kRobotHeadY + kRobotHeadHeight - 7, SSD1306_WHITE);
    display.drawPixel(kRobotHeadX + 79, kRobotHeadY + kRobotHeadHeight - 7, SSD1306_WHITE);
}

void drawClosedEye(int centerX, int centerY) {
    display.drawLine(centerX - 11, centerY + 1, centerX + 11, centerY + 1, SSD1306_WHITE);
    display.drawLine(centerX - 9, centerY, centerX + 9, centerY, SSD1306_WHITE);
    display.drawPixel(centerX - 7, centerY - 1, SSD1306_WHITE);
    display.drawPixel(centerX + 7, centerY - 1, SSD1306_WHITE);
    display.drawPixel(centerX - 4, centerY + 2, SSD1306_WHITE);
    display.drawPixel(centerX + 4, centerY + 2, SSD1306_WHITE);
}

void drawOpenEye(int centerX, int centerY) {
    display.fillRoundRect(centerX - 12, centerY - 7, 24, 14, 6, SSD1306_WHITE);
    display.drawRoundRect(centerX - 11, centerY - 6, 22, 12, 5, SSD1306_BLACK);
    display.fillCircle(centerX, centerY, 3, SSD1306_BLACK);
    display.drawPixel(centerX - 1, centerY - 1, SSD1306_WHITE);
    display.drawPixel(centerX, centerY - 2, SSD1306_WHITE);
}

void drawCheek(int centerX, int centerY) {
    display.drawCircle(centerX, centerY, 2, SSD1306_WHITE);
    display.drawPixel(centerX - 4, centerY, SSD1306_WHITE);
    display.drawPixel(centerX + 4, centerY, SSD1306_WHITE);
}

void drawSleepDecoration() {
    display.drawCircle(87, 13, 1, SSD1306_WHITE);
    display.setCursor(92, 0);
    display.print("z");
    display.setCursor(100, 3);
    display.print("z");
    display.setCursor(108, 6);
    display.print("Z");
}

void drawSleepMouth() {
    display.fillRoundRect(
        kSleepMouthX, kSleepMouthY, kSleepMouthWidth, kSleepMouthHeight, 4, SSD1306_WHITE);
    display.drawRoundRect(
        kSleepMouthX + 1, kSleepMouthY + 1, kSleepMouthWidth - 2, kSleepMouthHeight - 2, 4, SSD1306_BLACK);
    display.drawLine(
        kSleepMouthX + 8,
        kSleepMouthY + (kSleepMouthHeight / 2) + 1,
        kSleepMouthX + kSleepMouthWidth - 9,
        kSleepMouthY + (kSleepMouthHeight / 2) + 1,
        SSD1306_BLACK);
    display.drawPixel(kSleepMouthX + 6, kSleepMouthY + (kSleepMouthHeight / 2), SSD1306_BLACK);
    display.drawPixel(
        kSleepMouthX + kSleepMouthWidth - 7,
        kSleepMouthY + (kSleepMouthHeight / 2),
        SSD1306_BLACK);
}

void drawWaveformInRect(const int16_t rawData[],
                        int rawLen,
                        int x,
                        int y,
                        int width,
                        int height) {
    if (width < 4 || height < 4) {
        return;
    }

    display.drawRoundRect(x, y, width, height, 4, SSD1306_WHITE);
    const int innerLeft = x + 1;
    const int innerTop = y + 1;
    const int innerWidth = width - 2;
    const int innerHeight = height - 2;
    const int midY = innerTop + innerHeight / 2;
    const int halfSpan = innerHeight / 2;

    display.drawPixel(x + 6, midY, SSD1306_WHITE);
    display.drawPixel(x + width - 7, midY, SSD1306_WHITE);

    if (rawLen <= 1) {
        display.drawFastHLine(x + 10, midY, width - 20, SSD1306_WHITE);
        return;
    }

    int peakAbs = 0;
    for (int i = 0; i < rawLen; ++i) {
        int sampleAbs = rawData[i];
        if (sampleAbs < 0) {
            sampleAbs = -sampleAbs;
        }
        if (sampleAbs > peakAbs) {
            peakAbs = sampleAbs;
        }
    }

    // Auto-scale the current chunk so spoken audio stays visible on the small OLED,
    // while keeping enough headroom to avoid the waveform becoming a solid block.
    int displayPeak = peakAbs;
    if (displayPeak < 1800) {
        displayPeak = 1800;
    } else if (displayPeak > 12000) {
        displayPeak = 12000;
    }

    int prevX = innerLeft;
    int prevOffset = (static_cast<long>(rawData[0]) * halfSpan) / displayPeak;
    if (prevOffset > halfSpan) {
        prevOffset = halfSpan;
    } else if (prevOffset < -halfSpan) {
        prevOffset = -halfSpan;
    }
    int prevY = midY - prevOffset;

    for (int i = 1; i < innerWidth; ++i) {
        int idx = (i * rawLen) / innerWidth;
        if (idx >= rawLen) {
            idx = rawLen - 1;
        }

        const int currentX = innerLeft + i;
        int currentOffset = (static_cast<long>(rawData[idx]) * halfSpan) / displayPeak;
        if (currentOffset > halfSpan) {
            currentOffset = halfSpan;
        } else if (currentOffset < -halfSpan) {
            currentOffset = -halfSpan;
        }
        const int currentY = midY - currentOffset;
        display.drawLine(prevX, prevY, currentX, currentY, SSD1306_WHITE);
        prevX = currentX;
        prevY = currentY;
    }
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

void oledDrawWakewordSleep() {
    display.clearDisplay();
    display.setFont();
    display.setTextSize(1);

    drawRobotHeadFrame();
    drawClosedEye(kLeftEyeCenterX, kEyeCenterY);
    drawClosedEye(kRightEyeCenterX, kEyeCenterY);
    drawCheek(27, 42);
    drawCheek(101, 42);
    drawSleepMouth();
    drawSleepDecoration();
    display.display();
}

void oledDrawStreamingFace(const int16_t rawData[], int rawLen) {
    display.clearDisplay();
    display.setFont();
    display.setTextSize(1);

    drawRobotHeadFrame();
    drawOpenEye(kLeftEyeCenterX, kEyeCenterY);
    drawOpenEye(kRightEyeCenterX, kEyeCenterY);
    drawCheek(27, 42);
    drawCheek(101, 42);
    drawWaveformInRect(rawData, rawLen, kMouthBoxX, kMouthBoxY, kMouthBoxWidth, kMouthBoxHeight);

    display.display();
}

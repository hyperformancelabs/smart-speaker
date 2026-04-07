#include "ui/oled_view.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "app_config.h"
#include "net/wifi_service.h"

namespace {
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
constexpr uint8_t kSpinnerDotCount = 8;
constexpr int8_t kSpinnerOffsetX[kSpinnerDotCount] = {0, 5, 8, 5, 0, -5, -8, -5};
constexpr int8_t kSpinnerOffsetY[kSpinnerDotCount] = {-8, -5, 0, 5, 8, 5, 0, -5};

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
    const int barWidth = 78;
    const int barHeight = 6;
    const int barX = (SCREEN_WIDTH - barWidth) / 2;
    const int barY = 42;

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
    const int spinnerCenterY = 25;
    const int titleX = groupLeft + spinnerSize + gap;
    const int titleY = spinnerCenterY - (textHeight / 2);
    const uint8_t activeDot = (elapsedMs / STARTUP_SPINNER_INTERVAL_MS) % kSpinnerDotCount;
    const int innerBarWidth = barWidth - 2;
    const int fillWidth = min(innerBarWidth, (int)((elapsedMs * innerBarWidth) / STARTUP_SPLASH_MS));

    drawStartupSpinner(spinnerCenterX, spinnerCenterY, activeDot);

    display.setCursor(titleX, titleY);
    display.print(title);

    display.drawRect(barX, barY, barWidth, barHeight, SSD1306_WHITE);
    if (fillWidth > 0) {
        display.fillRect(barX + 1, barY + 1, fillWidth, barHeight - 2, SSD1306_WHITE);
    }

    display.display();
}

void oledDraw(const int16_t rawData[], int rawLen, const WakewordInfo &wakeword, const String &uid) {
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
    display.println(uid);

    display.display();
}

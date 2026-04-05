#include "ui/oled_view.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "app_config.h"
#include "net/wifi_service.h"

namespace {
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
}

void oledInit() {
    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
    }
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

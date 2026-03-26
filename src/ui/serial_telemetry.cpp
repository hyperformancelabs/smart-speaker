#include "ui/serial_telemetry.h"

#include "app_config.h"

void serialTelemetryBegin() {
    Serial.begin(SERIAL_BAUD_RATE);
}

void serialSendPlotter(const int16_t rawData[], int rawLen, int cardEvent) {
    int points = min(rawLen, SERIAL_RAW_LINES);
    if (points <= 0) {
        Serial.println(">raw:0");
    } else {
        for (int i = 0; i < points; i++) {
            int idx = (i * rawLen) / points;
            if (idx >= rawLen) idx = rawLen - 1;
            Serial.print(">raw:");
            Serial.println(rawData[idx]);
        }
    }

    Serial.print(">card:");
    Serial.println(cardEvent);
}

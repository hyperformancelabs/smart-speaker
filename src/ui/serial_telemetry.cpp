#include "ui/serial_telemetry.h"

#include "app_config.h"
#include "net/wifi_service.h"

namespace {
void serialSendWsIpPlotter() {
    const IPAddress wsIp = wifiGetIpAddress();

    Serial.print(">ws_ip_1:");
    Serial.println(wsIp[0]);
    Serial.print(">ws_ip_2:");
    Serial.println(wsIp[1]);
    Serial.print(">ws_ip_3:");
    Serial.println(wsIp[2]);
    Serial.print(">ws_ip_4:");
    Serial.println(wsIp[3]);
}
}

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

    serialSendWsIpPlotter();
}

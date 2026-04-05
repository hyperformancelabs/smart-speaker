#include <Arduino.h>

#include "app_state.h"
#include "audio/audio_service.h"
#include "net/wifi_service.h"
#include "net/ws_service.h"
#include "sensors/rfid_service.h"
#include "ui/oled_view.h"
#include "ui/serial_telemetry.h"

namespace {
AppState app;

void taskNetwork() {
    wsLoop();
    wifiEnsureConnected();
}

void taskAudioCapture() {
    app.rawLen = 0;
    audioReadMic(app.rawData, app.rawLen);
}

void taskAudioStream() {
    audioFeedWsFrames(app.rawData, app.rawLen);
}

void taskDemoUiAndRfid() {
    int previousCardEvent = app.pendingCardEvent;
    rfidPoll(app.lastUid, app.pendingCardEvent);
    if (!previousCardEvent && app.pendingCardEvent) {
        audioBeep(900, 80);
    }

    unsigned long now = millis();
    if (now - app.lastDemoTick >= 200) {
        oledDraw(app.rawData, app.rawLen, app.lastUid);
        serialSendPlotter(app.rawData, app.rawLen, app.pendingCardEvent);
        app.pendingCardEvent = 0;
        app.lastDemoTick = now;
    }
}
}

void setup() {
    serialTelemetryBegin();
    audioPrepareOutput();
    oledInit();
    rfidInit();

    audioInit();

    wifiConnect();
    wsBegin();

    audioEnableOutput();
    delay(50);
    audioBeep(900, 80);
}

void loop() {
    taskNetwork();
    taskAudioCapture();
    taskAudioStream();
    taskDemoUiAndRfid();
}

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

void taskAudioLoopback() {
    if (!app.recordMode && app.loopbackMode && app.rawLen > 0) {
        audioPlayLoopback(app.rawData, app.rawLen);
    }
}

void taskAudioStream() {
    audioFeedWsFrames(app.rawData, app.rawLen);
}

void taskDemoUiAndRfid() {
    if (app.recordMode) return;

    rfidPoll(app.lastUid, app.pendingCardEvent);

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
    if (!app.recordMode) {
        serialTelemetryBegin();
        audioPrepareOutput();
        oledInit();
        rfidInit();
    }

    audioInit(app.recordMode);

    wifiConnect();
    wsBegin();

    if (!app.recordMode) {
        audioEnableOutput();
        delay(50);
        audioBeep(900, 80);
    }
}

void loop() {
    taskNetwork();
    taskAudioCapture();
    taskAudioLoopback();
    taskAudioStream();
    taskDemoUiAndRfid();
}

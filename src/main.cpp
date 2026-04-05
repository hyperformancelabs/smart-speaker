#include <Arduino.h>

#include "app_state.h"
#include "audio/audio_service.h"
#include "net/wifi_service.h"
#include "net/ws_service.h"
#include "sensors/rfid_service.h"
#include "ui/oled_view.h"
#include "ui/serial_telemetry.h"
#include "wakeword/wakeword_service.h"

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

void taskWakeword() {
    if (wakewordProcessSamples(app.rawData, app.rawLen, app.wakeword)) {
        audioBeep(WAKEWORD_BEEP_FREQ, WAKEWORD_BEEP_MS);
    }
}

void taskDemoUiAndRfid() {
    int previousCardEvent = app.pendingCardEvent;
    rfidPoll(app.lastUid, app.pendingCardEvent);
    if (!previousCardEvent && app.pendingCardEvent) {
        audioBeep(900, 80);
    }

    unsigned long now = millis();
    if (now - app.lastDemoTick >= 200) {
        oledDraw(app.rawData, app.rawLen, app.wakeword, app.lastUid);
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
    wakewordInit(app.wakeword);

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
    taskWakeword();
    taskDemoUiAndRfid();
}

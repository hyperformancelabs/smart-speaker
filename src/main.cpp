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

bool taskStartup() {
    unsigned long now = millis();
    unsigned long elapsed = now - app.startupSplashStartedMs;
    WifiConnectionState wifiState = wifiGetConnectionState();

    if (!app.wifiReadyBeeped && elapsed >= STARTUP_SPLASH_MS &&
        wifiState == WifiConnectionState::Ready) {
        audioBeep(WIFI_CONNECTED_BEEP_FREQ, WIFI_CONNECTED_BEEP_MS);
        app.wifiReadyBeeped = true;
    }

    if (elapsed >= STARTUP_SPLASH_MS && wifiState == WifiConnectionState::Ready) {
        return false;
    }

    const bool shouldShowLoading =
        elapsed < STARTUP_SPLASH_MS || wifiState == WifiConnectionState::Connecting;

    if (shouldShowLoading) {
        if (app.startupShowingError || app.lastStartupFrameMs == 0 ||
            now - app.lastStartupFrameMs >= STARTUP_SPINNER_INTERVAL_MS) {
            oledDrawStartup(elapsed);
            app.lastStartupFrameMs = now;
            app.startupShowingError = false;
        }

        return true;
    }

    if (!app.startupShowingError) {
        oledDrawStartupConnectionError();
        app.startupShowingError = true;
    }

    return true;
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
    oledInit();
    app.startupSplashStartedMs = millis();
    oledDrawStartup(0);

    audioPrepareOutput();
    rfidInit();

    audioInit();
    wakewordInit(app.wakeword);

    wifiConnect();
    wsBegin();

    audioEnableOutput();
}

void loop() {
    taskNetwork();
    if (taskStartup()) {
        return;
    }

    taskAudioCapture();
    taskAudioStream();
    taskWakeword();
    taskDemoUiAndRfid();
}

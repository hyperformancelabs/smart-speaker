#include <Arduino.h>

#include "audio/audio_service.h"
#include "net/wifi_service.h"
#include "net/ws_service.h"
#include "rtos/app_tasks.h"
#include "sensors/rfid_service.h"
#include "ui/oled_view.h"
#include "ui/serial_telemetry.h"

void setup() {
    serialTelemetryBegin();
    oledInit();
    oledDrawStartup(0);

    audioPrepareOutput();
    rfidInit();
    audioInit();

    wifiConnect();
    wsBegin();

    audioEnableOutput();
    appTasksStart();
}

void loop() {
    delay(1000);
}

#include "net/ws_service.h"

#include <WiFi.h>
#include <WebSocketsServer.h>

#include "app_config.h"
#include "net/wifi_service.h"

namespace {
WebSocketsServer wsServer(WS_PORT);

void wsOnEvent(uint8_t clientId, WStype_t type, uint8_t *payload, size_t length) {
    (void)payload;
    (void)length;

    if (type == WStype_CONNECTED) {
        wsServer.sendTXT(clientId, "{\"type\":\"hello\",\"transport\":\"ws\"}");
    }
}
}

void wsBegin() {
    wsServer.begin();
    wsServer.onEvent(wsOnEvent);
}

void wsLoop() {
    wsServer.loop();
}

void wsSendAudioFrame(const int16_t pcm[], int n) {
    if (!wifiIsReady() || n <= 0) return;

    static uint32_t seq = 0;
    static uint8_t pkt[4 + FRAME_SAMPLES * 2];

    memcpy(pkt, &seq, 4);
    memcpy(pkt + 4, pcm, n * sizeof(int16_t));
    seq++;

    wsServer.broadcastBIN(pkt, 4 + n * sizeof(int16_t));
}

#include "net/ws_service.h"

#include <WiFi.h>
#include <WebSocketsServer.h>

#include "app_config.h"
#include "net/voice_backend_service.h"
#include "net/wifi_service.h"

namespace {
WebSocketsServer wsServer(WS_PORT);

void wsOnEvent(uint8_t clientId, WStype_t type, uint8_t *payload, size_t length) {
    if (type == WStype_CONNECTED) {
        wsServer.sendTXT(clientId, "{\"type\":\"hello\",\"transport\":\"ws\"}");
        return;
    }

    if (type == WStype_TEXT) {
        String message = "";
        message.reserve(length);
        for (size_t i = 0; i < length; ++i) {
            message += static_cast<char>(payload[i]);
        }

        if (!voiceBackendHandleControlMessage(message.c_str())) {
            Serial.printf("wsOnEvent: ignored text message from client %u: %s\n",
                          clientId,
                          message.c_str());
        }
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

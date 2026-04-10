#include "net/voice_backend_service.h"

#include <esp_system.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

#include "app_config.h"
#include "net/wifi_service.h"
#include "secrets.h"

#ifndef DEVICE_VOICE_BACKEND_URL
#define DEVICE_VOICE_BACKEND_URL SERVER_URL
#endif

namespace {
constexpr uint16_t kVoiceBackendConnectTimeoutMs = 2500;
constexpr uint16_t kVoiceBackendRequestTimeoutMs = 6500;
constexpr unsigned long kVoiceBackendWifiReadyWaitMs = 1500;
constexpr char kVoiceBackendPath[] = "/api/audio/start";
String buildAudioStartPayload() {
    const IPAddress ip = wifiGetIpAddress();
    if (ip == IPAddress()) {
        return "";
    }

    String payload = "{";
    payload += "\"ws_host\":\"";
    payload += ip.toString();
    payload += "\",";
    payload += "\"ws_port\":";
    payload += String(WS_PORT);
    payload += "}";
    return payload;
}
}

bool voiceBackendStartCapture() {
    if (!wifiWaitUntilReady(kVoiceBackendWifiReadyWaitMs)) {
        Serial.println("voiceBackendStartCapture: Wi-Fi not ready");
        return false;
    }

    const String payload = buildAudioStartPayload();
    if (payload.length() == 0) {
        Serial.println("voiceBackendStartCapture: missing local IP");
        return false;
    }

    Serial.printf("voiceBackendStartCapture: free heap before request = %u bytes\n", ESP.getFreeHeap());
    const String url = String(DEVICE_VOICE_BACKEND_URL) + kVoiceBackendPath;
    Serial.printf("voiceBackendStartCapture: POST %s\n", url.c_str());
    Serial.printf("voiceBackendStartCapture: payload %s\n", payload.c_str());
    const bool useTls = url.startsWith("https://");

    if (useTls) {
        WiFiClientSecure client;
        client.setInsecure();
        HTTPClient http;
        http.setConnectTimeout(kVoiceBackendConnectTimeoutMs);
        http.setTimeout(kVoiceBackendRequestTimeoutMs);
        if (!http.begin(client, url)) {
            Serial.println("voiceBackendStartCapture: failed to begin request");
            return false;
        }

        http.addHeader("Content-Type", "application/json");
        const int code = http.POST(payload);
        if (code != HTTP_CODE_OK && code != HTTP_CODE_ACCEPTED) {
            if (code < 0) {
                Serial.printf("voiceBackendStartCapture failed: %s (%d)\n",
                              HTTPClient::errorToString(code).c_str(),
                              code);
            } else {
                Serial.printf("voiceBackendStartCapture failed: HTTP %d\n", code);
            }
            http.end();
            return false;
        }

        const String body = http.getString();
        Serial.printf("voiceBackendStartCapture ok: HTTP %d %s\n", code, body.c_str());
        http.end();
        return true;
    } else {
        WiFiClient client;
        HTTPClient http;
        http.setConnectTimeout(kVoiceBackendConnectTimeoutMs);
        http.setTimeout(kVoiceBackendRequestTimeoutMs);
        if (!http.begin(client, url)) {
            Serial.println("voiceBackendStartCapture: failed to begin request");
            return false;
        }

        http.addHeader("Content-Type", "application/json");
        const int code = http.POST(payload);
        if (code != HTTP_CODE_OK && code != HTTP_CODE_ACCEPTED) {
            if (code < 0) {
                Serial.printf("voiceBackendStartCapture failed: %s (%d)\n",
                              HTTPClient::errorToString(code).c_str(),
                              code);
            } else {
                Serial.printf("voiceBackendStartCapture failed: HTTP %d\n", code);
            }
            http.end();
            return false;
        }

        const String body = http.getString();
        Serial.printf("voiceBackendStartCapture ok: HTTP %d %s\n", code, body.c_str());
        http.end();
        return true;
    }
}

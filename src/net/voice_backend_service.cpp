#include "net/voice_backend_service.h"

#include <cctype>

#include <esp_system.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

#include "app_config.h"
#include "net/wifi_service.h"
#include "rtos/app_tasks.h"
#include "secrets.h"

#ifndef DEVICE_VOICE_BACKEND_URL
#define DEVICE_VOICE_BACKEND_URL SERVER_URL
#endif

namespace {
constexpr uint16_t kVoiceBackendConnectTimeoutMs = 2500;
constexpr uint16_t kVoiceBackendRequestTimeoutMs = 6500;
constexpr unsigned long kVoiceBackendWifiReadyWaitMs = 1500;
constexpr char kVoiceBackendPath[] = "/api/audio/start";
constexpr char kFirstUtteranceState[] = "wait_wakeword";

bool extractJsonStringField(const String &payload, const char *fieldName, String &value) {
    value = "";

    String key = "\"";
    key += fieldName;
    key += "\"";

    const int keyIndex = payload.indexOf(key);
    if (keyIndex < 0) {
        return false;
    }

    const int colonIndex = payload.indexOf(':', keyIndex + key.length());
    if (colonIndex < 0) {
        return false;
    }

    int valueStart = colonIndex + 1;
    while (valueStart < payload.length() &&
           std::isspace(static_cast<unsigned char>(payload[valueStart]))) {
        ++valueStart;
    }

    if (valueStart >= payload.length() || payload[valueStart] != '"') {
        return false;
    }

    ++valueStart;
    const int valueEnd = payload.indexOf('"', valueStart);
    if (valueEnd < 0) {
        return false;
    }

    value = payload.substring(valueStart, valueEnd);
    return true;
}

bool parseExternalAudioSessionState(const String &value, ExternalAudioSessionState &state) {
    if (value.equalsIgnoreCase("wait_wakeword")) {
        state = ExternalAudioSessionState::WaitWakeword;
        return true;
    }

    if (value.equalsIgnoreCase("streaming")) {
        state = ExternalAudioSessionState::Streaming;
        return true;
    }

    return false;
}

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
    payload += ",";
    payload += "\"first_utterance_state\":\"";
    payload += kFirstUtteranceState;
    payload += "\"";
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

bool voiceBackendHandleControlMessage(const char *payload) {
    if (payload == nullptr || payload[0] == '\0') {
        return false;
    }

    const String message(payload);
    String messageType;
    if (!extractJsonStringField(message, "type", messageType) ||
        !messageType.equalsIgnoreCase("audio_session_state")) {
        return false;
    }

    String stateValue;
    if (!extractJsonStringField(message, "state", stateValue)) {
        Serial.printf("voiceBackendHandleControlMessage: missing state in %s\n", message.c_str());
        return true;
    }

    ExternalAudioSessionState nextState = ExternalAudioSessionState::WaitWakeword;
    if (!parseExternalAudioSessionState(stateValue, nextState)) {
        Serial.printf("voiceBackendHandleControlMessage: unsupported state '%s'\n",
                      stateValue.c_str());
        return true;
    }

    appRequestExternalAudioSessionState(nextState);
    Serial.printf("voiceBackendHandleControlMessage: queued state %s\n",
                  appExternalAudioSessionStateName(nextState));
    return true;
}

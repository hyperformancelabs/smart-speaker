#include "net/voice_backend_service.h"

#include <cctype>
#include <cstring>

#include <esp_system.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <freertos/FreeRTOS.h>

#include "app_config.h"
#include "net/wifi_service.h"
#include "rtos/app_runtime.h"
#include "rtos/app_tasks.h"
#include "schedule/schedule_service.h"
#include "secrets.h"

#ifndef DEVICE_VOICE_BACKEND_URL
#define DEVICE_VOICE_BACKEND_URL SERVER_URL
#endif

namespace {
namespace runtime = app_runtime;

constexpr uint16_t kVoiceBackendConnectTimeoutMs = 2500;
constexpr uint16_t kVoiceBackendRequestTimeoutMs = 6500;
constexpr unsigned long kVoiceBackendWifiReadyWaitMs = 1500;
constexpr char kVoiceBackendPath[] = "/api/audio/start";
constexpr char kFirstUtteranceState[] = "thinking";
constexpr unsigned long kNoSpeechTimeoutSeconds = 10;
portMUX_TYPE gCaptureTokenMux = portMUX_INITIALIZER_UNLOCKED;
char gActiveCaptureToken[40] = {};

void copyText(char dest[], size_t destSize, const String &src) {
    if (destSize == 0) {
        return;
    }

    const size_t copyLen = src.length() < (destSize - 1) ? src.length() : (destSize - 1);
    memcpy(dest, src.c_str(), copyLen);
    dest[copyLen] = '\0';
}

void setActiveCaptureToken(const String &token) {
    taskENTER_CRITICAL(&gCaptureTokenMux);
    copyText(gActiveCaptureToken, sizeof(gActiveCaptureToken), token);
    taskEXIT_CRITICAL(&gCaptureTokenMux);
}

void clearActiveCaptureToken() {
    taskENTER_CRITICAL(&gCaptureTokenMux);
    gActiveCaptureToken[0] = '\0';
    taskEXIT_CRITICAL(&gCaptureTokenMux);
}

String activeCaptureToken() {
    char tokenCopy[sizeof(gActiveCaptureToken)] = {};
    taskENTER_CRITICAL(&gCaptureTokenMux);
    memcpy(tokenCopy, gActiveCaptureToken, sizeof(gActiveCaptureToken));
    taskEXIT_CRITICAL(&gCaptureTokenMux);
    return String(tokenCopy);
}

bool activeCaptureTokenEquals(const String &token) {
    bool matches = false;
    taskENTER_CRITICAL(&gCaptureTokenMux);
    matches = gActiveCaptureToken[0] != '\0' && token == gActiveCaptureToken;
    taskEXIT_CRITICAL(&gCaptureTokenMux);
    return matches;
}

bool activeCaptureTokenMatches(const char *token) {
    bool matches = false;
    taskENTER_CRITICAL(&gCaptureTokenMux);
    matches = (token == nullptr || token[0] == '\0')
                  ? gActiveCaptureToken[0] == '\0'
                  : (gActiveCaptureToken[0] != '\0' && strcmp(token, gActiveCaptureToken) == 0);
    taskEXIT_CRITICAL(&gCaptureTokenMux);
    return matches;
}

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

bool extractJsonBoolField(const String &payload, const char *fieldName, bool &value) {
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

    if (payload.startsWith("true", valueStart)) {
        value = true;
        return true;
    }

    if (payload.startsWith("false", valueStart)) {
        value = false;
        return true;
    }

    return false;
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

    if (value.equalsIgnoreCase("thinking")) {
        state = ExternalAudioSessionState::Thinking;
        return true;
    }

    if (value.equalsIgnoreCase("speaking")) {
        state = ExternalAudioSessionState::Speaking;
        return true;
    }

    return false;
}

String buildCaptureToken() {
    const uint32_t tokenPartA = static_cast<uint32_t>(esp_random());
    const uint32_t tokenPartB = static_cast<uint32_t>(millis());
    char buffer[32] = {};
    snprintf(buffer, sizeof(buffer), "%08lx%08lx",
             static_cast<unsigned long>(tokenPartA),
             static_cast<unsigned long>(tokenPartB));
    return String(buffer);
}

bool messageMatchesActiveCaptureToken(const String &message) {
    String captureToken;
    if (!extractJsonStringField(message, "capture_token", captureToken)) {
        return activeCaptureTokenMatches(nullptr);
    }

    return activeCaptureTokenEquals(captureToken);
}

bool hasUsableNfcTagId(const char *nfcTagId) {
    return nfcTagId != nullptr && nfcTagId[0] != '\0' && strcmp(nfcTagId, "(no card)") != 0;
}

String buildAudioStartPayload(const String &captureToken) {
    const IPAddress ip = wifiGetIpAddress();
    if (ip == IPAddress()) {
        return "";
    }
    const AppState snapshot = app_runtime::loadAppStateSnapshot();

    String payload = "{";
    payload += "\"ws_host\":\"";
    payload += ip.toString();
    payload += "\",";
    payload += "\"ws_port\":";
    payload += String(WS_PORT);
    payload += ",";
    payload += "\"first_utterance_state\":\"";
    payload += kFirstUtteranceState;
    payload += "\",";
    payload += "\"no_speech_timeout_seconds\":";
    payload += String(kNoSpeechTimeoutSeconds);
    payload += ",";
    payload += "\"capture_token\":\"";
    payload += captureToken;
    payload += "\"";
    if (hasUsableNfcTagId(snapshot.lastUid)) {
        payload += ",";
        payload += "\"nfc_tag_id\":\"";
        payload += snapshot.lastUid;
        payload += "\"";
    }
    payload += "}";
    return payload;
}
}

bool voiceBackendStartCapture() {
    if (!wifiWaitUntilReady(kVoiceBackendWifiReadyWaitMs)) {
        Serial.println("voiceBackendStartCapture: Wi-Fi not ready");
        return false;
    }

    const String nextCaptureToken = buildCaptureToken();
    const String payload = buildAudioStartPayload(nextCaptureToken);
    if (payload.length() == 0) {
        Serial.println("voiceBackendStartCapture: missing local IP");
        return false;
    }

    setActiveCaptureToken(nextCaptureToken);

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
            clearActiveCaptureToken();
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
            clearActiveCaptureToken();
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
            clearActiveCaptureToken();
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
            clearActiveCaptureToken();
            return false;
        }

        const String body = http.getString();
        Serial.printf("voiceBackendStartCapture ok: HTTP %d %s\n", code, body.c_str());
        http.end();
        return true;
    }
}

void voiceBackendInvalidateCaptureToken() {
    clearActiveCaptureToken();
}

bool voiceBackendCaptureTokenMatches(const char *captureToken) {
    return activeCaptureTokenMatches(captureToken);
}

bool voiceBackendHandleControlMessage(const char *payload) {
    if (payload == nullptr || payload[0] == '\0') {
        return false;
    }

    const String message(payload);
    String messageType;
    if (!extractJsonStringField(message, "type", messageType)) {
        return false;
    }

    if (messageType.equalsIgnoreCase("schedule_sync_request")) {
        String nfcTagId;
        String reason;
        extractJsonStringField(message, "nfc_tag_id", nfcTagId);
        extractJsonStringField(message, "reason", reason);

        if (nfcTagId.isEmpty()) {
            const AppState snapshot = app_runtime::loadAppStateSnapshot();
            if (hasUsableNfcTagId(snapshot.lastUid)) {
                nfcTagId = snapshot.lastUid;
            }
        }

        if (!nfcTagId.isEmpty()) {
            scheduleRequestSync(nfcTagId.c_str(), reason.c_str());
            Serial.printf("voiceBackendHandleControlMessage: queued schedule sync for %s\n",
                          nfcTagId.c_str());
        }
        return true;
    }

    if (!messageMatchesActiveCaptureToken(message)) {
        String messageCaptureToken;
        extractJsonStringField(message, "capture_token", messageCaptureToken);
        const String activeToken = activeCaptureToken();
        Serial.printf(
            "voiceBackendHandleControlMessage: ignored stale %s active_token=%s incoming_token=%s\n",
            messageType.c_str(),
            activeToken.length() > 0 ? activeToken.c_str() : "<none>",
            messageCaptureToken.length() > 0 ? messageCaptureToken.c_str() : "<none>");
        return true;
    }

    if (messageType.equalsIgnoreCase("audio_session_state")) {
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

        bool stopCapture = false;
        extractJsonBoolField(message, "stop_capture", stopCapture);

        if (stopCapture && nextState == ExternalAudioSessionState::WaitWakeword) {
            runtime::clearPendingExternalAudioSessionState();
            runtime::resetStreamAudioQueue();
            runtime::storePlaybackAudio(nullptr, 0);
            voiceBackendInvalidateCaptureToken();
        }

        appRequestExternalAudioSessionState(nextState);
        Serial.printf("voiceBackendHandleControlMessage: queued state %s stop_capture=%s\n",
                      appExternalAudioSessionStateName(nextState),
                      stopCapture ? "true" : "false");
        return true;
    }

    if (messageType.equalsIgnoreCase("assistant_playback")) {
        String ttsUrl;
        String mediaUrl;
        String mediaTitle;
        String finalStateValue;

        extractJsonStringField(message, "tts_url", ttsUrl);
        extractJsonStringField(message, "media_url", mediaUrl);
        extractJsonStringField(message, "media_title", mediaTitle);
        extractJsonStringField(message, "final_state", finalStateValue);

        AssistantPlaybackRequest request = {};
        copyText(request.captureToken, sizeof(request.captureToken), activeCaptureToken());
        copyText(request.ttsUrl, sizeof(request.ttsUrl), ttsUrl);
        copyText(request.mediaUrl, sizeof(request.mediaUrl), mediaUrl);
        copyText(request.mediaTitle, sizeof(request.mediaTitle), mediaTitle);

        if (!finalStateValue.isEmpty()) {
            parseExternalAudioSessionState(finalStateValue, request.finalState);
        }

        if (request.ttsUrl[0] == '\0' && request.mediaUrl[0] == '\0') {
            appRequestExternalAudioSessionState(request.finalState);
            Serial.printf(
                "voiceBackendHandleControlMessage: playback message without URLs, switching to %s\n",
                appExternalAudioSessionStateName(request.finalState));
            return true;
        }

        appQueueAssistantPlayback(request);
        appRequestExternalAudioSessionState(ExternalAudioSessionState::Speaking);
        Serial.printf("voiceBackendHandleControlMessage: queued playback (tts=%s media=%s)\n",
                      request.ttsUrl[0] != '\0' ? "yes" : "no",
                      request.mediaUrl[0] != '\0' ? "yes" : "no");
        return true;
    }

    return false;
}

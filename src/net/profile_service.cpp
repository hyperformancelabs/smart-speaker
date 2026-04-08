#include "net/profile_service.h"

#include <cstring>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

#include "net/wifi_service.h"
#include "secrets.h"

namespace {
constexpr uint16_t kProfileConnectTimeoutMs = 2500;
constexpr uint16_t kProfileRequestTimeoutMs = 6500;
constexpr uint8_t kProfileMaxAttempts = 2;
constexpr unsigned long kProfileRetryDelayMs = 200;
constexpr unsigned long kProfileWifiReadyWaitMs = 1500;
constexpr int kProfileIncompleteHttpCode = 412;

struct HttpTextResponse {
    int code = 0;
    String body;
};

void copyText(char dest[], size_t destSize, const char *src) {
    if (dest == nullptr || destSize == 0) {
        return;
    }

    if (src == nullptr) {
        src = "";
    }

    std::strncpy(dest, src, destSize - 1);
    dest[destSize - 1] = '\0';
}

HttpTextResponse performGetTextRequest(const String &url) {
    HttpTextResponse response = {};
    WiFiClientSecure client;
    client.setInsecure();

    HTTPClient http;
    http.setConnectTimeout(kProfileConnectTimeoutMs);
    http.setTimeout(kProfileRequestTimeoutMs);

    if (!http.begin(client, url)) {
        response.code = HTTPC_ERROR_CONNECTION_REFUSED;
        return response;
    }

    response.code = http.GET();
    if (response.code > 0) {
        response.body = http.getString();
    }

    http.end();
    return response;
}

bool shouldRetryProfileRequest(int httpCode, bool emptyBody) {
    if (emptyBody) {
        return true;
    }

    if (httpCode < 0) {
        return true;
    }

    return httpCode == HTTP_CODE_REQUEST_TIMEOUT || httpCode == HTTP_CODE_TOO_MANY_REQUESTS ||
           httpCode >= HTTP_CODE_INTERNAL_SERVER_ERROR;
}

void logProfileRequestIssue(const char *label, int httpCode, uint8_t attempt) {
    if (httpCode < 0) {
        Serial.printf("%s attempt %u failed: %s (%d)\n",
                      label,
                      attempt,
                      HTTPClient::errorToString(httpCode).c_str(),
                      httpCode);
        return;
    }

    Serial.printf("%s attempt %u failed: HTTP %d\n", label, attempt, httpCode);
}
}

bool profileFetchStatus(const char *uid, ProfileStatus &status) {
    status = {};
    if (uid == nullptr || uid[0] == '\0') {
        return false;
    }

    if (!wifiIsReady()) {
        wifiForceReconnect();
    }

    if (!wifiWaitUntilReady(kProfileWifiReadyWaitMs)) {
        Serial.println("profileFetchStatus: Wi-Fi not ready");
        return false;
    }

    String url = String(SERVER_URL) + "/api/device/users/" + uid + "/profile-status";

    for (uint8_t attempt = 1; attempt <= kProfileMaxAttempts; ++attempt) {
        const HttpTextResponse response = performGetTextRequest(url);

        if (response.code == HTTP_CODE_NOT_FOUND) {
            status.state = ProfileState::Missing;
            return true;
        }

        if (response.code == kProfileIncompleteHttpCode) {
            status.state = ProfileState::Incomplete;
            return true;
        }

        const bool emptyOkBody = response.code == HTTP_CODE_OK && response.body.length() == 0;
        if (response.code == HTTP_CODE_OK && !emptyOkBody) {
            status.state = ProfileState::Ready;
            copyText(status.name, sizeof(status.name), response.body.c_str());
            return true;
        }

        if (!shouldRetryProfileRequest(response.code, emptyOkBody) || attempt == kProfileMaxAttempts) {
            logProfileRequestIssue("profileFetchStatus", response.code, attempt);
            return false;
        }

        logProfileRequestIssue("profileFetchStatus", response.code, attempt);
        wifiForceReconnect();
        wifiWaitUntilReady(kProfileWifiReadyWaitMs);
        delay(kProfileRetryDelayMs);
    }

    return false;
}

bool profileWarmupConnection() {
    if (!wifiWaitUntilReady(kProfileWifiReadyWaitMs)) {
        return false;
    }

    const HttpTextResponse response = performGetTextRequest(String(SERVER_URL) + "/health");
    if (response.code == HTTP_CODE_OK) {
        return true;
    }

    logProfileRequestIssue("profileWarmupConnection", response.code, 1);
    return false;
}

bool profileIsComplete(const ProfileStatus &status) {
    return status.state == ProfileState::Ready;
}

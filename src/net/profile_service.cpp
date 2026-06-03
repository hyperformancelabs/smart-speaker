#include "net/profile_service.h"

#include <cstring>
#include <esp_system.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

#include "net/wifi_service.h"
#include "secrets.h"

#ifndef DEVICE_API_URL
#define DEVICE_API_URL SERVER_URL
#endif

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
    Serial.printf("performGetTextRequest: free heap before request = %u bytes\n", ESP.getFreeHeap());
    const bool useTls = url.startsWith("https://");
    if (useTls) {
        WiFiClientSecure client;
        client.setInsecure();
        HTTPClient http;
        http.setConnectTimeout(kProfileConnectTimeoutMs);
        http.setTimeout(kProfileRequestTimeoutMs);
        if (!http.begin(client, url)) {
            Serial.printf("performGetTextRequest: begin failed for %s\n", url.c_str());
            response.code = HTTPC_ERROR_CONNECTION_REFUSED;
            return response;
        }

        response.code = http.GET();
        if (response.code < 0) {
            Serial.printf("performGetTextRequest: %s -> %s (%d)\n",
                          url.c_str(),
                          HTTPClient::errorToString(response.code).c_str(),
                          response.code);
        } else {
            Serial.printf("performGetTextRequest: %s -> HTTP %d\n", url.c_str(), response.code);
        }
        if (response.code > 0) {
            response.body = http.getString();
        }
        http.end();
    } else {
        WiFiClient client;
        HTTPClient http;
        http.setConnectTimeout(kProfileConnectTimeoutMs);
        http.setTimeout(kProfileRequestTimeoutMs);
        if (!http.begin(client, url)) {
            Serial.printf("performGetTextRequest: begin failed for %s\n", url.c_str());
            response.code = HTTPC_ERROR_CONNECTION_REFUSED;
            return response;
        }

        response.code = http.GET();
        if (response.code < 0) {
            Serial.printf("performGetTextRequest: %s -> %s (%d)\n",
                          url.c_str(),
                          HTTPClient::errorToString(response.code).c_str(),
                          response.code);
        } else {
            Serial.printf("performGetTextRequest: %s -> HTTP %d\n", url.c_str(), response.code);
        }
        if (response.code > 0) {
            response.body = http.getString();
        }
        http.end();
    }
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

    String url = String(DEVICE_API_URL) + "/api/device/users/" + uid + "/profile-status";

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

bool profileIsComplete(const ProfileStatus &status) {
    return status.state == ProfileState::Ready;
}

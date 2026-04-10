#include "net/wifi_service.h"

#include <cstring>
#include <Arduino.h>
#include <WiFi.h>

#include "app_config.h"
#include "secrets.h"

#ifndef APP_WIFI_MODE_STA
#define APP_WIFI_MODE_STA 0
#endif

#ifndef APP_WIFI_MODE_AP
#define APP_WIFI_MODE_AP 1
#endif

#ifndef APP_WIFI_MODE
#define APP_WIFI_MODE APP_WIFI_MODE_STA
#endif

#ifndef WIFI_STA_SSID
#ifdef WIFI_SSID
#define WIFI_STA_SSID WIFI_SSID
#else
#define WIFI_STA_SSID ""
#endif
#endif

#ifndef WIFI_STA_PASSWORD
#ifdef WIFI_PASSWORD
#define WIFI_STA_PASSWORD WIFI_PASSWORD
#else
#define WIFI_STA_PASSWORD ""
#endif
#endif

#ifndef WIFI_AP_SSID
#define WIFI_AP_SSID "ESP32-Audio"
#endif

#ifndef WIFI_AP_PASSWORD
#define WIFI_AP_PASSWORD "12345678"
#endif

#if APP_WIFI_MODE != APP_WIFI_MODE_STA && APP_WIFI_MODE != APP_WIFI_MODE_AP
#error "APP_WIFI_MODE must be APP_WIFI_MODE_STA or APP_WIFI_MODE_AP"
#endif

namespace {
unsigned long lastWifiRetryMs = 0;
unsigned long wifiAttemptStartedMs = 0;
bool accessPointStarted = false;

bool wifiStartAccessPoint() {
    const IPAddress apIp(192, 168, 4, 1);
    const IPAddress gateway(192, 168, 4, 1);
    const IPAddress subnet(255, 255, 255, 0);

    if (!WiFi.softAPConfig(apIp, gateway, subnet)) {
        return false;
    }

    if (std::strlen(WIFI_AP_PASSWORD) == 0) {
        return WiFi.softAP(WIFI_AP_SSID);
    }

    return WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASSWORD);
}

void wifiRestartStationConnection(unsigned long now) {
    lastWifiRetryMs = now;
    wifiAttemptStartedMs = now;
    WiFi.disconnect();
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);
}
}

void wifiConnect() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    WiFi.mode(WIFI_AP);
    accessPointStarted = wifiStartAccessPoint();
    lastWifiRetryMs = millis();
#else
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);
    wifiAttemptStartedMs = millis();
    lastWifiRetryMs = wifiAttemptStartedMs;
#endif
}

WifiConnectionState wifiGetConnectionState() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    return accessPointStarted ? WifiConnectionState::Ready : WifiConnectionState::Failed;
#else
    wl_status_t status = WiFi.status();

    if (status == WL_CONNECTED) {
        return WifiConnectionState::Ready;
    }

    const bool failedImmediately =
        status == WL_CONNECT_FAILED || status == WL_NO_SSID_AVAIL || status == WL_CONNECTION_LOST;
    const bool attemptExpired =
        wifiAttemptStartedMs > 0 && (millis() - wifiAttemptStartedMs) >= WIFI_TIMEOUT_MS;

    if (failedImmediately || attemptExpired) {
        return WifiConnectionState::Failed;
    }

    return WifiConnectionState::Connecting;
#endif
}

void wifiEnsureConnected() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    if (accessPointStarted) return;

    unsigned long now = millis();
    if (now - lastWifiRetryMs < WIFI_RETRY_MS) return;

    lastWifiRetryMs = now;
    accessPointStarted = wifiStartAccessPoint();
#else
    unsigned long now = millis();
    if (wifiGetConnectionState() != WifiConnectionState::Failed) return;
    if (now - lastWifiRetryMs < WIFI_RETRY_MS) return;

    wifiRestartStationConnection(now);
#endif
}

void wifiForceReconnect() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    accessPointStarted = false;
    lastWifiRetryMs = millis();
    accessPointStarted = wifiStartAccessPoint();
#else
    wifiRestartStationConnection(millis());
#endif
}

bool wifiWaitUntilReady(unsigned long timeoutMs) {
    const unsigned long startedMs = millis();

    while (!wifiIsReady()) {
        wifiEnsureConnected();

        if (timeoutMs == 0 || millis() - startedMs >= timeoutMs) {
            break;
        }

        delay(50);
    }

    return wifiIsReady();
}

bool wifiIsReady() {
    return wifiGetConnectionState() == WifiConnectionState::Ready;
}

IPAddress wifiGetIpAddress() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    if (accessPointStarted) {
        return WiFi.softAPIP();
    }

    return IPAddress();
#else
    if (WiFi.status() == WL_CONNECTED) {
        return WiFi.localIP();
    }

    return IPAddress();
#endif
}

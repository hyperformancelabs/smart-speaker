#include "net/wifi_service.h"

#include <cstring>

#include <Arduino.h>
#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

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
SemaphoreHandle_t gWifiMutex = nullptr;

void ensureWifiMutex() {
    if (gWifiMutex != nullptr) {
        return;
    }

    gWifiMutex = xSemaphoreCreateMutex();
}

bool lockWifiMutex(TickType_t timeoutTicks = portMAX_DELAY) {
    ensureWifiMutex();
    return gWifiMutex != nullptr && xSemaphoreTake(gWifiMutex, timeoutTicks) == pdTRUE;
}

void unlockWifiMutex() {
    if (gWifiMutex != nullptr) {
        xSemaphoreGive(gWifiMutex);
    }
}

void schedulerFriendlyDelay(unsigned long delayMs) {
    if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING) {
        vTaskDelay(pdMS_TO_TICKS(delayMs));
    } else {
        delay(delayMs);
    }
}

bool wifiStartAccessPointLocked() {
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

void wifiRestartStationConnectionLocked(unsigned long now) {
    lastWifiRetryMs = now;
    wifiAttemptStartedMs = now;
    WiFi.disconnect();
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);
}

WifiConnectionState wifiGetConnectionStateLocked() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    return accessPointStarted ? WifiConnectionState::Ready : WifiConnectionState::Failed;
#else
    const wl_status_t status = WiFi.status();

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
}  // namespace

void wifiConnect() {
    if (!lockWifiMutex()) {
        return;
    }

#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    WiFi.mode(WIFI_AP);
    accessPointStarted = wifiStartAccessPointLocked();
    lastWifiRetryMs = millis();
#else
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);
    wifiAttemptStartedMs = millis();
    lastWifiRetryMs = wifiAttemptStartedMs;
#endif

    unlockWifiMutex();
}

WifiConnectionState wifiGetConnectionState() {
    if (!lockWifiMutex()) {
        return WifiConnectionState::Failed;
    }

    const WifiConnectionState state = wifiGetConnectionStateLocked();
    unlockWifiMutex();
    return state;
}

void wifiEnsureConnected() {
    if (!lockWifiMutex()) {
        return;
    }

#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    if (!accessPointStarted) {
        const unsigned long now = millis();
        if (now - lastWifiRetryMs >= WIFI_RETRY_MS) {
            lastWifiRetryMs = now;
            accessPointStarted = wifiStartAccessPointLocked();
        }
    }
#else
    const unsigned long now = millis();
    if (wifiGetConnectionStateLocked() == WifiConnectionState::Failed &&
        now - lastWifiRetryMs >= WIFI_RETRY_MS) {
        wifiRestartStationConnectionLocked(now);
    }
#endif

    unlockWifiMutex();
}

void wifiForceReconnect() {
    if (!lockWifiMutex()) {
        return;
    }

#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    accessPointStarted = false;
    lastWifiRetryMs = millis();
    accessPointStarted = wifiStartAccessPointLocked();
#else
    wifiRestartStationConnectionLocked(millis());
#endif

    unlockWifiMutex();
}

bool wifiWaitUntilReady(unsigned long timeoutMs) {
    const unsigned long startedMs = millis();

    while (!wifiIsReady()) {
        wifiEnsureConnected();

        if (timeoutMs == 0 || millis() - startedMs >= timeoutMs) {
            break;
        }

        schedulerFriendlyDelay(50);
    }

    return wifiIsReady();
}

bool wifiIsReady() {
    return wifiGetConnectionState() == WifiConnectionState::Ready;
}

IPAddress wifiGetIpAddress() {
    if (!lockWifiMutex()) {
        return IPAddress();
    }

#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    const IPAddress ip = accessPointStarted ? WiFi.softAPIP() : IPAddress();
#else
    const IPAddress ip = WiFi.status() == WL_CONNECTED ? WiFi.localIP() : IPAddress();
#endif

    unlockWifiMutex();
    return ip;
}

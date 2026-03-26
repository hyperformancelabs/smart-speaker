#include "net/wifi_service.h"

#include <cstring>
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
}

void wifiConnect() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    WiFi.mode(WIFI_AP);
    accessPointStarted = wifiStartAccessPoint();
#else
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);

    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < WIFI_TIMEOUT_MS) {
        delay(250);
    }
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
    if (WiFi.status() == WL_CONNECTED) return;

    unsigned long now = millis();
    if (now - lastWifiRetryMs < WIFI_RETRY_MS) return;

    lastWifiRetryMs = now;
    WiFi.disconnect();
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);
#endif
}

bool wifiIsReady() {
#if APP_WIFI_MODE == APP_WIFI_MODE_AP
    return accessPointStarted;
#else
    return WiFi.status() == WL_CONNECTED;
#endif
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

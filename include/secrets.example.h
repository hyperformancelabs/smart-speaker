#ifndef SECRETS_H
#define SECRETS_H

#define APP_WIFI_MODE_STA 0
#define APP_WIFI_MODE_AP  1

// Switch to APP_WIFI_MODE_AP when you want the ESP32 to create its own Wi-Fi
// for direct debugging from a laptop/phone.
#define APP_WIFI_MODE APP_WIFI_MODE_STA

#define WIFI_STA_SSID     "YOUR_WIFI_SSID"
#define WIFI_STA_PASSWORD "YOUR_WIFI_PASSWORD"

#define WIFI_AP_SSID      "ESP32-Audio"
#define WIFI_AP_PASSWORD  "12345678"

// Shared base URL for both the device API calls and the registration page.
#define SERVER_URL "your.server.url"

#endif

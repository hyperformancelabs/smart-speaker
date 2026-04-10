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

// Single public base URL for browser-facing registration and cloud access.
#define SERVER_URL "https://ssproject.hyperformancelabs.click"

// ESP32 should prefer local plain HTTP on the same LAN to avoid TLS memory pressure.
// Replace 192.168.1.9 with the IP of the machine running the local services.
#define DEVICE_API_URL "http://192.168.1.9:8386"
#define DEVICE_VOICE_BACKEND_URL "http://192.168.1.9:8387"

#endif

#pragma once

#include <IPAddress.h>

enum class WifiConnectionState {
    Connecting,
    Ready,
    Failed,
};

void wifiConnect();
void wifiEnsureConnected();
bool wifiIsReady();
WifiConnectionState wifiGetConnectionState();
IPAddress wifiGetIpAddress();

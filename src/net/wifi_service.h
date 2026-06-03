#pragma once

#include <IPAddress.h>

enum class WifiConnectionState {
    Connecting,
    Ready,
    Failed,
};

void wifiConnect();
void wifiEnsureConnected();
void wifiForceReconnect();
bool wifiWaitUntilReady(unsigned long timeoutMs);
bool wifiIsReady();
WifiConnectionState wifiGetConnectionState();
IPAddress wifiGetIpAddress();

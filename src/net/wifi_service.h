#pragma once

#include <IPAddress.h>

void wifiConnect();
void wifiEnsureConnected();
bool wifiIsReady();
IPAddress wifiGetIpAddress();

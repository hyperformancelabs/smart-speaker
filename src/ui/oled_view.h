#pragma once

#include <Arduino.h>

#include "app_state.h"

void oledInit();
void oledDrawStartup(unsigned long elapsedMs);
void oledDrawStartupConnectionError();
void oledDrawWifiReconnect(unsigned long elapsedMs);
void oledDrawAwaitNfc();
void oledDrawLoading(unsigned long elapsedMs);
void oledDrawLookupError();
void oledDrawRegistrationPrompt(const char *registerUrl);
void oledDrawGreeting(const char *name);
void oledDrawWakewordSleep();
void oledDrawStreamingFace(const int16_t rawData[], int rawLen);

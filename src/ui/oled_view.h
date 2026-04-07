#pragma once

#include <Arduino.h>

#include "app_state.h"

void oledInit();
void oledDrawStartup(unsigned long elapsedMs);
void oledDraw(const int16_t rawData[], int rawLen, const WakewordInfo &wakeword, const String &uid);

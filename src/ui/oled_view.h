#pragma once

#include <Arduino.h>

void oledInit();
void oledDraw(const int16_t rawData[], int rawLen, const String &uid);

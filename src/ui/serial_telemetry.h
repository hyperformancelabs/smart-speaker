#pragma once

#include <Arduino.h>

void serialTelemetryBegin();
void serialSendPlotter(const int16_t rawData[], int rawLen, int cardEvent);

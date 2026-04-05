#pragma once

#include <Arduino.h>

#include "app_state.h"

void wakewordInit(WakewordInfo &state);
bool wakewordProcessSamples(const int16_t rawData[], int rawLen, WakewordInfo &state);

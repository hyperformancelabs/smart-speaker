#pragma once

#include <Arduino.h>
#include "app_config.h"

struct AppState {
    bool recordMode = false;
    int16_t rawData[MIC_DMA_LEN] = {};
    int rawLen = 0;
    String lastUid = "(no card)";
    unsigned long lastDemoTick = 0;
    int pendingCardEvent = 0;
};

#pragma once

#include <Arduino.h>
#include "app_config.h"

struct WakewordInfo {
    bool hasInference = false;
    const char *topLabel = "warming";
    float topScore = 0.0f;
    float noiseScore = 0.0f;
    float otherScore = 0.0f;
    float wakeupScore = 0.0f;
    unsigned long lastInferenceMs = 0;
    unsigned long lastDetectionMs = 0;
};

struct AppState {
    int16_t rawData[MIC_DMA_LEN] = {};
    int rawLen = 0;
    String lastUid = "(no card)";
    WakewordInfo wakeword = {};
    unsigned long startupSplashStartedMs = 0;
    unsigned long lastStartupFrameMs = 0;
    unsigned long lastDemoTick = 0;
    bool wifiReadyBeeped = false;
    int pendingCardEvent = 0;
};

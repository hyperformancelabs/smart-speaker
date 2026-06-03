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

struct AudioChunk {
    int16_t samples[MIC_DMA_LEN] = {};
    uint16_t len = 0;
    unsigned long capturedMs = 0;
};

struct AppState {
    AudioChunk latestAudio = {};
    AudioChunk playbackAudio = {};
    char lastUid[32] = "(no card)";
    WakewordInfo wakeword = {};
};

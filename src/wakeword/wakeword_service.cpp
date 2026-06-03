#include "wakeword/wakeword_service.h"

#include <string.h>

#include "app_config.h"
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"

namespace {
static_assert(MIC_SAMPLE_RATE == EI_CLASSIFIER_FREQUENCY,
              "Edge Impulse model sample rate must match microphone sample rate");

constexpr const char *kNoiseLabel = "noise";
constexpr const char *kOtherLabel = "other";
constexpr const char *kWakewordLabel = "wakeup";

int16_t gSliceBuffer[EI_CLASSIFIER_SLICE_SIZE] = {};
size_t gSliceFill = 0;
bool gWakewordLatched = false;

int getAudioSignalData(size_t offset, size_t length, float *outPtr) {
    if (offset + length > EI_CLASSIFIER_SLICE_SIZE) {
        return -1;
    }

    for (size_t i = 0; i < length; ++i) {
        outPtr[i] = static_cast<float>(gSliceBuffer[offset + i]);
    }

    return 0;
}

void resetWakewordState(WakewordInfo &state) {
    state = WakewordInfo{};
}

void updateWakewordInfo(WakewordInfo &state, const ei_impulse_result_t &result) {
    state.hasInference = true;
    state.topLabel = kNoiseLabel;
    state.topScore = 0.0f;
    state.noiseScore = 0.0f;
    state.otherScore = 0.0f;
    state.wakeupScore = 0.0f;
    state.lastInferenceMs = millis();

    for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; ++i) {
        const ei_impulse_result_classification_t &classification = result.classification[i];

        if (strcmp(classification.label, kNoiseLabel) == 0) {
            state.noiseScore = classification.value;
        } else if (strcmp(classification.label, kOtherLabel) == 0) {
            state.otherScore = classification.value;
        } else if (strcmp(classification.label, kWakewordLabel) == 0) {
            state.wakeupScore = classification.value;
        }

        if (classification.value >= state.topScore) {
            state.topLabel = classification.label;
            state.topScore = classification.value;
        }
    }
}

bool shouldTriggerWakeword(WakewordInfo &state) {
    const bool wakewordMatch =
        strcmp(state.topLabel, kWakewordLabel) == 0 &&
        state.wakeupScore >= WAKEWORD_DETECTION_THRESHOLD;

    if (!wakewordMatch) {
        if (state.wakeupScore <= WAKEWORD_RELEASE_THRESHOLD) {
            gWakewordLatched = false;
        }
        return false;
    }

    if (gWakewordLatched) {
        return false;
    }

    if (state.lastDetectionMs != 0 &&
        state.lastInferenceMs - state.lastDetectionMs < WAKEWORD_DETECTION_COOLDOWN_MS) {
        return false;
    }

    gWakewordLatched = true;
    state.lastDetectionMs = state.lastInferenceMs;
    return true;
}
}

void wakewordInit(WakewordInfo &state) {
    memset(gSliceBuffer, 0, sizeof(gSliceBuffer));
    gSliceFill = 0;
    gWakewordLatched = false;
    resetWakewordState(state);
    run_classifier_init();
}

bool wakewordProcessSamples(const int16_t rawData[], int rawLen, WakewordInfo &state) {
    bool detected = false;

    for (int i = 0; i < rawLen; ++i) {
        gSliceBuffer[gSliceFill++] = rawData[i];

        if (gSliceFill < EI_CLASSIFIER_SLICE_SIZE) {
            continue;
        }

        signal_t signal;
        signal.total_length = EI_CLASSIFIER_SLICE_SIZE;
        signal.get_data = &getAudioSignalData;

        ei_impulse_result_t result = {};
        const EI_IMPULSE_ERROR err = run_classifier_continuous(&signal, &result, false);

        gSliceFill = 0;

        if (err != EI_IMPULSE_OK) {
            state.hasInference = false;
            state.topLabel = "ei-error";
            state.topScore = 0.0f;
            continue;
        }

        if (result.timing.classification_us <= 0) {
            state.hasInference = false;
            state.topLabel = "warming";
            state.topScore = 0.0f;
            continue;
        }

        updateWakewordInfo(state, result);
        detected = shouldTriggerWakeword(state) || detected;
    }

    return detected;
}

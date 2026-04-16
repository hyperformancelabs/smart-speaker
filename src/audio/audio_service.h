#pragma once

#include <Arduino.h>
#include <stddef.h>

enum class AudioRouteMode {
    Capture,
    Playback,
};

void audioPrepareOutput();
void audioEnableOutput();
void audioInit();
void audioBeep(int freq = 1200, int ms = 80);
void audioWriteOutputSamples(const int16_t samples[], size_t sampleCount);
void audioLogBootDiagnostics();
void audioSetRouteMode(AudioRouteMode mode);
void audioReadMic(int16_t rawOut[], int &rawLen);
void audioResetWsFrames();
void audioFeedWsFrames(const int16_t rawData[], int rawLen);

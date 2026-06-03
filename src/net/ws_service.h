#pragma once

#include <Arduino.h>

void wsBegin();
void wsLoop();
void wsSendAudioFrame(const int16_t pcm[], int n);

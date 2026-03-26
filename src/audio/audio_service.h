#pragma once

#include <Arduino.h>

void audioPrepareOutput();
void audioEnableOutput();
void audioInit(bool recordMode);
void audioBeep(int freq = 1200, int ms = 80);
void audioPlayLoopback(const int16_t pcm[], int n);
void audioReadMic(int16_t rawOut[], int &rawLen);
void audioFeedWsFrames(const int16_t rawData[], int rawLen);

#pragma once

#include <Arduino.h>

void rfidInit();
bool rfidPoll(char uidOut[], size_t uidOutSize);

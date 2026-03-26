#pragma once

#include <Arduino.h>

void rfidInit();
void rfidPoll(String &lastUid, int &pendingCardEvent);

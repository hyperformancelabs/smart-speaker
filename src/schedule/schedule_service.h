#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

void scheduleInit();
bool scheduleAnnounceDevice(const char *uid);
bool scheduleSyncForUid(const char *uid, const char *reason = nullptr);
void scheduleRequestSync(const char *uid, const char *reason = nullptr);
bool scheduleAlertActive();
void scheduleDismissActiveAlert();

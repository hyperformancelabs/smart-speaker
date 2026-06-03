#pragma once

#include "rtos/app_tasks.h"

bool voiceBackendStartCapture();
void voiceBackendInvalidateCaptureToken();
bool voiceBackendCaptureTokenMatches(const char *captureToken);
bool voiceBackendHandleControlMessage(const char *payload);

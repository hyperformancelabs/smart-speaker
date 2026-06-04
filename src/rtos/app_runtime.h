#pragma once

#include <freertos/FreeRTOS.h>

#include "app_state.h"
#include "net/profile_service.h"
#include "rtos/app_tasks.h"

namespace app_runtime {

enum class AudioSessionMode : uint8_t {
    Idle,
    WaitWakeword,
    Streaming,
    Thinking,
    Speaking,
};

struct BeepRequest {
    int freq = 0;
    int durationMs = 0;
};

struct ProfileLookupRequest {
    char uid[32] = {};
};

struct ProfileLookupResult {
    char uid[32] = {};
    bool requestOk = false;
    ProfileStatus status = {};
};

bool init();

void storeLatestAudio(const AudioChunk &chunk);
void storePlaybackAudio(const int16_t samples[], int sampleCount);
void storeWakewordState(const WakewordInfo &wakeword);
void storeLastUid(const char *uid);
AppState loadAppStateSnapshot();
void clearRealtimeAppState();

void pushWakewordAudio(const AudioChunk &chunk);
bool waitWakewordAudio(AudioChunk &chunk, TickType_t timeoutTicks);
void resetWakewordAudioQueue();

void pushStreamAudio(const AudioChunk &chunk);
bool tryPopStreamAudio(AudioChunk &chunk);
void resetStreamAudioQueue();

void queueBeep(int freq, int durationMs);
bool waitBeep(BeepRequest &request, TickType_t timeoutTicks);
void resetBeepQueue();

void queueProfileLookup(const char *uid);
bool waitProfileLookup(ProfileLookupRequest &request, TickType_t timeoutTicks);
void publishProfileLookupResult(const ProfileLookupResult &result);
bool tryPopProfileLookupResult(ProfileLookupResult &result);
void resetProfileLookupQueues();

void queueAssistantPlayback(const AssistantPlaybackRequest &request);
bool tryPopAssistantPlayback(AssistantPlaybackRequest &request);
void resetAssistantPlaybackQueue();

void setAudioSessionMode(AudioSessionMode nextMode);
AudioSessionMode audioSessionMode();
bool isAudioSessionActive();
bool isMicrophoneCaptureActive();
bool isWakewordDetectionActive();
bool isStreamingActive();
bool isSpeakingActive();

void signalWakewordTransition();
bool consumeWakewordTransition();

void requestExternalAudioSessionState(ExternalAudioSessionState nextState);
bool consumeExternalAudioSessionState(ExternalAudioSessionState &nextState);
void clearPendingExternalAudioSessionState();

}  // namespace app_runtime

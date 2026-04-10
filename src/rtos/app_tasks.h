#pragma once

enum class ExternalAudioSessionState {
    WaitWakeword,
    Streaming,
};

void appTasksStart();
void appRequestExternalAudioSessionState(ExternalAudioSessionState nextState);
const char *appExternalAudioSessionStateName(ExternalAudioSessionState state);

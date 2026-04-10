#pragma once

enum class ExternalAudioSessionState {
    WaitWakeword,
    Streaming,
    Thinking,
};

void appTasksStart();
void appRequestExternalAudioSessionState(ExternalAudioSessionState nextState);
const char *appExternalAudioSessionStateName(ExternalAudioSessionState state);

#pragma once

enum class ExternalAudioSessionState {
    WaitWakeword,
    Streaming,
    Thinking,
    Speaking,
};

struct AssistantPlaybackRequest {
    char captureToken[40] = {};
    char ttsUrl[256] = {};
    char mediaUrl[256] = {};
    char mediaTitle[96] = {};
    ExternalAudioSessionState finalState = ExternalAudioSessionState::Streaming;
};

void appTasksStart();
void appRequestExternalAudioSessionState(ExternalAudioSessionState nextState);
void appQueueAssistantPlayback(const AssistantPlaybackRequest &request);
const char *appExternalAudioSessionStateName(ExternalAudioSessionState state);

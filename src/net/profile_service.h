#pragma once

#include <Arduino.h>

enum class ProfileState : uint8_t {
    Missing,
    Incomplete,
    Ready,
};

struct ProfileStatus {
    ProfileState state = ProfileState::Missing;
    char name[64] = {};
};

bool profileFetchStatus(const char *uid, ProfileStatus &status);
bool profileWarmupConnection();
bool profileIsComplete(const ProfileStatus &status);

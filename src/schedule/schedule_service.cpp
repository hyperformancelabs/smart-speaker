#include "schedule/schedule_service.h"

#include <cstdlib>
#include <cstring>

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <sys/time.h>
#include <time.h>

#include "app_config.h"
#include "audio/audio_service.h"
#include "net/voice_backend_service.h"
#include "net/wifi_service.h"
#include "rtos/app_runtime.h"
#include "rtos/app_tasks.h"
#include "secrets.h"

#ifndef DEVICE_API_URL
#define DEVICE_API_URL SERVER_URL
#endif

#ifndef DEVICE_VOICE_BACKEND_URL
#define DEVICE_VOICE_BACKEND_URL SERVER_URL
#endif

namespace {
namespace runtime = app_runtime;

constexpr uint16_t kScheduleConnectTimeoutMs = 2500;
constexpr uint16_t kScheduleRequestTimeoutMs = 6500;
constexpr unsigned long kScheduleWifiReadyWaitMs = 1500;
constexpr unsigned long kScheduleWakewordSyncPollMs = 50;
constexpr char kScheduleSyncPathPrefix[] = "/api/device/users/";
constexpr char kScheduleSyncPathSuffix[] = "/schedule-sync";
constexpr char kScheduleEventPathSuffix[] = "/schedule-events";
constexpr char kDeviceAnnouncePath[] = "/api/device/announce";
constexpr size_t kMaxScheduleEntries = 16;
constexpr size_t kScheduleEventQueueDepth = 4;
constexpr uint32_t kScheduleTaskStackBytes = 8192;
constexpr UBaseType_t kScheduleTaskPriority = 5;
constexpr BaseType_t kScheduleTaskCore = 0;
constexpr int kAlertBeepFreq = 1400;
constexpr int kAlertBeepMs = 220;
constexpr int kAlertPauseMs = 120;
constexpr unsigned long kAlertMaxDurationMs = 10000;

enum class ScheduleRepeat : uint8_t {
    Once,
    Daily,
    Weekly,
};

enum class ScheduleEventType : uint8_t {
    SyncRequest,
    TimerExpired,
};

struct ScheduleEntry {
    bool active = false;
    bool isTimer = false;
    int64_t dueEpochSeconds = 0;
    ScheduleRepeat repeat = ScheduleRepeat::Once;
    char id[40] = {};
};

struct ScheduleEvent {
    ScheduleEventType type = ScheduleEventType::TimerExpired;
    char uid[32] = {};
    char reason[32] = {};
};

QueueHandle_t gScheduleEventQueue = nullptr;
TaskHandle_t gScheduleTaskHandle = nullptr;
esp_timer_handle_t gScheduleTimer = nullptr;
ScheduleEntry gScheduleEntries[kMaxScheduleEntries] = {};
portMUX_TYPE gScheduleMux = portMUX_INITIALIZER_UNLOCKED;
bool gAlertActive = false;
bool gAlertCancelRequested = false;
char gActiveScheduleUid[32] = {};
bool gInitialized = false;

void copyText(char dest[], size_t destSize, const char *src) {
    if (destSize == 0) {
        return;
    }

    if (src == nullptr) {
        src = "";
    }

    std::strncpy(dest, src, destSize - 1);
    dest[destSize - 1] = '\0';
}

bool hasUsableUid(const char *uid) {
    return uid != nullptr && uid[0] != '\0' && strcmp(uid, "(no card)") != 0;
}

ScheduleRepeat parseRepeat(const String &value) {
    if (value.equalsIgnoreCase("daily")) {
        return ScheduleRepeat::Daily;
    }
    if (value.equalsIgnoreCase("weekly")) {
        return ScheduleRepeat::Weekly;
    }
    return ScheduleRepeat::Once;
}

int64_t repeatIntervalSeconds(ScheduleRepeat repeat) {
    switch (repeat) {
        case ScheduleRepeat::Daily:
            return 24LL * 60LL * 60LL;
        case ScheduleRepeat::Weekly:
            return 7LL * 24LL * 60LL * 60LL;
        case ScheduleRepeat::Once:
            return 0;
    }
    return 0;
}

void pushScheduleEvent(const ScheduleEvent &event) {
    if (gScheduleEventQueue == nullptr) {
        return;
    }

    if (xQueueSend(gScheduleEventQueue, &event, 0) == pdPASS) {
        return;
    }

    ScheduleEvent dropped = {};
    xQueueReceive(gScheduleEventQueue, &dropped, 0);
    xQueueSend(gScheduleEventQueue, &event, 0);
}

void onScheduleTimer(void *arg) {
    (void)arg;
    ScheduleEvent event = {};
    event.type = ScheduleEventType::TimerExpired;
    pushScheduleEvent(event);
}

void setSystemEpochSeconds(int64_t epochSeconds) {
    if (epochSeconds <= 0) {
        return;
    }

    timeval tv = {};
    tv.tv_sec = static_cast<time_t>(epochSeconds);
    tv.tv_usec = 0;
    settimeofday(&tv, nullptr);
}

bool parseScheduleEntryLine(const String &line, ScheduleEntry &entry) {
    const int firstPipe = line.indexOf('|');
    if (firstPipe <= 0) {
        return false;
    }

    const int secondPipe = line.indexOf('|', firstPipe + 1);
    const int thirdPipe = line.indexOf('|', secondPipe + 1);
    if (secondPipe <= firstPipe || thirdPipe <= secondPipe) {
        return false;
    }

    const String kind = line.substring(0, firstPipe);
    const String scheduleId = line.substring(firstPipe + 1, secondPipe);
    const String dueEpoch = line.substring(secondPipe + 1, thirdPipe);
    const String repeat = line.substring(thirdPipe + 1);

    if (scheduleId.length() == 0 || dueEpoch.length() == 0) {
        return false;
    }

    const long long parsedDueEpoch = std::strtoll(dueEpoch.c_str(), nullptr, 10);
    if (parsedDueEpoch <= 0) {
        return false;
    }

    entry = {};
    entry.active = true;
    entry.isTimer = kind.equalsIgnoreCase("timer");
    entry.dueEpochSeconds = static_cast<int64_t>(parsedDueEpoch);
    entry.repeat = parseRepeat(repeat);
    copyText(entry.id, sizeof(entry.id), scheduleId.c_str());
    return true;
}

size_t parseSchedulePayload(const String &payload,
                            ScheduleEntry parsedEntries[],
                            size_t maxEntries,
                            int64_t &serverEpochSeconds) {
    serverEpochSeconds = 0;
    size_t parsedCount = 0;
    int lineStart = 0;

    while (lineStart <= payload.length()) {
        int lineEnd = payload.indexOf('\n', lineStart);
        if (lineEnd < 0) {
            lineEnd = payload.length();
        }

        String line = payload.substring(lineStart, lineEnd);
        line.trim();
        if (line.length() > 0) {
            if (line.startsWith("server_epoch=")) {
                const String epochValue = line.substring(strlen("server_epoch="));
                serverEpochSeconds = std::strtoll(epochValue.c_str(), nullptr, 10);
            } else if ((line.startsWith("alarm|") || line.startsWith("timer|")) &&
                       parsedCount < maxEntries) {
                ScheduleEntry entry = {};
                if (parseScheduleEntryLine(line, entry)) {
                    parsedEntries[parsedCount++] = entry;
                }
            }
        }

        if (lineEnd >= payload.length()) {
            break;
        }
        lineStart = lineEnd + 1;
    }

    return parsedCount;
}

void replaceSchedules(const ScheduleEntry entries[], size_t count) {
    taskENTER_CRITICAL(&gScheduleMux);
    for (size_t index = 0; index < kMaxScheduleEntries; ++index) {
        gScheduleEntries[index] = {};
    }
    for (size_t index = 0; index < count && index < kMaxScheduleEntries; ++index) {
        gScheduleEntries[index] = entries[index];
    }
    taskEXIT_CRITICAL(&gScheduleMux);
}

bool loadAlertActive() {
    taskENTER_CRITICAL(&gScheduleMux);
    const bool active = gAlertActive;
    taskEXIT_CRITICAL(&gScheduleMux);
    return active;
}

bool loadAlertCancelRequested() {
    taskENTER_CRITICAL(&gScheduleMux);
    const bool cancelRequested = gAlertCancelRequested;
    taskEXIT_CRITICAL(&gScheduleMux);
    return cancelRequested;
}

void setAlertState(bool active, bool cancelRequested) {
    taskENTER_CRITICAL(&gScheduleMux);
    gAlertActive = active;
    gAlertCancelRequested = cancelRequested;
    taskEXIT_CRITICAL(&gScheduleMux);
}

void setActiveScheduleUid(const char *uid) {
    taskENTER_CRITICAL(&gScheduleMux);
    copyText(gActiveScheduleUid, sizeof(gActiveScheduleUid), uid);
    taskEXIT_CRITICAL(&gScheduleMux);
}

void loadActiveScheduleUid(char dest[], size_t destSize) {
    taskENTER_CRITICAL(&gScheduleMux);
    copyText(dest, destSize, gActiveScheduleUid);
    taskEXIT_CRITICAL(&gScheduleMux);
}

void armNextScheduleTimer() {
    int64_t earliestDueEpoch = 0;
    taskENTER_CRITICAL(&gScheduleMux);
    for (size_t index = 0; index < kMaxScheduleEntries; ++index) {
        const ScheduleEntry &entry = gScheduleEntries[index];
        if (!entry.active || entry.dueEpochSeconds <= 0) {
            continue;
        }
        if (earliestDueEpoch == 0 || entry.dueEpochSeconds < earliestDueEpoch) {
            earliestDueEpoch = entry.dueEpochSeconds;
        }
    }
    taskEXIT_CRITICAL(&gScheduleMux);

    if (gScheduleTimer == nullptr) {
        return;
    }

    if (esp_timer_is_active(gScheduleTimer)) {
        esp_timer_stop(gScheduleTimer);
    }

    if (earliestDueEpoch <= 0) {
        return;
    }

    const int64_t nowEpoch = static_cast<int64_t>(time(nullptr));
    if (earliestDueEpoch <= nowEpoch) {
        ScheduleEvent event = {};
        event.type = ScheduleEventType::TimerExpired;
        pushScheduleEvent(event);
        return;
    }

    const int64_t deltaUs = (earliestDueEpoch - nowEpoch) * 1000000LL;
    esp_timer_start_once(gScheduleTimer, deltaUs);
}

String buildScheduleSyncUrl(const char *uid) {
    String url = DEVICE_API_URL;
    url += kScheduleSyncPathPrefix;
    url += uid;
    url += kScheduleSyncPathSuffix;
    return url;
}

String buildScheduleEventUrl(const char *uid) {
    String url = DEVICE_API_URL;
    url += kScheduleSyncPathPrefix;
    url += uid;
    url += kScheduleEventPathSuffix;
    return url;
}

bool performHttpGetText(const String &url, String &responseBody, int &httpCode) {
    responseBody = "";
    httpCode = 0;

    const bool useTls = url.startsWith("https://");
    if (useTls) {
        WiFiClientSecure client;
        client.setInsecure();
        HTTPClient http;
        http.setConnectTimeout(kScheduleConnectTimeoutMs);
        http.setTimeout(kScheduleRequestTimeoutMs);
        if (!http.begin(client, url)) {
            return false;
        }
        httpCode = http.GET();
        if (httpCode > 0) {
            responseBody = http.getString();
        }
        http.end();
        return true;
    }

    WiFiClient client;
    HTTPClient http;
    http.setConnectTimeout(kScheduleConnectTimeoutMs);
    http.setTimeout(kScheduleRequestTimeoutMs);
    if (!http.begin(client, url)) {
        return false;
    }
    httpCode = http.GET();
    if (httpCode > 0) {
        responseBody = http.getString();
    }
    http.end();
    return true;
}

bool performHttpPostJson(const String &url, const String &payload, int &httpCode) {
    httpCode = 0;
    const bool useTls = url.startsWith("https://");
    if (useTls) {
        WiFiClientSecure client;
        client.setInsecure();
        HTTPClient http;
        http.setConnectTimeout(kScheduleConnectTimeoutMs);
        http.setTimeout(kScheduleRequestTimeoutMs);
        if (!http.begin(client, url)) {
            return false;
        }
        http.addHeader("Content-Type", "application/json");
        httpCode = http.POST(payload);
        http.end();
        return true;
    }

    WiFiClient client;
    HTTPClient http;
    http.setConnectTimeout(kScheduleConnectTimeoutMs);
    http.setTimeout(kScheduleRequestTimeoutMs);
    if (!http.begin(client, url)) {
        return false;
    }
    http.addHeader("Content-Type", "application/json");
    httpCode = http.POST(payload);
    http.end();
    return true;
}

bool shouldDeferScheduleSyncForWakeword() {
    return (!runtime::isAudioSessionActive() || runtime::isWakewordDetectionActive()) &&
           !loadAlertActive();
}

bool reportConsumedSchedules(const ScheduleEntry entries[], size_t count) {
    if (entries == nullptr || count == 0) {
        return true;
    }

    char uid[sizeof(gActiveScheduleUid)] = {};
    loadActiveScheduleUid(uid, sizeof(uid));
    if (!hasUsableUid(uid)) {
        return false;
    }

    String payload = "{\"events\":[";
    size_t eventCount = 0;
    for (size_t index = 0; index < count; ++index) {
        const ScheduleEntry &entry = entries[index];
        if (entry.id[0] == '\0' || entry.repeat != ScheduleRepeat::Once) {
            continue;
        }

        if (eventCount > 0) {
            payload += ",";
        }
        payload += "{\"kind\":\"";
        payload += entry.isTimer ? "timer" : "alarm";
        payload += "\",\"schedule_id\":\"";
        payload += entry.id;
        payload += "\",\"event\":\"triggered\"}";
        ++eventCount;
    }
    payload += "]}";

    if (eventCount == 0) {
        return true;
    }

    if (!wifiWaitUntilReady(kScheduleWifiReadyWaitMs)) {
        return false;
    }

    const String url = buildScheduleEventUrl(uid);
    int httpCode = 0;
    const bool requestStarted = performHttpPostJson(url, payload, httpCode);
    if (!requestStarted || (httpCode != HTTP_CODE_OK && httpCode != HTTP_CODE_ACCEPTED)) {
        Serial.printf("reportConsumedSchedules failed: uid=%s started=%s code=%d\n",
                      uid,
                      requestStarted ? "yes" : "no",
                      httpCode);
        return false;
    }

    return true;
}

void handleDueSchedules() {
    const int64_t nowEpoch = static_cast<int64_t>(time(nullptr));
    ScheduleEntry dueEntries[kMaxScheduleEntries] = {};
    size_t dueCount = 0;

    taskENTER_CRITICAL(&gScheduleMux);
    for (size_t index = 0; index < kMaxScheduleEntries; ++index) {
        ScheduleEntry &entry = gScheduleEntries[index];
        if (!entry.active || entry.dueEpochSeconds <= 0 || entry.dueEpochSeconds > nowEpoch) {
            continue;
        }

        if (dueCount < kMaxScheduleEntries) {
            dueEntries[dueCount] = entry;
            ++dueCount;
        }
        const int64_t intervalSeconds = repeatIntervalSeconds(entry.repeat);
        if (intervalSeconds <= 0) {
            entry = {};
            continue;
        }

        do {
            entry.dueEpochSeconds += intervalSeconds;
        } while (entry.dueEpochSeconds <= nowEpoch);
    }
    taskEXIT_CRITICAL(&gScheduleMux);

    if (dueCount == 0) {
        armNextScheduleTimer();
        return;
    }

    runtime::resetBeepQueue();
    runtime::resetWakewordAudioQueue();
    runtime::resetStreamAudioQueue();
    runtime::storePlaybackAudio(nullptr, 0);
    runtime::clearPendingExternalAudioSessionState();
    voiceBackendInvalidateCaptureToken();
    setAlertState(true, false);

    const unsigned long alertStartedMs = millis();
    while ((millis() - alertStartedMs) < kAlertMaxDurationMs) {
        if (loadAlertCancelRequested()) {
            break;
        }

        audioBeep(kAlertBeepFreq, kAlertBeepMs);
        if (loadAlertCancelRequested()) {
            break;
        }

        vTaskDelay(pdMS_TO_TICKS(kAlertPauseMs));
    }

    runtime::resetBeepQueue();
    setAlertState(false, false);
    reportConsumedSchedules(dueEntries, dueCount);
    appRequestExternalAudioSessionState(ExternalAudioSessionState::WaitWakeword);
    armNextScheduleTimer();
}

void scheduleTask(void *param) {
    (void)param;

    ScheduleEvent event = {};
    ScheduleEvent deferredSync = {};
    bool hasDeferredSync = false;
    for (;;) {
        if (hasDeferredSync && !shouldDeferScheduleSyncForWakeword()) {
            scheduleSyncForUid(deferredSync.uid, deferredSync.reason);
            hasDeferredSync = false;
            deferredSync = {};
            continue;
        }

        const TickType_t waitTicks =
            hasDeferredSync ? pdMS_TO_TICKS(kScheduleWakewordSyncPollMs) : portMAX_DELAY;
        if (!xQueueReceive(gScheduleEventQueue, &event, waitTicks)) {
            continue;
        }

        if (event.type == ScheduleEventType::SyncRequest) {
            if (shouldDeferScheduleSyncForWakeword()) {
                deferredSync = event;
                hasDeferredSync = true;
                continue;
            }
            scheduleSyncForUid(event.uid, event.reason);
            continue;
        }

        if (event.type == ScheduleEventType::TimerExpired) {
            handleDueSchedules();
        }
    }
}
}  // namespace

void scheduleInit() {
    if (gInitialized) {
        return;
    }

    gScheduleEventQueue = xQueueCreate(kScheduleEventQueueDepth, sizeof(ScheduleEvent));
    if (gScheduleEventQueue == nullptr) {
        Serial.println("schedule: failed to allocate event queue");
        return;
    }

    esp_timer_create_args_t timerArgs = {};
    timerArgs.callback = &onScheduleTimer;
    timerArgs.name = "schedule_timer";
    if (esp_timer_create(&timerArgs, &gScheduleTimer) != ESP_OK) {
        Serial.println("schedule: failed to create esp_timer");
        return;
    }

    if (xTaskCreatePinnedToCore(scheduleTask,
                                "schedule",
                                kScheduleTaskStackBytes,
                                nullptr,
                                kScheduleTaskPriority,
                                &gScheduleTaskHandle,
                                kScheduleTaskCore) != pdPASS) {
        Serial.println("schedule: failed to create schedule task");
        return;
    }

    gInitialized = true;
}

bool scheduleAnnounceDevice(const char *uid) {
    if (!hasUsableUid(uid)) {
        return false;
    }

    if (!wifiWaitUntilReady(kScheduleWifiReadyWaitMs)) {
        return false;
    }

    const IPAddress ip = wifiGetIpAddress();
    if (ip == IPAddress()) {
        return false;
    }

    const String url = String(DEVICE_VOICE_BACKEND_URL) + kDeviceAnnouncePath;
    const String ipString = ip.toString();
    String payload = "{";
    payload += "\"ws_host\":\"";
    payload += ipString;
    payload += "\",";
    payload += "\"ws_port\":";
    payload += String(WS_PORT);
    payload += ",";
    payload += "\"device_id\":\"";
    payload += ipString;
    payload += "\",";
    payload += "\"nfc_tag_id\":\"";
    payload += uid;
    payload += "\"}";

    int httpCode = 0;
    const bool requestStarted = performHttpPostJson(url, payload, httpCode);
    if (!requestStarted || (httpCode != HTTP_CODE_OK && httpCode != HTTP_CODE_ACCEPTED)) {
        Serial.printf("scheduleAnnounceDevice failed: started=%s code=%d\n",
                      requestStarted ? "yes" : "no",
                      httpCode);
        return false;
    }

    return true;
}

bool scheduleSyncForUid(const char *uid, const char *reason) {
    if (!hasUsableUid(uid)) {
        return false;
    }

    if (!wifiWaitUntilReady(kScheduleWifiReadyWaitMs)) {
        return false;
    }

    const String url = buildScheduleSyncUrl(uid);
    String responseBody = "";
    int httpCode = 0;
    const bool requestStarted = performHttpGetText(url, responseBody, httpCode);
    if (!requestStarted || httpCode != HTTP_CODE_OK) {
        Serial.printf("scheduleSyncForUid failed: uid=%s reason=%s started=%s code=%d\n",
                      uid,
                      reason != nullptr ? reason : "",
                      requestStarted ? "yes" : "no",
                      httpCode);
        return false;
    }

    ScheduleEntry parsedEntries[kMaxScheduleEntries] = {};
    int64_t serverEpochSeconds = 0;
    const size_t parsedCount =
        parseSchedulePayload(responseBody, parsedEntries, kMaxScheduleEntries, serverEpochSeconds);
    if (serverEpochSeconds > 0) {
        setSystemEpochSeconds(serverEpochSeconds);
    }
    replaceSchedules(parsedEntries, parsedCount);
    setActiveScheduleUid(uid);
    armNextScheduleTimer();

    Serial.printf("scheduleSyncForUid ok: uid=%s reason=%s entries=%u server_epoch=%lld\n",
                  uid,
                  reason != nullptr ? reason : "",
                  static_cast<unsigned>(parsedCount),
                  static_cast<long long>(serverEpochSeconds));
    return true;
}

void scheduleRequestSync(const char *uid, const char *reason) {
    if (!hasUsableUid(uid)) {
        return;
    }

    ScheduleEvent event = {};
    event.type = ScheduleEventType::SyncRequest;
    copyText(event.uid, sizeof(event.uid), uid);
    copyText(event.reason, sizeof(event.reason), reason != nullptr ? reason : "schedule_sync_request");
    pushScheduleEvent(event);
}

bool scheduleAlertActive() {
    return loadAlertActive();
}

void scheduleDismissActiveAlert() {
    if (!loadAlertActive()) {
        return;
    }

    taskENTER_CRITICAL(&gScheduleMux);
    gAlertCancelRequested = true;
    taskEXIT_CRITICAL(&gScheduleMux);
}

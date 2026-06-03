# RTOS architecture

This project now runs as a small FreeRTOS pipeline on ESP32 instead of doing all work inside `loop()`.

## Task layout

- Core 1: `audio_capture`
  Reads microphone samples from I2S, updates the latest UI snapshot, and fans out audio chunks to downstream queues.
- Core 1: `wakeword`
  Consumes audio chunks for Edge Impulse inference and queues a beep when the wake word is detected.
- Core 0: `network`
  Owns `wifiEnsureConnected()`, `wsLoop()`, and WebSocket audio streaming so network state stays serialized.
- Core 0: `ui`
  Drives the startup screen, OLED refresh, serial telemetry, and RFID polling at a lower priority.
- Core 0: `beep`
  Plays queued beeps asynchronously so startup, RFID, and wakeword feedback no longer block the main flow.

## Data flow

- `audio_capture -> wakeword` via a bounded queue
- `audio_capture -> network` via a bounded queue
- `wakeword/ui -> beep` via a beep queue
- Shared OLED snapshot via a mutex-protected `AppState`

## Coordination

- `app_runtime` owns the shared queues, app snapshot, and cross-core session flags so task code no longer edits scattered globals directly.
- `playback_service` owns WAV parsing and HTTP audio playback so `app_tasks.cpp` stays focused on orchestration.
- `wifi_service` serializes `WiFi` access with an internal mutex because reconnects, status checks, and HTTP-triggered waits now come from multiple tasks.
- `audioBeep()` now keeps exclusive control of the shared I2S route for the full tone, which avoids route flapping during wakeword/NFC feedback.

## Why this layout

- Audio capture is the most timing-sensitive path, so it gets the highest priority.
- Wakeword inference stays close to capture on the application core to reduce handoff latency.
- Wi-Fi and WebSocket handling stay together to avoid concurrent access patterns around the networking stack.
- UI and RFID are intentionally lower priority because they can tolerate jitter better than audio and network I/O.

## Next tuning ideas

- If inference ever falls behind, replace queue-by-copy audio chunks with a ring buffer or pointer pool.
- If beeps still interfere with capture on your hardware, move output to a dedicated I2S path or mix tones in a dedicated audio task.
- Add runtime instrumentation such as queue fill levels and stack high-water marks before increasing throughput further.

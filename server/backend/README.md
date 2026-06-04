# Backend Setup

This service runs the full voice pipeline for the speaker:

- websocket audio capture from ESP
- STT with `Groq Whisper`
- orchestration / tool calling based on the `.local/llm-orches` prototype
- VieNeu TTS generation
- YouTube/media proxying and WAV transcoding for ESP playback

## Environment

Backend config is read from `server/backend/.env`.
Use `server/backend/.env.example` as the template.

Important fields:

- `BACKEND_API_URL`: URL of the database service, usually `http://localhost:8386`
- `GROQ_API_KEY`: required for Groq Speech-to-Text
- `GROQ_STT_MODEL`: default `whisper-large-v3-turbo`
- `GROQ_STT_LANGUAGE`: optional ISO-639-1 hint such as `vi` or `en`
- `GROQ_STT_PROMPT`: optional spelling/context hint for transcription
- `GROQ_STT_RESPONSE_FORMAT`: `json`, `verbose_json`, or `text`
- `GROQ_STT_TEMPERATURE`: recommended default is `0`
- `GROQ_STT_TIMESTAMP_GRANULARITIES`: comma-separated `segment`, `word`, or both when using `verbose_json`
- `GROQ_STT_TIMEOUT_SECONDS`: request timeout passed to the Groq SDK
- `GROQ_STT_MAX_RETRIES`: retry count passed to the Groq SDK
- `GROQ_STT_BASE_URL`: optional override for Groq-compatible base URL
- `VOICE_BACKEND_PORT`: HTTP port for this service, usually `8387`
- `VOICE_BACKEND_PUBLIC_BASE_URL`: base URL that the ESP can reach to fetch TTS/media assets
- `OPENROUTER_API_KEY`: required for the LLM orchestration
- `OPENROUTER_BASE_URL`: optional OpenRouter chat completions endpoint override
- `OPENROUTER_REASONING_ENABLED`: set `false` for low-latency non-thinking calls
- `YT_DLP_BIN`: needed for YouTube search/stream resolution
- `FFMPEG_BIN`: needed for media WAV transcoding

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/backend/requirements.txt
python3 server/backend/app.py
```

## Health Check

```bash
curl http://localhost:8387/health
```

## Main Endpoints

- `POST /api/audio/start`: start ESP websocket capture + full STT -> agent -> TTS flow
- `GET /api/audio/status`: inspect the latest capture / assistant turn
- `POST /api/process-command`: text-only assistant turn for local testing
- `POST /api/test`: quick smoke test with a default prompt
- `POST /api/dev/assistant-turn`: debug route for text or uploaded audio from browser / CLI
- `POST /api/dev/session/reset`: clear cached session state for a browser / CLI / device identity
- `GET /api/dev/sessions`: inspect in-memory backend sessions
- `GET /api/assets/tts/<id>.wav`: normalized TTS WAV asset
- `GET /api/assets/media/<id>.wav`: ffmpeg-transcoded WAV stream for ESP playback

## Local Debugging

Web lab:

```bash
open http://localhost:8387/dev/assistant
```

Text CLI:

```bash
python3 server/backend/assistant_cli.py --base-url http://127.0.0.1:8387
```

Voice CLI:

```bash
python3 server/backend/assistant_cli_v2.py --base-url http://127.0.0.1:8387
```

Shortcut alias:

```bash
python3 server/backend/voice_test_cli.py --base-url http://127.0.0.1:8387
```

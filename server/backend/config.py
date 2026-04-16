import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

# LLM configuration
LLM_MODEL = os.getenv("LLM_MODEL", "gemma-3-27b-it")
SMALL_LLM_MODEL = os.getenv("SMALL_LLM_MODEL", "gemma-3-4b-it")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# Database API
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8386")

# Voice backend HTTP service
VOICE_BACKEND_PORT = int(os.getenv("VOICE_BACKEND_PORT", os.getenv("LLM_API_PORT", "8387")))
VOICE_BACKEND_PUBLIC_BASE_URL = os.getenv(
    "VOICE_BACKEND_PUBLIC_BASE_URL",
    os.getenv("LLM_PUBLIC_BASE_URL", f"http://localhost:{VOICE_BACKEND_PORT}"),
)

# Backward-compatible aliases kept for copied modules.
LLM_API_URL = VOICE_BACKEND_PUBLIC_BASE_URL
LLM_API_PORT = VOICE_BACKEND_PORT
LLM_PUBLIC_BASE_URL = VOICE_BACKEND_PUBLIC_BASE_URL

# Search and fetch tools
WEB_SEARCH_SOURCE = os.getenv("WEB_SEARCH_SOURCE", "duckduckgo_html")
WEB_SEARCH_URL = os.getenv("WEB_SEARCH_URL", "https://html.duckduckgo.com/html/")
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "10"))
WEB_SEARCH_FETCH_LIMIT = int(os.getenv("WEB_SEARCH_FETCH_LIMIT", "3"))
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "10"))
FETCH_MAX_CONTENT_CHARS = int(os.getenv("FETCH_MAX_CONTENT_CHARS", "2500"))
FETCH_MAX_ITEMS = int(os.getenv("FETCH_MAX_ITEMS", "3"))

# YouTube / media tools
YT_DLP_BIN = os.getenv("YT_DLP_BIN", "yt-dlp")
YOUTUBE_TOOL_TIMEOUT = int(os.getenv("YOUTUBE_TOOL_TIMEOUT", "25"))
YOUTUBE_SEARCH_MAX_RESULTS = int(os.getenv("YOUTUBE_SEARCH_MAX_RESULTS", "5"))
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
MEDIA_TRANSCODE_TIMEOUT = int(os.getenv("MEDIA_TRANSCODE_TIMEOUT", "3600"))
MEDIA_TRANSCODE_SAMPLE_RATE = int(os.getenv("MEDIA_TRANSCODE_SAMPLE_RATE", "16000"))
MEDIA_TRANSCODE_CHANNELS = int(os.getenv("MEDIA_TRANSCODE_CHANNELS", "1"))

# TTS assets
ASSET_STORAGE_DIR = Path(os.getenv("ASSET_STORAGE_DIR", BASE_DIR / "generated_assets")).expanduser()
TTS_STORAGE_DIR = ASSET_STORAGE_DIR / "tts"
MEDIA_STORAGE_DIR = ASSET_STORAGE_DIR / "media"
TTS_VOICE_ID = int(os.getenv("TTS_VOICE_ID", "2"))
TTS_NORMALIZE_SAMPLE_RATE = int(os.getenv("TTS_NORMALIZE_SAMPLE_RATE", "16000"))
TTS_NORMALIZE_CHANNELS = int(os.getenv("TTS_NORMALIZE_CHANNELS", "1"))

# ESP/device session behavior
EDGE_PAYLOAD_VERSION = int(os.getenv("EDGE_PAYLOAD_VERSION", "2"))
DEVICE_SESSION_TTL_SECONDS = int(os.getenv("DEVICE_SESSION_TTL_SECONDS", "3600"))

# Conversation
MAX_CONVERSATION_HISTORY = int(os.getenv("MAX_CONVERSATION_HISTORY", "5"))
MAX_MEMORY_ITEMS = int(os.getenv("MAX_MEMORY_ITEMS", "20"))
MAX_CONTEXT_SUMMARY_CHARS = int(os.getenv("MAX_CONTEXT_SUMMARY_CHARS", "1500"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "llm_pipeline.log")
LOG_FILE_PATH = Path(LOG_FILE).expanduser()
if not LOG_FILE_PATH.is_absolute():
    LOG_FILE_PATH = (BASE_DIR / LOG_FILE_PATH).resolve()

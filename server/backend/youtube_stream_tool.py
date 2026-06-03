from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any
from urllib.parse import urlencode

from config import LLM_PUBLIC_BASE_URL, YOUTUBE_SEARCH_MAX_RESULTS, YOUTUBE_TOOL_TIMEOUT, YT_DLP_BIN

YOUTUBE_WATCH_BASE_URL = "https://www.youtube.com/watch?v="
YOUTUBE_PROXY_PATH = "/api/media/youtube/stream"
AUDIO_EXT_PREFERENCE = {
    "m4a": 16,
    "mp4": 14,
    "mp3": 12,
    "aac": 10,
    "webm": 8,
    "ogg": 6,
    "opus": 6,
}
VIDEO_EXT_PREFERENCE = {
    "mp4": 16,
    "webm": 12,
    "mkv": 8,
}


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in {"", None}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {"", None}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _find_yt_dlp() -> str | None:
    candidates = []
    configured = (YT_DLP_BIN or "").strip()
    if configured:
        candidates.append(configured)
    if "yt-dlp" not in candidates:
        candidates.append("yt-dlp")

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def yt_dlp_is_available() -> bool:
    return bool(_find_yt_dlp())


def _run_yt_dlp_json(arguments: list[str], timeout: int = YOUTUBE_TOOL_TIMEOUT) -> dict[str, Any]:
    binary = _find_yt_dlp()
    if not binary:
        raise RuntimeError("yt-dlp chưa có trong environment đang chạy app")

    completed = subprocess.run(
        [binary, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        raise RuntimeError(stderr or stdout or "yt-dlp returned a non-zero exit code")

    if not stdout:
        raise RuntimeError("yt-dlp không trả JSON output")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Không parse được JSON từ yt-dlp: {exc}") from exc


def _watch_url(video_id: str) -> str:
    return f"{YOUTUBE_WATCH_BASE_URL}{video_id}"


def _pick_thumbnail_url(data: dict[str, Any]) -> str:
    if data.get("thumbnail"):
        return str(data["thumbnail"])

    thumbnails = data.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumbnail in reversed(thumbnails):
            if isinstance(thumbnail, dict) and thumbnail.get("url"):
                return str(thumbnail["url"])

    return ""


def _normalize_search_entry(entry: dict[str, Any]) -> dict[str, Any]:
    video_id = str(entry.get("id") or entry.get("url") or "")
    return {
        "video_id": video_id,
        "title": entry.get("title", ""),
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "channel_id": entry.get("channel_id") or entry.get("uploader_id") or "",
        "duration_seconds": _coerce_int(entry.get("duration")),
        "view_count": _coerce_int(entry.get("view_count")),
        "webpage_url": entry.get("webpage_url") or _watch_url(video_id),
        "thumbnail_url": _pick_thumbnail_url(entry),
        "description": (entry.get("description") or "")[:320],
    }


def youtube_search_videos(query: str, max_results: int = YOUTUBE_SEARCH_MAX_RESULTS) -> dict[str, Any]:
    payload = _run_yt_dlp_json(
        [
            "--dump-single-json",
            "--flat-playlist",
            "--no-playlist",
            "--no-warnings",
            f"ytsearch{max_results}:{query}",
        ]
    )
    entries = payload.get("entries") or []
    results = [
        _normalize_search_entry(entry)
        for entry in entries
        if isinstance(entry, dict) and (entry.get("id") or entry.get("url"))
    ]
    return {
        "query": query,
        "source": "youtube_yt_dlp",
        "results": results,
    }


def _extract_single_video_info(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("entries"):
        entries = payload.get("entries") or []
        for entry in entries:
            if isinstance(entry, dict):
                return entry
        return {}
    return payload


def _protocol_score(protocol: str) -> int:
    normalized = (protocol or "").lower()
    if normalized.startswith("https"):
        return 16
    if normalized.startswith("http"):
        return 14
    if normalized in {"m3u8_native", "m3u8"}:
        return 10
    if "dash" in normalized:
        return 6
    return 0


def _infer_content_type(format_data: dict[str, Any], mode: str) -> str | None:
    ext = (format_data.get("ext") or "").lower()
    if mode == "audio":
        if ext == "mp3":
            return "audio/mpeg"
        if ext in {"m4a", "mp4"}:
            return "audio/mp4"
        if ext == "aac":
            return "audio/aac"
        if ext in {"ogg", "opus", "webm"}:
            return "audio/webm" if ext == "webm" else "audio/ogg"
    else:
        if ext == "mp4":
            return "video/mp4"
        if ext == "webm":
            return "video/webm"
        if ext == "mkv":
            return "video/x-matroska"
    return None


def _audio_format_key(format_data: dict[str, Any]) -> tuple[int, int, float, float, int]:
    acodec = (format_data.get("acodec") or "").lower()
    vcodec = (format_data.get("vcodec") or "").lower()
    if not format_data.get("url") or acodec in {"", "none"}:
        return (-1, -1, -1.0, -1.0, -1)

    ext = (format_data.get("audio_ext") or format_data.get("ext") or "").lower()
    protocol = format_data.get("protocol", "")
    audio_only = 1 if vcodec == "none" else 0
    bitrate = _coerce_float(format_data.get("abr")) or _coerce_float(format_data.get("tbr"))
    size_hint = _coerce_float(format_data.get("filesize") or format_data.get("filesize_approx"))
    return (
        audio_only,
        AUDIO_EXT_PREFERENCE.get(ext, 0),
        bitrate,
        size_hint,
        _protocol_score(protocol),
    )


def _video_format_key(format_data: dict[str, Any]) -> tuple[int, int, int, float, int]:
    vcodec = (format_data.get("vcodec") or "").lower()
    if not format_data.get("url") or vcodec in {"", "none"}:
        return (-1, -1, -1, -1.0, -1)

    acodec = (format_data.get("acodec") or "").lower()
    ext = (format_data.get("ext") or "").lower()
    protocol = format_data.get("protocol", "")
    progressive = 1 if acodec not in {"", "none"} else 0
    height = _coerce_int(format_data.get("height"))
    target_height = min(height, 720) if height else 0
    bitrate = _coerce_float(format_data.get("tbr"))
    return (
        progressive,
        VIDEO_EXT_PREFERENCE.get(ext, 0),
        target_height,
        bitrate,
        _protocol_score(protocol),
    )


def _select_format(formats: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    valid_formats = [item for item in formats if isinstance(item, dict)]
    if mode == "audio":
        ranked = sorted(valid_formats, key=_audio_format_key, reverse=True)
    else:
        ranked = sorted(valid_formats, key=_video_format_key, reverse=True)

    for format_data in ranked:
        if format_data.get("url"):
            return format_data
    return {}


def build_youtube_proxy_path(video_id: str, mode: str = "audio") -> str:
    query = urlencode({"video_id": video_id, "mode": mode})
    return f"{YOUTUBE_PROXY_PATH}?{query}"


def build_youtube_proxy_url(video_id: str, mode: str = "audio", base_url: str = LLM_PUBLIC_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}{build_youtube_proxy_path(video_id, mode=mode)}"


def resolve_youtube_stream(
    *,
    video_id: str | None = None,
    url: str | None = None,
    query: str | None = None,
    mode: str = "audio",
) -> dict[str, Any]:
    normalized_mode = (mode or "audio").strip().lower()
    if normalized_mode not in {"audio", "video"}:
        raise ValueError("mode phải là 'audio' hoặc 'video'")

    target = (url or "").strip()
    if not target and video_id:
        target = _watch_url(video_id.strip())
    if not target and query:
        target = f"ytsearch1:{query}"
    if not target:
        raise ValueError("Cần truyền query, video_id hoặc url")

    payload = _run_yt_dlp_json(
        [
            "--dump-single-json",
            "--no-playlist",
            "--no-warnings",
            "--skip-download",
            target,
        ]
    )
    info = _extract_single_video_info(payload)
    if not info:
        raise RuntimeError("Không tìm thấy video YouTube phù hợp")

    selected_format = _select_format(info.get("formats") or [], normalized_mode)
    direct_stream_url = selected_format.get("url") or info.get("url") or ""
    if not direct_stream_url:
        raise RuntimeError("Không lấy được stream URL từ YouTube")

    resolved_video_id = str(info.get("id") or video_id or "")
    ext = (selected_format.get("ext") or "").lower()
    return {
        "source": "youtube_yt_dlp",
        "mode": normalized_mode,
        "video_id": resolved_video_id,
        "title": info.get("title", ""),
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_id": info.get("channel_id") or info.get("uploader_id") or "",
        "duration_seconds": _coerce_int(info.get("duration")),
        "webpage_url": info.get("webpage_url") or (_watch_url(resolved_video_id) if resolved_video_id else ""),
        "thumbnail_url": _pick_thumbnail_url(info),
        "description": (info.get("description") or "")[:1200],
        "is_live": bool(info.get("is_live")),
        "direct_stream_url": direct_stream_url,
        "proxy_path": build_youtube_proxy_path(resolved_video_id, mode=normalized_mode),
        "proxy_url": build_youtube_proxy_url(resolved_video_id, mode=normalized_mode),
        "format_id": selected_format.get("format_id") or "",
        "format_note": selected_format.get("format_note") or selected_format.get("format") or "",
        "ext": ext,
        "container": selected_format.get("container") or ext,
        "protocol": selected_format.get("protocol") or "",
        "content_type_hint": _infer_content_type(selected_format, normalized_mode),
        "audio_codec": selected_format.get("acodec") or "",
        "video_codec": selected_format.get("vcodec") or "",
        "bitrate_kbps": _coerce_int(selected_format.get("abr") or selected_format.get("tbr")),
        "width": _coerce_int(selected_format.get("width")),
        "height": _coerce_int(selected_format.get("height")),
    }

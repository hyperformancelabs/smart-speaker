from __future__ import annotations

from typing import Any

from config import YOUTUBE_SEARCH_MAX_RESULTS
from youtube_stream_tool import resolve_youtube_stream, youtube_search_videos


def _build_youtube_stream_result(
    stream_info: dict[str, Any],
    *,
    query: str | None = None,
    mode: str = "audio",
) -> dict[str, Any]:
    normalized_mode = (mode or "audio").strip().lower()
    stream_type = "audio_stream" if normalized_mode == "audio" else "video_stream"
    title = stream_info.get("title") or query or "YouTube stream"
    stream_url = stream_info.get("proxy_url") or stream_info.get("direct_stream_url")

    device_payload = {
        "type": stream_type,
        "status": "ready",
        "query": query,
        "source": stream_info.get("source", "youtube_yt_dlp"),
        "stream_url": stream_url,
        "proxy_path": stream_info.get("proxy_path"),
        "proxy_url": stream_info.get("proxy_url"),
        "upstream_stream_url": stream_info.get("direct_stream_url"),
        "stream_name": title,
        "video_id": stream_info.get("video_id"),
        "webpage_url": stream_info.get("webpage_url"),
        "thumbnail_url": stream_info.get("thumbnail_url"),
        "duration_seconds": stream_info.get("duration_seconds"),
        "transport": "http_proxy",
        "content_type_hint": stream_info.get("content_type_hint"),
        "container": stream_info.get("container"),
        "audio_codec": stream_info.get("audio_codec"),
        "video_codec": stream_info.get("video_codec"),
        "bitrate_kbps": stream_info.get("bitrate_kbps"),
        "protocol": stream_info.get("protocol"),
        "is_live": stream_info.get("is_live"),
    }

    return {
        "status": "success",
        "message": f"Đang phát {title}",
        "query": query,
        "source": stream_info.get("source", "youtube_yt_dlp"),
        "stream_name": title,
        "stream_url": stream_url,
        "proxy_url": stream_info.get("proxy_url"),
        "proxy_path": stream_info.get("proxy_path"),
        "upstream_stream_url": stream_info.get("direct_stream_url"),
        "video_id": stream_info.get("video_id"),
        "title": title,
        "channel": stream_info.get("channel"),
        "duration_seconds": stream_info.get("duration_seconds"),
        "webpage_url": stream_info.get("webpage_url"),
        "thumbnail_url": stream_info.get("thumbnail_url"),
        "content_type_hint": stream_info.get("content_type_hint"),
        "stream_info": stream_info,
        "device_payload": device_payload,
    }


def youtube_search_with(
    query: str,
    max_results: int = YOUTUBE_SEARCH_MAX_RESULTS,
    *,
    youtube_search_videos_fn,
) -> dict[str, Any]:
    """
    Search YouTube via yt-dlp and return compact video results.
    """
    try:
        data = youtube_search_videos_fn(query=query, max_results=max_results)
        results = data.get("results", [])
        primary_result = results[0] if results else None
        return {
            "status": "success",
            "query": query,
            "source": data.get("source", "youtube_yt_dlp"),
            "results": results,
            "primary_result": primary_result,
            "message": f"Tìm thấy {len(results)} video YouTube",
            "device_payload": {
                "type": "youtube_search_results",
                "status": "ok" if results else "empty",
                "query": query,
                "source": data.get("source", "youtube_yt_dlp"),
                "results": results,
                "top_result": primary_result,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"YouTube search error: {str(exc)}",
        }


def youtube_search(query: str, max_results: int = YOUTUBE_SEARCH_MAX_RESULTS) -> dict[str, Any]:
    return youtube_search_with(
        query=query,
        max_results=max_results,
        youtube_search_videos_fn=youtube_search_videos,
    )


def youtube_stream_with(
    query: str | None = None,
    video_id: str | None = None,
    url: str | None = None,
    mode: str = "audio",
    *,
    resolve_youtube_stream_fn,
) -> dict[str, Any]:
    """
    Resolve a YouTube audio/video stream via yt-dlp without downloading to disk.
    """
    try:
        stream_info = resolve_youtube_stream_fn(
            query=query,
            video_id=video_id,
            url=url,
            mode=mode,
        )
        result = _build_youtube_stream_result(stream_info, query=query, mode=mode)
        return result
    except Exception as exc:
        return {
            "status": "error",
            "message": f"YouTube stream error: {str(exc)}",
        }


def youtube_stream(
    query: str | None = None,
    video_id: str | None = None,
    url: str | None = None,
    mode: str = "audio",
) -> dict[str, Any]:
    return youtube_stream_with(
        query=query,
        video_id=video_id,
        url=url,
        mode=mode,
        resolve_youtube_stream_fn=resolve_youtube_stream,
    )


def play_audio_with(
    query: str,
    user_id: str = None,
    *,
    youtube_stream_fn,
) -> dict[str, Any]:
    """
    Resolve audio playback through YouTube search and return a stream URL.
    """
    try:
        youtube_result = youtube_stream_fn(query=query, mode="audio")
        if youtube_result.get("status") == "success":
            return youtube_result

        return {
            "status": "error",
            "message": (
                f"Không thể lấy YouTube audio stream cho '{query}'"
                + (
                    f": {youtube_result.get('message')}"
                    if youtube_result.get("message")
                    else ""
                )
            ),
            "query": query,
            "source": "youtube_yt_dlp",
            "device_payload": {
                "type": "audio_stream",
                "query": query,
                "status": "not_found",
                "source": "youtube_yt_dlp",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Audio stream error: {str(exc)}",
        }


def play_audio(query: str, user_id: str = None) -> dict[str, Any]:
    return play_audio_with(
        query=query,
        user_id=user_id,
        youtube_stream_fn=youtube_stream,
    )

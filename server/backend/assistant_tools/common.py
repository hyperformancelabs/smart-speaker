from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import requests

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8386")
BACKEND_TIMEOUT_SECONDS = 5


def _extract_backend_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    reason = str(getattr(response, "reason", "") or "").strip()
    if reason:
        return reason
    return f"Database API request failed with status {response.status_code}"


def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


def build_llm_documents(content_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    documents = []
    for item in content_items:
        if item.get("status") != "success":
            continue
        documents.append(
            {
                "title": item.get("title", ""),
                "url": item.get("final_url") or item.get("resolved_url") or item.get("requested_url", ""),
                "domain": item.get("domain", ""),
                "content": item.get("focused_content") or item.get("content", ""),
                "excerpt": item.get("focused_excerpt") or item.get("excerpt", ""),
            }
        )
    return documents


def backend_request(
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    timeout: int = BACKEND_TIMEOUT_SECONDS,
) -> requests.Response:
    response = requests.request(
        method=method,
        url=f"{BACKEND_API_URL}{path}",
        json=json_payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_backend_error_message(response))
    return response


def backend_json(
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    timeout: int = BACKEND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return backend_request(
        method=method,
        path=path,
        json_payload=json_payload,
        timeout=timeout,
    ).json()


def parse_json_string_if_possible(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value

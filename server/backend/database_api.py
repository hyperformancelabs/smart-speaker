from __future__ import annotations

from typing import Any

import requests

from config import BACKEND_API_URL


def get_user_by_nfc_tag(nfc_tag_id: str, timeout: int = 5) -> dict[str, Any] | None:
    normalized_nfc_tag_id = str(nfc_tag_id or "").strip()
    if not normalized_nfc_tag_id:
        return None

    try:
        response = requests.get(
            f"{BACKEND_API_URL}/api/users/{normalized_nfc_tag_id}",
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except requests.RequestException:
        return None

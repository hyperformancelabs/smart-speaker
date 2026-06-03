from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import uuid
from typing import Any

from config import MEDIA_STORAGE_DIR, TTS_STORAGE_DIR, VOICE_BACKEND_PUBLIC_BASE_URL


@dataclass(slots=True)
class AssetRecord:
    asset_id: str
    kind: str
    created_at: str
    file_path: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "file_path": self.file_path,
            "source_url": self.source_url,
            "metadata": dict(self.metadata),
        }


class AssetRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, AssetRecord] = {}
        TTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        MEDIA_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _store(self, record: AssetRecord) -> AssetRecord:
        with self._lock:
            self._records[record.asset_id] = record
        return record

    def register_tts_file(self, file_path: Path, *, metadata: dict[str, Any] | None = None) -> AssetRecord:
        return self._store(
            AssetRecord(
                asset_id=self._next_id("tts"),
                kind="tts",
                created_at=datetime.now(timezone.utc).isoformat(),
                file_path=str(file_path),
                metadata=dict(metadata or {}),
            )
        )

    def register_media_source(
        self,
        source_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AssetRecord:
        return self._store(
            AssetRecord(
                asset_id=self._next_id("media"),
                kind="media",
                created_at=datetime.now(timezone.utc).isoformat(),
                source_url=str(source_url or "").strip(),
                metadata=dict(metadata or {}),
            )
        )

    def get(self, asset_id: str) -> AssetRecord | None:
        with self._lock:
            return self._records.get(asset_id)

    def build_tts_url(self, asset_id: str, *, base_url: str | None = None) -> str:
        resolved_base_url = str(base_url or VOICE_BACKEND_PUBLIC_BASE_URL).rstrip("/")
        return f"{resolved_base_url}/api/assets/tts/{asset_id}.wav"

    def build_media_url(self, asset_id: str, *, base_url: str | None = None) -> str:
        resolved_base_url = str(base_url or VOICE_BACKEND_PUBLIC_BASE_URL).rstrip("/")
        return f"{resolved_base_url}/api/assets/media/{asset_id}.wav"


asset_registry = AssetRegistry()

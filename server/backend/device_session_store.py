from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time
from typing import Any

from config import DEVICE_SESSION_TTL_SECONDS


@dataclass(slots=True)
class DeviceSession:
    session_state: dict[str, Any]
    updated_at: float


class DeviceSessionStore:
    def __init__(self, ttl_seconds: int = DEVICE_SESSION_TTL_SECONDS) -> None:
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._lock = Lock()
        self._sessions: dict[str, DeviceSession] = {}

    def _cleanup_expired_locked(self, now: float) -> None:
        expired_keys = [
            key
            for key, session in self._sessions.items()
            if now - session.updated_at > self._ttl_seconds
        ]
        for key in expired_keys:
            self._sessions.pop(key, None)

    def get(self, session_key: str | None) -> dict[str, Any] | None:
        if not session_key:
            return None

        now = time.time()
        with self._lock:
            self._cleanup_expired_locked(now)
            session = self._sessions.get(session_key)
            if session is None:
                return None
            session.updated_at = now
            return dict(session.session_state)

    def set(self, session_key: str | None, session_state: dict[str, Any] | None) -> None:
        if not session_key or not isinstance(session_state, dict):
            return

        now = time.time()
        with self._lock:
            self._cleanup_expired_locked(now)
            self._sessions[session_key] = DeviceSession(
                session_state=dict(session_state),
                updated_at=now,
            )

    def clear(self, session_key: str | None) -> None:
        if not session_key:
            return
        with self._lock:
            self._sessions.pop(session_key, None)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._cleanup_expired_locked(now)
            return {
                key: {
                    "updated_at": session.updated_at,
                    "session_state": dict(session.session_state),
                }
                for key, session in self._sessions.items()
            }

    def dump(self) -> dict[str, Any]:
        # Backward-compatible alias for debug routes that still call dump().
        return self.snapshot()


device_session_store = DeviceSessionStore()

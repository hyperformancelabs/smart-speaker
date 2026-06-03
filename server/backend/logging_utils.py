from __future__ import annotations

import logging
from logging import Logger
from pathlib import Path
from urllib.parse import urlparse


def configure_logging(*, level: str, log_file: str | Path | None = None) -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_smart_speaker_logging_configured", False):
        return

    resolved_level = getattr(logging, str(level or "INFO").upper(), logging.INFO)
    root_logger.setLevel(resolved_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(resolved_level)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(resolved_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    setattr(root_logger, "_smart_speaker_logging_configured", True)


def get_logger(name: str) -> Logger:
    return logging.getLogger(name)


def log_kv(logger: Logger, level: int, event: str, **fields: object) -> None:
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value!r}")
    logger.log(level, " | ".join(parts))


def is_loopback_base_url(url: str | None) -> bool:
    normalized = str(url or "").strip()
    if not normalized:
        return False

    host = (urlparse(normalized).hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"}

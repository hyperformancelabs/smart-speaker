#!/usr/bin/env python3
"""Receive ESP32 websocket audio frames and save them as WAV files.

The firmware in `src/main.cpp` exposes a websocket server and sends binary
frames with this layout:

- 4 bytes: little-endian packet sequence number
- N bytes: signed 16-bit PCM samples, mono, 16 kHz

This script connects as a websocket client, validates the packet framing, and
writes the PCM stream into either:

- one continuous WAV file, or
- rolling N-second WAV segments

The WAV header is refreshed after each write so the file stays readable if the
stream ends unexpectedly.
"""

from __future__ import annotations

import argparse
import signal
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import websocket


DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_SAMPLE_WIDTH = 2
DEFAULT_CHANNELS = 1
DEFAULT_PORT = 81
DEFAULT_TIMEOUT_SECONDS = 1.0
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "recordings"


@dataclass(slots=True)
class AudioFormat:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    sample_width: int = DEFAULT_SAMPLE_WIDTH
    channels: int = DEFAULT_CHANNELS

    @property
    def block_align(self) -> int:
        return self.sample_width * self.channels

    @property
    def byte_rate(self) -> int:
        return self.sample_rate * self.block_align


class StreamingWavWriter:
    """Append PCM audio while keeping the WAV header up to date."""

    def __init__(self, path: Path, audio_format: AudioFormat) -> None:
        self.path = path
        self.audio_format = audio_format
        self._data_bytes = 0
        self._file = path.open("w+b")
        self._write_header()

    def _write_header(self) -> None:
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + self._data_bytes,
            b"WAVE",
            b"fmt ",
            16,
            1,
            self.audio_format.channels,
            self.audio_format.sample_rate,
            self.audio_format.byte_rate,
            self.audio_format.block_align,
            self.audio_format.sample_width * 8,
            b"data",
            self._data_bytes,
        )
        self._file.seek(0)
        self._file.write(header)
        self._file.flush()

    def _sync_sizes(self) -> None:
        if self._data_bytes > 0xFFFFFFFF - 36:
            raise OverflowError(
                f"WAV file {self.path} exceeded the 4 GiB RIFF limit. "
                "Use --segment-seconds to rotate files."
            )

        current_pos = self._file.tell()
        self._file.seek(4)
        self._file.write(struct.pack("<I", 36 + self._data_bytes))
        self._file.seek(40)
        self._file.write(struct.pack("<I", self._data_bytes))
        self._file.seek(current_pos)
        self._file.flush()

    def write(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        if len(pcm_bytes) % self.audio_format.block_align:
            raise ValueError(
                f"PCM payload length {len(pcm_bytes)} is not aligned to "
                f"{self.audio_format.block_align}-byte frames."
            )

        self._file.seek(0, 2)
        self._file.write(pcm_bytes)
        self._data_bytes += len(pcm_bytes)
        self._sync_sizes()

    def close(self) -> None:
        if self._file.closed:
            return
        self._sync_sizes()
        self._file.close()


class WavSegmentSink:
    """Write audio into one continuous WAV or rotate fixed-length segments."""

    def __init__(
        self,
        output_dir: Path,
        prefix: str,
        audio_format: AudioFormat,
        segment_seconds: float | None,
    ) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.audio_format = audio_format
        self.segment_frames = self._get_segment_frames(segment_seconds, audio_format)
        self.session_tag = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.segment_index = 0
        self.current_frames = 0
        self.total_frames = 0
        self.writer: StreamingWavWriter | None = None

    @staticmethod
    def _get_segment_frames(
        segment_seconds: float | None, audio_format: AudioFormat
    ) -> int | None:
        if segment_seconds is None:
            return None
        if segment_seconds <= 0:
            raise ValueError("--segment-seconds must be greater than zero.")

        frames = round(segment_seconds * audio_format.sample_rate)
        if frames <= 0:
            raise ValueError("--segment-seconds is too small for the sample rate.")
        return frames

    def _next_path(self) -> Path:
        if self.segment_frames is None:
            filename = f"{self.prefix}_{self.session_tag}.wav"
        else:
            self.segment_index += 1
            filename = f"{self.prefix}_{self.session_tag}_part{self.segment_index:04d}.wav"
        return self.output_dir / filename

    def _open_writer(self) -> None:
        if self.writer is not None:
            return
        path = self._next_path()
        self.writer = StreamingWavWriter(path, self.audio_format)
        self.current_frames = 0
        print(f"writing {path}", flush=True)

    def _close_writer(self) -> None:
        if self.writer is None:
            return
        self.writer.close()
        self.writer = None
        self.current_frames = 0

    def write(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return

        block_align = self.audio_format.block_align
        if len(pcm_bytes) % block_align:
            raise ValueError(
                f"PCM payload length {len(pcm_bytes)} is not aligned to {block_align} bytes."
            )

        remaining = memoryview(pcm_bytes)
        while remaining:
            self._open_writer()

            if self.segment_frames is None:
                chunk = remaining.tobytes()
                self.writer.write(chunk)
                frames = len(chunk) // block_align
                self.current_frames += frames
                self.total_frames += frames
                break

            frames_left = self.segment_frames - self.current_frames
            if frames_left <= 0:
                self._close_writer()
                continue

            chunk_bytes = min(len(remaining), frames_left * block_align)
            chunk = remaining[:chunk_bytes].tobytes()
            self.writer.write(chunk)

            frames = chunk_bytes // block_align
            self.current_frames += frames
            self.total_frames += frames
            remaining = remaining[chunk_bytes:]

            if self.current_frames >= self.segment_frames:
                self._close_writer()

    def close(self) -> None:
        self._close_writer()


def parse_audio_packet(packet: bytes, audio_format: AudioFormat) -> tuple[int, bytes]:
    if len(packet) < 4:
        raise ValueError("binary frame shorter than 4-byte sequence header")

    seq = int.from_bytes(packet[:4], "little", signed=False)
    pcm_bytes = packet[4:]
    if len(pcm_bytes) % audio_format.block_align:
        raise ValueError(
            f"payload size {len(pcm_bytes)} is not aligned to "
            f"{audio_format.block_align}-byte PCM frames"
        )

    return seq, pcm_bytes


def install_signal_handlers(stop: Callable[[], None]) -> None:
    def _handle_signal(signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        print(f"received {signal_name}, closing stream", flush=True)
        stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)


def receive_stream(
    url: str,
    output_dir: Path,
    prefix: str,
    audio_format: AudioFormat,
    segment_seconds: float | None,
    timeout_seconds: float,
    retry_seconds: float | None,
) -> int:
    stop_requested = False

    def request_stop() -> None:
        nonlocal stop_requested
        stop_requested = True

    install_signal_handlers(request_stop)

    while True:
        sink = WavSegmentSink(output_dir, prefix, audio_format, segment_seconds)
        last_seq: int | None = None
        packet_count = 0
        ws: websocket.WebSocket | None = None

        try:
            print(f"connecting to {url}", flush=True)
            ws = websocket.create_connection(url, timeout=timeout_seconds)
            ws.settimeout(timeout_seconds)
            print("connected", flush=True)

            while not stop_requested:
                try:
                    message = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                if isinstance(message, str):
                    print(f"text frame: {message}", flush=True)
                    continue

                seq, pcm_bytes = parse_audio_packet(bytes(message), audio_format)

                if last_seq is not None:
                    expected = (last_seq + 1) & 0xFFFFFFFF
                    if seq != expected:
                        print(
                            f"sequence gap: expected {expected}, got {seq}",
                            file=sys.stderr,
                            flush=True,
                        )
                last_seq = seq

                sink.write(pcm_bytes)
                packet_count += 1

        except KeyboardInterrupt:
            request_stop()
        except websocket.WebSocketBadStatusException as exc:
            print(f"websocket handshake failed: {exc}", file=sys.stderr, flush=True)
            return 2
        except websocket.WebSocketConnectionClosedException:
            print("stream ended: peer closed the websocket", flush=True)
        except (OSError, ValueError, OverflowError, websocket.WebSocketException) as exc:
            print(f"stream stopped: {exc}", file=sys.stderr, flush=True)
            if retry_seconds is None and not stop_requested:
                return 1
        finally:
            if ws is not None:
                try:
                    ws.close()
                except websocket.WebSocketException:
                    pass
            sink.close()
            if packet_count:
                seconds = sink.total_frames / audio_format.sample_rate
                print(
                    f"saved {sink.total_frames} samples ({seconds:.2f}s)",
                    flush=True,
                )

        if stop_requested:
            return 0

        if retry_seconds is None:
            return 0

        print(f"reconnecting in {retry_seconds:.1f}s", flush=True)
        time.sleep(retry_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Connect to the ESP32 websocket audio stream and save the incoming "
            "PCM as WAV."
        )
    )
    parser.add_argument("--host", required=True, help="ESP32 hostname or IP address.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Websocket port on the ESP32 (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--path",
        default="/",
        help="Websocket path on the ESP32 (default: /).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for recorded WAV files (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--prefix",
        default="capture",
        help="Filename prefix for saved WAV files.",
    )
    parser.add_argument(
        "--segment-seconds",
        type=float,
        default=None,
        help=(
            "Rotate files every N seconds. Omit this flag to keep writing into "
            "one continuous WAV file until EOF/disconnect."
        ),
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help=f"PCM sample rate in Hz (default: {DEFAULT_SAMPLE_RATE}).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Socket timeout used while waiting for audio packets "
            f"(default: {DEFAULT_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--retry-seconds",
        type=float,
        default=None,
        help="Reconnect delay after disconnect. Omit to stop after EOF/disconnect.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = args.path if args.path.startswith("/") else f"/{args.path}"
    url = f"ws://{args.host}:{args.port}{path}"
    audio_format = AudioFormat(sample_rate=args.sample_rate)

    return receive_stream(
        url=url,
        output_dir=args.output_dir,
        prefix=args.prefix,
        audio_format=audio_format,
        segment_seconds=args.segment_seconds,
        timeout_seconds=args.timeout_seconds,
        retry_seconds=args.retry_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())

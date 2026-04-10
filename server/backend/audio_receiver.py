from __future__ import annotations

import argparse
import signal
import struct
import sys
import threading
import time
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import websocket

try:
    from .session_control import (
        AudioSessionDirective,
        DeviceAudioSessionState,
        build_audio_session_state_message,
        default_stop_after_first_utterance,
    )
    from .silero_vad_segmenter import FirstUtteranceDetector, SileroVadConfig, SpeechSegment
except ImportError:
    from session_control import (
        AudioSessionDirective,
        DeviceAudioSessionState,
        build_audio_session_state_message,
        default_stop_after_first_utterance,
    )
    from silero_vad_segmenter import FirstUtteranceDetector, SileroVadConfig, SpeechSegment


DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_SAMPLE_WIDTH = 2
DEFAULT_CHANNELS = 1
DEFAULT_PORT = 81
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_RETRY_SECONDS = 1.0
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "recordings"
DEFAULT_WS_PATH = "/"
DEFAULT_CONTROL_SIGNAL_SETTLE_SECONDS = 0.05


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
        self.last_path: Path | None = None

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
        self.last_path = path
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


def write_pcm_wav(path: Path, audio_format: AudioFormat, pcm_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(audio_format.channels)
        wav_file.setsampwidth(audio_format.sample_width)
        wav_file.setframerate(audio_format.sample_rate)
        wav_file.writeframes(pcm_bytes)


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


@dataclass(slots=True)
class CaptureRequest:
    ws_host: str
    ws_port: int = DEFAULT_PORT
    ws_path: str = DEFAULT_WS_PATH
    prefix: str = "capture"
    sample_rate: int = DEFAULT_SAMPLE_RATE
    output_dir: Path = DEFAULT_OUTPUT_DIR
    segment_seconds: float | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retry_seconds: float | None = DEFAULT_RETRY_SECONDS
    enable_first_utterance_vad: bool = True
    first_utterance_state: DeviceAudioSessionState = DeviceAudioSessionState.WAIT_WAKEWORD
    stop_after_first_utterance: bool | None = None

    def websocket_url(self) -> str:
        path = self.ws_path if self.ws_path.startswith("/") else f"/{self.ws_path}"
        return f"ws://{self.ws_host}:{self.ws_port}{path}"

    def resolved_stop_after_first_utterance(self) -> bool:
        if self.stop_after_first_utterance is not None:
            return self.stop_after_first_utterance
        return default_stop_after_first_utterance(self.first_utterance_state)


@dataclass(slots=True)
class CaptureStatus:
    session_id: str
    state: str = "idle"
    ws_url: str = ""
    started_at: str | None = None
    stopped_at: str | None = None
    packet_count: int = 0
    total_frames: int = 0
    last_sequence: int | None = None
    output_dir: str = ""
    last_file_path: str | None = None
    first_utterance_path: str | None = None
    first_utterance_duration_seconds: float | None = None
    first_utterance_completed_at: str | None = None
    first_utterance_completion_reason: str | None = None
    device_state_signal: str | None = None
    device_state_signal_reason: str | None = None
    device_state_signal_sent_at: str | None = None
    device_state_signal_error: str | None = None
    error: str | None = None


class FirstUtteranceProcessingError(RuntimeError):
    pass


class CaptureSession:
    def __init__(self, request: CaptureRequest) -> None:
        self.request = request
        self.audio_format = AudioFormat(sample_rate=request.sample_rate)
        self.stop_event = threading.Event()
        self.first_utterance_config = (
            SileroVadConfig(sample_rate=request.sample_rate)
            if request.enable_first_utterance_vad
            else None
        )
        self.first_utterance_detector: FirstUtteranceDetector | None = None
        self.status = CaptureStatus(
            session_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
            state="starting",
            ws_url=request.websocket_url(),
            started_at=datetime.now(timezone.utc).isoformat(),
            output_dir=str(request.output_dir),
        )
        self._thread = threading.Thread(target=self._run, name="audio-capture", daemon=True)
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return asdict(self.status)

    def _update_status(self, **changes: object) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self.status, key, value)

    def _save_first_utterance(self, segment: SpeechSegment) -> Path:
        path = self.request.output_dir / "utterances" / (
            f"{self.request.prefix}_{self.status.session_id}_first_utterance.wav"
        )
        write_pcm_wav(path, self.audio_format, segment.pcm_bytes)
        return path

    def _handle_first_utterance(self, ws: websocket.WebSocket, segment: SpeechSegment) -> bool:
        detected_at = datetime.now(timezone.utc).isoformat()

        try:
            utterance_path = self._save_first_utterance(segment)
        except OSError as exc:
            raise FirstUtteranceProcessingError(
                f"failed to persist first utterance audio: {exc}"
            ) from exc

        directive = AudioSessionDirective(
            state=self.request.first_utterance_state,
            reason="first_utterance_detected",
            stop_capture=self.request.resolved_stop_after_first_utterance(),
        )
        self._update_status(
            first_utterance_path=str(utterance_path),
            first_utterance_duration_seconds=round(segment.duration_seconds, 3),
            first_utterance_completed_at=detected_at,
            first_utterance_completion_reason=segment.completion_reason,
            device_state_signal=directive.state.value,
            device_state_signal_reason=directive.reason,
            device_state_signal_error=None,
        )

        try:
            ws.send(build_audio_session_state_message(directive))
        except websocket.WebSocketException as exc:
            self._update_status(device_state_signal_error=str(exc))
            raise FirstUtteranceProcessingError(
                f"failed to send device state '{directive.state.value}' over websocket: {exc}"
            ) from exc

        self._update_status(device_state_signal_sent_at=datetime.now(timezone.utc).isoformat())
        time.sleep(DEFAULT_CONTROL_SIGNAL_SETTLE_SECONDS)

        if directive.stop_capture:
            self._update_status(state="completed")

        return directive.stop_capture

    def _run(self) -> None:
        while True:
            sink = WavSegmentSink(
                output_dir=self.request.output_dir,
                prefix=self.request.prefix,
                audio_format=self.audio_format,
                segment_seconds=self.request.segment_seconds,
            )
            last_seq: int | None = None
            ws: websocket.WebSocket | None = None
            self.first_utterance_detector = (
                FirstUtteranceDetector(self.first_utterance_config)
                if self.first_utterance_config is not None
                else None
            )

            try:
                print(f"connecting to {self.request.websocket_url()}", flush=True)
                self._update_status(state="connecting", error=None)
                ws = websocket.create_connection(
                    self.request.websocket_url(),
                    timeout=self.request.timeout_seconds,
                )
                ws.settimeout(self.request.timeout_seconds)
                print(f"websocket connected {self.request.websocket_url()}", flush=True)
                self._update_status(state="running")

                while not self.stop_event.is_set():
                    try:
                        message = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue

                    if isinstance(message, str):
                        continue

                    seq, pcm_bytes = parse_audio_packet(bytes(message), self.audio_format)
                    last_seq = seq
                    sink.write(pcm_bytes)

                    self._update_status(
                        packet_count=self.status.packet_count + 1,
                        total_frames=sink.total_frames,
                        last_sequence=last_seq,
                        last_file_path=str(sink.last_path) if sink.last_path else None,
                    )

                    if self.first_utterance_detector is None:
                        continue

                    segment = self.first_utterance_detector.process_pcm_bytes(pcm_bytes)
                    if segment is None:
                        continue

                    if self._handle_first_utterance(ws, segment):
                        break

            except FirstUtteranceProcessingError as exc:
                print(f"first utterance processing error {self.request.websocket_url()}: {exc}", flush=True)
                self._update_status(state="error", error=str(exc))
                break
            except websocket.WebSocketBadStatusException as exc:
                print(f"websocket handshake failed {self.request.websocket_url()}: {exc}", flush=True)
                self._update_status(state="error", error=f"websocket handshake failed: {exc}")
                break
            except websocket.WebSocketConnectionClosedException:
                if self.stop_event.is_set():
                    self._update_status(state="stopped")
                    break
                if self.request.retry_seconds is None:
                    self._update_status(state="stopped", error="stream ended: peer closed the websocket")
                    break
                print("websocket peer closed connection, retrying", flush=True)
            except (OSError, ValueError, OverflowError, websocket.WebSocketException) as exc:
                print(f"websocket capture error {self.request.websocket_url()}: {exc}", flush=True)
                self._update_status(state="error", error=str(exc))
                if self.request.retry_seconds is None or self.stop_event.is_set():
                    break
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except websocket.WebSocketException:
                        pass
                sink.close()
                self._update_status(
                    total_frames=sink.total_frames,
                    last_file_path=str(sink.last_path) if sink.last_path else self.status.last_file_path,
                )

            if self.snapshot()["state"] == "completed":
                break

            if self.stop_event.is_set():
                self._update_status(state="stopped")
                break

            if self.request.retry_seconds is None:
                break

            self._update_status(state="retrying")
            time.sleep(self.request.retry_seconds)

        self._update_status(stopped_at=datetime.now(timezone.utc).isoformat())


class CaptureManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: CaptureSession | None = None

    def start(self, request: CaptureRequest) -> dict[str, object]:
        with self._lock:
            if self._current is not None:
                self._current.stop()

            session = CaptureSession(request)
            self._current = session
            session.start()
            return session.snapshot()

    def stop(self) -> dict[str, object]:
        with self._lock:
            if self._current is None:
                return {"state": "idle"}

            self._current.stop()
            return self._current.snapshot()

    def status(self) -> dict[str, object]:
        with self._lock:
            if self._current is None:
                return {"state": "idle"}
            return self._current.snapshot()


capture_manager = CaptureManager()


def install_signal_handlers(stop: Callable[[], None]) -> None:
    def _handle_signal(signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        print(f"received {signal_name}, closing stream", flush=True)
        stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)


def receive_stream(
    request: CaptureRequest,
) -> int:
    stop_requested = False

    def request_stop() -> None:
        nonlocal stop_requested
        stop_requested = True

    install_signal_handlers(request_stop)
    session = CaptureSession(request)
    session.start()

    while not stop_requested:
        snapshot = session.snapshot()
        if snapshot["state"] in {"stopped", "completed", "error"}:
            break
        time.sleep(0.2)

    session.stop()
    final_status = session.snapshot()
    if final_status["state"] == "error":
        print(final_status.get("error") or "capture failed", file=sys.stderr, flush=True)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connect to the ESP32 websocket audio stream and save the incoming PCM as WAV."
    )
    parser.add_argument("--host", required=True, help="ESP32 hostname or IP address.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Websocket port on the ESP32.")
    parser.add_argument("--path", default=DEFAULT_WS_PATH, help="Websocket path on the ESP32.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for recorded WAV files.")
    parser.add_argument("--prefix", default="capture", help="Filename prefix for saved WAV files.")
    parser.add_argument("--segment-seconds", type=float, default=None, help="Rotate files every N seconds.")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE, help="PCM sample rate in Hz.")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Socket timeout while waiting for packets.")
    parser.add_argument("--retry-seconds", type=float, default=DEFAULT_RETRY_SECONDS, help="Reconnect delay after disconnect.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    request = CaptureRequest(
        ws_host=args.host,
        ws_port=args.port,
        ws_path=args.path,
        output_dir=args.output_dir,
        prefix=args.prefix,
        sample_rate=args.sample_rate,
        segment_seconds=args.segment_seconds,
        timeout_seconds=args.timeout_seconds,
        retry_seconds=args.retry_seconds,
    )
    return receive_stream(request)


if __name__ == "__main__":
    raise SystemExit(main())

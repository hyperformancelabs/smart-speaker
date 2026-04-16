from __future__ import annotations

import sys
import threading
import time
from array import array
from collections import deque
from dataclasses import dataclass

import torch
from silero_vad import load_silero_vad


_MODEL_LOCK = threading.Lock()
_SILERO_VAD_MODEL = None
_TORCH_THREADS_CONFIGURED = False


def get_silero_vad_model():
    global _SILERO_VAD_MODEL, _TORCH_THREADS_CONFIGURED
    with _MODEL_LOCK:
        if not _TORCH_THREADS_CONFIGURED:
            torch.set_num_threads(1)
            _TORCH_THREADS_CONFIGURED = True
        if _SILERO_VAD_MODEL is None:
            _SILERO_VAD_MODEL = load_silero_vad()
        return _SILERO_VAD_MODEL


@dataclass(slots=True)
class SileroVadConfig:
    sample_rate: int = 16_000
    sample_width: int = 2
    model_window_samples: int = 512
    vad_threshold: float = 0.50
    start_voiced_blocks: int = 2
    short_pause_ms: int = 224
    final_pause_ms: int = 640
    min_speech_ms: int = 300
    max_utterance_ms: int = 10_000
    preroll_ms: int = 1000

    def validate(self) -> None:
        if self.sample_rate not in {8_000, 16_000}:
            raise ValueError("Silero VAD streaming mode only supports 8000 Hz and 16000 Hz audio.")

    @property
    def model_window_bytes(self) -> int:
        return self.model_window_samples * self.sample_width

    @property
    def block_ms(self) -> int:
        return int(self.model_window_samples / self.sample_rate * 1000)

    @property
    def preroll_blocks(self) -> int:
        return max(1, self.preroll_ms // self.block_ms)

    @property
    def min_speech_blocks(self) -> int:
        return max(1, self.min_speech_ms // self.block_ms)

    @property
    def final_pause_blocks(self) -> int:
        return max(1, self.final_pause_ms // self.block_ms)

    @property
    def max_utterance_blocks(self) -> int:
        return max(1, self.max_utterance_ms // self.block_ms)


@dataclass(slots=True)
class SpeechSegment:
    pcm_bytes: bytes
    duration_seconds: float
    block_count: int
    speech_block_count: int
    completion_reason: str


class FirstUtteranceDetector:
    def __init__(self, config: SileroVadConfig) -> None:
        self.config = config
        self.config.validate()
        self.model = get_silero_vad_model()
        self._sample_buffer = bytearray()
        self._completed = False
        self.started_monotonic = time.monotonic()
        self.last_speech_activity_monotonic = self.started_monotonic
        self.last_audio_monotonic = self.started_monotonic
        self._reset_detection_state()

    def process_pcm_bytes(self, pcm_bytes: bytes) -> SpeechSegment | None:
        if self._completed or not pcm_bytes:
            return None

        if len(pcm_bytes) % self.config.sample_width:
            raise ValueError("incoming PCM buffer is not aligned to 16-bit samples")

        self.last_audio_monotonic = time.monotonic()
        self._sample_buffer.extend(pcm_bytes)

        while len(self._sample_buffer) >= self.config.model_window_bytes:
            block_bytes = bytes(self._sample_buffer[: self.config.model_window_bytes])
            del self._sample_buffer[: self.config.model_window_bytes]
            segment = self._process_block(block_bytes)
            if segment is not None:
                self._completed = True
                return segment

        return None

    def _process_block(self, block_bytes: bytes) -> SpeechSegment | None:
        self.preroll.append(block_bytes)

        speech_prob = float(self.model(self._build_tensor(block_bytes), self.config.sample_rate).item())
        is_speech = speech_prob >= self.config.vad_threshold
        if is_speech:
            self.last_speech_activity_monotonic = time.monotonic()

        if self.state == "WAIT_FOR_SPEECH":
            self.speech_run = self.speech_run + 1 if is_speech else 0

            if self.speech_run >= self.config.start_voiced_blocks:
                self.state = "IN_SPEECH"
                self.silence_run = 0
                self.speech_blocks = self.speech_run
                self.utterance = list(self.preroll)
                self.utterance_blocks = len(self.utterance)
            return None

        self.utterance.append(block_bytes)
        self.utterance_blocks += 1

        if is_speech:
            self.state = "IN_SPEECH"
            self.silence_run = 0
            self.speech_blocks += 1
        else:
            self.silence_run += 1
            if self.silence_run * self.config.block_ms >= self.config.short_pause_ms:
                self.state = "IN_PAUSE_HOLD"

        if self.utterance_blocks >= self.config.max_utterance_blocks:
            return self._finalize_if_valid("max_utterance")

        if self.silence_run >= self.config.final_pause_blocks:
            return self._finalize_if_valid("end_of_speech")

        return None

    def _finalize_if_valid(self, completion_reason: str) -> SpeechSegment | None:
        if self.speech_blocks < self.config.min_speech_blocks:
            self._reset_detection_state()
            return None

        pcm_bytes = b"".join(self.utterance)
        duration_seconds = len(pcm_bytes) / (
            self.config.sample_rate * self.config.sample_width
        )
        segment = SpeechSegment(
            pcm_bytes=pcm_bytes,
            duration_seconds=duration_seconds,
            block_count=self.utterance_blocks,
            speech_block_count=self.speech_blocks,
            completion_reason=completion_reason,
        )
        self._reset_detection_state()
        return segment

    def _build_tensor(self, block_bytes: bytes) -> torch.Tensor:
        block = array("h")
        block.frombytes(block_bytes)
        if sys.byteorder != "little":
            block.byteswap()

        return torch.tensor(list(block), dtype=torch.float32) / 32768.0

    def _reset_detection_state(self) -> None:
        self.state = "WAIT_FOR_SPEECH"
        self.speech_run = 0
        self.silence_run = 0
        self.speech_blocks = 0
        self.utterance_blocks = 0
        self.utterance: list[bytes] = []
        self.preroll: deque[bytes] = deque(maxlen=self.config.preroll_blocks)

    def idle_timeout_reached(self, timeout_seconds: float | None) -> bool:
        if timeout_seconds is None or timeout_seconds <= 0:
            return False
        return (time.monotonic() - self.last_speech_activity_monotonic) >= timeout_seconds

    def has_pending_utterance(self) -> bool:
        return self.state != "WAIT_FOR_SPEECH" and self.utterance_blocks > 0

    def finalize_pending_if_idle(
        self,
        idle_seconds: float | None,
        completion_reason: str = "input_idle",
    ) -> SpeechSegment | None:
        if (
            idle_seconds is None
            or idle_seconds <= 0
            or not self.has_pending_utterance()
            or (time.monotonic() - self.last_audio_monotonic) < idle_seconds
        ):
            return None
        return self._finalize_if_valid(completion_reason)

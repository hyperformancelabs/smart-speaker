from __future__ import annotations

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import torch


SERVER_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_BACKEND_ROOT))

import silero_vad_segmenter


class _FakeModel:
    def __init__(self, probs: list[float]) -> None:
        self._probs = iter(probs)

    def __call__(self, _tensor: torch.Tensor, _sample_rate: int) -> torch.Tensor:
        return torch.tensor(next(self._probs), dtype=torch.float32)


class SileroVadSegmenterTests(unittest.TestCase):
    def test_finalize_pending_if_idle_flushes_valid_utterance(self) -> None:
        config = silero_vad_segmenter.SileroVadConfig(sample_rate=16_000)
        speech_blocks = max(config.min_speech_blocks + 1, config.start_voiced_blocks + 1)
        fake_model = _FakeModel([0.95] * speech_blocks)

        with patch.object(silero_vad_segmenter, "get_silero_vad_model", return_value=fake_model):
            detector = silero_vad_segmenter.FirstUtteranceDetector(config)

        block = b"\x00\x00" * config.model_window_samples
        for _ in range(speech_blocks):
            detector.process_pcm_bytes(block)

        self.assertTrue(detector.has_pending_utterance())

        detector.last_audio_monotonic = time.monotonic() - 2.0
        segment = detector.finalize_pending_if_idle(1.0)

        self.assertIsNotNone(segment)
        self.assertEqual(segment.completion_reason, "input_idle")
        self.assertGreaterEqual(segment.speech_block_count, config.min_speech_blocks)
        self.assertFalse(detector.has_pending_utterance())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
import re
import subprocess
import tempfile
import unicodedata
import uuid
import wave

from config import (
    FFMPEG_BIN,
    TTS_NORMALIZE_CHANNELS,
    TTS_NORMALIZE_SAMPLE_RATE,
    TTS_STORAGE_DIR,
    TTS_VOICE_ID,
)

try:
    from vieneu import Vieneu
except ModuleNotFoundError:
    Vieneu = None  # type: ignore[assignment]


TTS_MAX_DECIMAL_PLACES = 2
NUMBER_TOKEN_PATTERN = re.compile(r"(?<!\w)([-+]?\d(?:[\d.,]*\d)?)(?!\w)")
VIETNAMESE_DIGITS = [
    "không",
    "một",
    "hai",
    "ba",
    "bốn",
    "năm",
    "sáu",
    "bảy",
    "tám",
    "chín",
]
VIETNAMESE_GROUP_UNITS = [
    "",
    "nghìn",
    "triệu",
    "tỷ",
    "nghìn tỷ",
    "triệu tỷ",
]


def _round_decimal_for_tts(value: Decimal, places: int = TTS_MAX_DECIMAL_PLACES) -> Decimal:
    quantizer = Decimal("1").scaleb(-places)
    rounded = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral():
        return rounded.quantize(Decimal("1"))
    return rounded.normalize()


def _parse_number_token(token: str) -> Decimal | None:
    normalized = str(token or "").strip()
    if not normalized:
        return None

    sign = ""
    if normalized[0] in {"+", "-"}:
        sign = normalized[0]
        normalized = normalized[1:]

    if not normalized or not re.fullmatch(r"\d(?:[\d.,]*\d)?", normalized):
        return None

    decimal_separator: str | None = None
    thousand_separator: str | None = None

    if "." in normalized and "," in normalized:
        decimal_separator = "." if normalized.rfind(".") > normalized.rfind(",") else ","
        thousand_separator = "," if decimal_separator == "." else "."
    elif "." in normalized:
        dot_parts = normalized.split(".")
        if len(dot_parts) == 2 and len(dot_parts[1]) <= TTS_MAX_DECIMAL_PLACES:
            decimal_separator = "."
        else:
            thousand_separator = "."
    elif "," in normalized:
        comma_parts = normalized.split(",")
        if len(comma_parts) == 2 and len(comma_parts[1]) <= TTS_MAX_DECIMAL_PLACES:
            decimal_separator = ","
        else:
            thousand_separator = ","

    canonical = normalized
    if thousand_separator:
        canonical = canonical.replace(thousand_separator, "")
    if decimal_separator:
        canonical = canonical.replace(decimal_separator, ".")

    if sign:
        canonical = f"{sign}{canonical}"

    try:
        return Decimal(canonical)
    except InvalidOperation:
        return None


def _read_under_thousand(number: int, *, force_full_read: bool) -> str:
    if number == 0 and force_full_read:
        return "không trăm"
    if number == 0:
        return ""

    hundreds = number // 100
    tens = (number % 100) // 10
    ones = number % 10
    parts: list[str] = []

    if hundreds > 0 or force_full_read:
        parts.extend([VIETNAMESE_DIGITS[hundreds], "trăm"])

    if tens > 1:
        parts.extend([VIETNAMESE_DIGITS[tens], "mươi"])
        if ones == 1:
            parts.append("mốt")
        elif ones == 4:
            parts.append("tư")
        elif ones == 5:
            parts.append("lăm")
        elif ones > 0:
            parts.append(VIETNAMESE_DIGITS[ones])
    elif tens == 1:
        parts.append("mười")
        if ones == 5:
            parts.append("lăm")
        elif ones > 0:
            parts.append(VIETNAMESE_DIGITS[ones])
    elif ones > 0:
        if hundreds > 0 or force_full_read:
            parts.append("lẻ")
        parts.append(VIETNAMESE_DIGITS[ones])

    return " ".join(parts).strip()


def _integer_to_vietnamese(number: int) -> str:
    if number == 0:
        return VIETNAMESE_DIGITS[0]

    groups: list[int] = []
    remaining = abs(number)
    while remaining > 0:
        groups.append(remaining % 1000)
        remaining //= 1000

    parts: list[str] = []
    seen_non_zero_group = False
    for index in range(len(groups) - 1, -1, -1):
        group_value = groups[index]
        if group_value == 0:
            continue

        lower_groups_exist = any(value > 0 for value in groups[:index])
        force_full_read = seen_non_zero_group and group_value < 100 and lower_groups_exist
        group_text = _read_under_thousand(group_value, force_full_read=force_full_read)
        if group_text:
            parts.append(group_text)
        unit = VIETNAMESE_GROUP_UNITS[index] if index < len(VIETNAMESE_GROUP_UNITS) else ""
        if unit:
            parts.append(unit)
        seen_non_zero_group = True

    return " ".join(parts).strip()


def _decimal_to_vietnamese(value: Decimal) -> str:
    rounded = _round_decimal_for_tts(value)
    plain_text = format(rounded, "f")

    sign_prefix = ""
    if plain_text.startswith("-"):
        sign_prefix = "âm "
        plain_text = plain_text[1:]

    integer_text, dot, fractional_text = plain_text.partition(".")
    integer_words = _integer_to_vietnamese(int(integer_text or "0"))
    if not dot or not fractional_text:
        return f"{sign_prefix}{integer_words}".strip()

    fractional_words = " ".join(VIETNAMESE_DIGITS[int(char)] for char in fractional_text)
    return f"{sign_prefix}{integer_words} phẩy {fractional_words}".strip()


def _normalize_number_tokens_for_tts(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        parsed = _parse_number_token(token)
        if parsed is None:
            return token
        return _decimal_to_vietnamese(parsed)

    return NUMBER_TOKEN_PATTERN.sub(replace, text or "")


def _restore_title_case_for_uppercase_words(text: str) -> str:
    normalized_tokens: list[str] = []
    for token in (text or "").split():
        letters = [char for char in token if char.isalpha()]
        if len(letters) > 1 and token.upper() == token:
            normalized_tokens.append(token.title())
        else:
            normalized_tokens.append(token)
    return " ".join(normalized_tokens)


def normalize_text_for_tts(text: str) -> str:
    normalized = _normalize_number_tokens_for_tts(" ".join((text or "").split()))

    cleaned_chars: list[str] = []
    for char in normalized:
        if unicodedata.category(char).startswith(("P", "S")):
            cleaned_chars.append(" ")
        else:
            cleaned_chars.append(char)
    normalized = re.sub(r"\s+", " ", "".join(cleaned_chars)).strip()
    return _restore_title_case_for_uppercase_words(normalized)


def strip_punctuation_for_tts(text: str) -> str:
    return normalize_text_for_tts(text)


@dataclass(slots=True)
class SynthesizedSpeech:
    text: str
    spoken_text: str
    file_path: Path
    duration_seconds: float
    voice_name: str
    sample_rate: int
    channels: int


class TTSService:
    def __init__(self, voice_id: int = TTS_VOICE_ID, output_dir: Path = TTS_STORAGE_DIR) -> None:
        self._lock = Lock()
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self.voice_id = voice_id
        self.voice_name = ""
        self.voice_data = None
        self._tts = None
        self._voices = None

    def _ensure_model_loaded(self) -> None:
        if Vieneu is None:
            raise RuntimeError("vieneu is not installed in the backend environment.")
        if self._tts is not None and self.voice_data is not None and self._voices is not None:
            return

        self._tts = Vieneu()
        self._voices = self._tts.list_preset_voices()
        if self.voice_id < 0 or self.voice_id >= len(self._voices):
            raise ValueError(f"voice_id={self.voice_id} is out of range. Available voices: {len(self._voices)}")

        self.voice_name = str(self._voices[self.voice_id][1])
        self.voice_data = self._tts.get_preset_voice(self.voice_name)

    def prewarm(self) -> None:
        with self._lock:
            self._ensure_model_loaded()

    def _normalize_wav(self, source_path: Path, output_path: Path) -> None:
        command = [
            FFMPEG_BIN,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            str(TTS_NORMALIZE_CHANNELS),
            "-ar",
            str(TTS_NORMALIZE_SAMPLE_RATE),
            "-sample_fmt",
            "s16",
            str(output_path),
        ]
        subprocess.run(command, check=True)

    def _read_wav_metadata(self, file_path: Path) -> tuple[float, int, int]:
        with wave.open(str(file_path), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            duration_seconds = frame_count / float(sample_rate or 1)
        return duration_seconds, sample_rate, channels

    def synthesize(self, text: str) -> SynthesizedSpeech:
        spoken_text = normalize_text_for_tts(text)
        if not spoken_text:
            raise ValueError("No speakable text was provided for TTS.")

        with self._lock:
            self._ensure_model_loaded()
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".wav",
                prefix="vieneu_raw_",
                dir=self._output_dir,
                delete=False,
            ) as temp_file:
                raw_path = Path(temp_file.name)

            output_path = self._output_dir / f"tts_{uuid.uuid4().hex}.wav"
            assert self._tts is not None
            assert self.voice_data is not None
            audio = self._tts.infer(text=spoken_text, voice=self.voice_data)
            self._tts.save(audio, str(raw_path))

            try:
                self._normalize_wav(raw_path, output_path)
            finally:
                raw_path.unlink(missing_ok=True)

        duration_seconds, sample_rate, channels = self._read_wav_metadata(output_path)
        return SynthesizedSpeech(
            text=text,
            spoken_text=spoken_text,
            file_path=output_path,
            duration_seconds=duration_seconds,
            voice_name=self.voice_name,
            sample_rate=sample_rate,
            channels=channels,
        )


tts_service = TTSService()

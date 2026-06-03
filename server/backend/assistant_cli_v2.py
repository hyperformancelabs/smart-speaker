from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import tempfile
import wave

import requests

from cli_common import (
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE_ID,
    DEFAULT_NFC_TAG_ID,
    DEFAULT_USER_ID,
    FORGET_COMMANDS,
    HISTORY_COMMANDS,
    QUIT_COMMANDS,
    RESET_COMMANDS,
    CliSession,
    clear_local_session,
    format_turn_summary,
    load_session_cache,
    persist_session_cache,
    print_session_history,
    reset_remote_session,
    update_local_session,
)

try:
    import numpy as np
    import sounddevice as sd
except ModuleNotFoundError:
    np = None  # type: ignore[assignment]
    sd = None  # type: ignore[assignment]


DEFAULT_RECORDINGS_DIR = Path(__file__).resolve().parent / "cli_recordings"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice CLI để test browser/audio endpoint của backend.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL của server/backend.")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="User ID gửi kèm vào request.")
    parser.add_argument("--nfc-tag-id", default=DEFAULT_NFC_TAG_ID, help="NFC tag ID dùng để load profile.")
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID, help="Device ID dùng để giữ session cache.")
    parser.add_argument("--sample-rate", type=int, default=16000, help="Sample rate ghi âm local.")
    parser.add_argument("--input-device", default=None, help="Tên hoặc index input device.")
    parser.add_argument("--output-device", default=None, help="Tên hoặc index output device.")
    parser.add_argument("--no-playback", action="store_true", help="Không auto-play TTS trả về từ server.")
    parser.add_argument("--show-json", action="store_true", help="In raw JSON response sau mỗi turn.")
    parser.add_argument("--list-audio-devices", action="store_true", help="In danh sách audio devices rồi thoát.")
    return parser.parse_args()


def parse_device_arg(device: str | None) -> str | int | None:
    if device is None:
        return None
    stripped = str(device).strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return int(stripped)
    return stripped


def reset_both_sides(base_url: str, session: CliSession) -> None:
    clear_local_session(session)
    try:
        reset_remote_session(base_url, session)
    except requests.RequestException as exc:
        print(f"Không reset được remote session: {exc}")


def record_audio_to_wav(
    *,
    sample_rate: int,
    input_device: str | int | None,
    output_dir: Path,
) -> Path:
    if sd is None or np is None:
        raise RuntimeError("Cần cài thêm numpy và sounddevice để dùng voice CLI.")

    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[np.ndarray] = []

    def callback(indata, frames, time_info, status) -> None:
        del frames
        del time_info
        if status:
            print(f"[audio_status] {status}")
        chunks.append(indata.copy())

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        callback=callback,
        device=input_device,
    ):
        print("Đang ghi âm. Nhấn Enter để dừng và gửi lên server.")
        input()

    if not chunks:
        raise RuntimeError("Không thu được frame audio nào từ microphone.")

    audio = np.concatenate(chunks, axis=0)
    audio = np.clip(audio, -1.0, 1.0)
    audio_i16 = (audio * 32767.0).astype(np.int16)

    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="server_cli_voice_",
        suffix=".wav",
        dir=output_dir,
        delete=False,
    ) as temp_file:
        wav_path = Path(temp_file.name)

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_i16.tobytes())

    return wav_path


def upload_audio_turn(base_url: str, session: CliSession, audio_path: Path) -> dict[str, object]:
    with audio_path.open("rb") as audio_file:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/dev/assistant-turn",
            data={
                "user_id": session.user_id,
                "nfc_tag_id": session.nfc_tag_id,
                "device_id": session.device_id,
                "session_state": json.dumps(session.session_state, ensure_ascii=False),
            },
            files={
                "audio": (audio_path.name, audio_file, "audio/wav"),
            },
            timeout=180,
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def play_remote_wav(url: str, output_device: str | int | None) -> None:
    if sd is None or np is None:
        raise RuntimeError("Cần cài thêm numpy và sounddevice để phát audio local.")

    response = requests.get(url, timeout=180)
    response.raise_for_status()

    with wave.open(io.BytesIO(response.content), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        pcm_bytes = wav_file.readframes(frame_count)

    if sample_width == 1:
        audio = (np.frombuffer(pcm_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(pcm_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        audio = audio.reshape(-1, channels)

    sd.play(audio, samplerate=sample_rate, device=output_device)
    sd.wait()


def main() -> None:
    args = parse_args()

    if args.list_audio_devices:
        if sd is None:
            raise SystemExit("sounddevice chưa được cài trong environment hiện tại.")
        print(sd.query_devices())
        return

    session = CliSession(
        user_id=args.user_id,
        nfc_tag_id=args.nfc_tag_id,
        device_id=args.device_id,
    )
    load_session_cache(session)

    input_device = parse_device_arg(args.input_device)
    output_device = parse_device_arg(args.output_device)

    print("Server voice CLI v2")
    print(f"base_url={args.base_url}")
    print(f"user_id={session.user_id} nfc_tag_id={session.nfc_tag_id} device_id={session.device_id}")
    print("Commands: /record, /history, /reset, /exit")
    print("Để ghi âm nhanh, chỉ cần Enter ở prompt trống.")

    while True:
        try:
            command = input("\nVoice> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThoát voice CLI.")
            break

        lowered = command.lower()
        if lowered in QUIT_COMMANDS:
            print("Thoát voice CLI.")
            break
        if lowered in RESET_COMMANDS or lowered in FORGET_COMMANDS:
            reset_both_sides(args.base_url, session)
            persist_session_cache(session)
            print("Đã reset context local và yêu cầu backend clear session cache.")
            continue
        if lowered in HISTORY_COMMANDS:
            print_session_history(session)
            continue

        if command and lowered not in {"/record", "record"}:
            try:
                result = requests.post(
                    f"{args.base_url.rstrip('/')}/api/process-command",
                    json={
                        "user_id": session.user_id,
                        "nfc_tag_id": session.nfc_tag_id,
                        "device_id": session.device_id,
                        "text_input": command,
                        "session_state": session.session_state,
                    },
                    timeout=120,
                )
                result.raise_for_status()
                payload = result.json()
            except requests.RequestException as exc:
                print(f"Lỗi gọi backend: {exc}")
                continue

            print("\n=== output ===")
            print(format_turn_summary(payload))
            if args.show_json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            update_local_session(session, command, payload)
            continue

        try:
            wav_path = record_audio_to_wav(
                sample_rate=args.sample_rate,
                input_device=input_device,
                output_dir=DEFAULT_RECORDINGS_DIR,
            )
        except Exception as exc:
            print(f"Không ghi âm được: {exc}")
            continue

        try:
            payload = upload_audio_turn(args.base_url, session, wav_path)
        except requests.RequestException as exc:
            print(f"Lỗi upload audio lên backend: {exc}")
            wav_path.unlink(missing_ok=True)
            continue

        transcript = (
            ((payload.get("transcription") or {}) if isinstance(payload.get("transcription"), dict) else {}).get("text")
            or "(empty transcript)"
        )
        print("\n=== transcript ===")
        print(transcript)
        print("\n=== output ===")
        print(format_turn_summary(payload))
        if args.show_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        update_local_session(session, str(transcript), payload)

        if not args.no_playback:
            playback = payload.get("playback", {}) if isinstance(payload.get("playback"), dict) else {}
            tts = playback.get("tts", {}) if isinstance(playback.get("tts"), dict) else {}
            tts_url = str(tts.get("url") or "").strip()
            if tts_url:
                try:
                    play_remote_wav(tts_url, output_device=output_device)
                except Exception as exc:
                    print(f"Không phát được TTS local: {exc}")

        wav_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json

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
    build_text_turn_payload,
    clear_local_session,
    format_turn_summary,
    load_session_cache,
    persist_session_cache,
    post_json,
    print_session_history,
    reset_remote_session,
    update_local_session,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive text CLI để test voice backend qua HTTP.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL của server/backend.")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="User ID gửi kèm vào request.")
    parser.add_argument("--nfc-tag-id", default=DEFAULT_NFC_TAG_ID, help="NFC tag ID dùng để load profile.")
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID, help="Device ID dùng để giữ session cache.")
    parser.add_argument("--show-json", action="store_true", help="In raw JSON response sau mỗi turn.")
    return parser.parse_args()


def reset_both_sides(base_url: str, session: CliSession) -> None:
    clear_local_session(session)
    try:
        reset_remote_session(base_url, session)
    except requests.RequestException as exc:
        print(f"Không reset được remote session: {exc}")


def main() -> None:
    args = parse_args()
    session = CliSession(
        user_id=args.user_id,
        nfc_tag_id=args.nfc_tag_id,
        device_id=args.device_id,
    )
    load_session_cache(session)

    print("Server assistant CLI")
    print(f"base_url={args.base_url}")
    print(f"user_id={session.user_id} nfc_tag_id={session.nfc_tag_id} device_id={session.device_id}")
    print("Commands: /forget, /reset, /history, /exit")

    while True:
        try:
            text_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThoát CLI.")
            break

        if not text_input:
            continue

        lowered = text_input.lower()
        if lowered in QUIT_COMMANDS:
            print("Thoát CLI.")
            break
        if lowered in RESET_COMMANDS or lowered in FORGET_COMMANDS:
            reset_both_sides(args.base_url, session)
            persist_session_cache(session)
            print("Đã reset context local và yêu cầu backend clear session cache.")
            continue
        if lowered in HISTORY_COMMANDS:
            print_session_history(session)
            continue

        try:
            result = post_json(
                args.base_url,
                "/api/process-command",
                build_text_turn_payload(session, text_input),
            )
        except requests.RequestException as exc:
            print(f"Lỗi gọi backend: {exc}")
            continue

        print("\n=== output ===")
        print(format_turn_summary(result))
        if args.show_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))

        update_local_session(session, text_input, result)


if __name__ == "__main__":
    main()

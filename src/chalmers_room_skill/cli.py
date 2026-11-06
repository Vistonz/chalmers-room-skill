from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import browser


def _state_dir(value: str | None) -> Path:
    return Path(value).expanduser() if value else browser.default_state_dir()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _save(result: browser.CaptureResult, prefix: str, state_dir: Path) -> Path:
    path = browser.captures_dir(state_dir) / f"{prefix}-{_timestamp()}.json"
    return browser.write_capture(result, path)


def command_login(args: argparse.Namespace) -> int:
    browser.login(
        state_file=browser.auth_state_path(_state_dir(args.state_dir)),
        url=args.url,
        timeout_ms=args.timeout_ms,
    )
    return 0


def command_bookings(args: argparse.Namespace) -> int:
    result = browser.capture(
        url=args.url,
        state_file=browser.auth_state_path(_state_dir(args.state_dir)),
        headless=args.headless,
        settle_ms=args.settle_ms,
        timeout_ms=args.timeout_ms,
    )
    path = _save(result, "bookings-before", _state_dir(args.state_dir))
    print(f"Saved current bookings data: {path}")
    print("\nPage text:\n")
    print(result.text)
    return 0


def command_rooms(args: argparse.Namespace) -> int:
    result = browser.capture(
        url=args.url,
        state_file=browser.auth_state_path(_state_dir(args.state_dir)),
        headless=args.headless,
        settle_ms=args.settle_ms,
        timeout_ms=args.timeout_ms,
    )
    path = _save(result, "rooms", _state_dir(args.state_dir))
    print(f"Saved room availability data: {path}")
    print("\nPage text:\n")
    print(result.text)
    return 0


def command_book(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args.state_dir)

    # Always capture existing bookings before assisting a new reservation.
    before = browser.capture(
        url=browser.MY_BOOKINGS_URL,
        state_file=browser.auth_state_path(state_dir),
        headless=args.headless,
        settle_ms=args.settle_ms,
        timeout_ms=args.timeout_ms,
    )
    before_path = _save(before, "bookings-before", state_dir)
    print(f"Saved pre-booking bookings data: {before_path}")

    print("\nPlease review your existing bookings in the browser before continuing.")
    print("Chalmers library group rooms allow at most 4 bookings of 4 hours in 4 weeks.")
    input("Press Enter to open the booking page... ")

    after = browser.assisted_booking(
        state_file=browser.auth_state_path(state_dir),
        url=args.url,
        timeout_ms=args.timeout_ms,
    )
    after_path = _save(after, "booking-after", state_dir)
    print(f"Saved post-booking data: {after_path}")
    print("\nConfirmation page text:\n")
    print(after.text)
    return 0


def command_session(args: argparse.Namespace) -> int:
    info = browser.session_info(
        state_file=browser.auth_state_path(_state_dir(args.state_dir)),
        url=args.url,
        timeout_ms=args.timeout_ms,
    )
    print(f"URL: {info['final_url']}")
    print(f"Title: {info['title']}")
    print(f"Cookies: {len(info['cookies'])}")
    for cookie in info["cookies"]:
        print(f"  {cookie['domain']} {cookie['name']}")
    print(f"LocalStorage keys: {info['local_storage_keys']}")
    print(f"SessionStorage keys: {info['session_storage_keys']}")
    print("\nPage text:\n")
    print(info["text"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chalmers-room",
        description="Session-based helper for Chalmers library group-room bookings",
    )
    parser.add_argument(
        "--state-dir",
        help="directory for browser session and captures (default: ~/.chalmers-room-skill)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="open a browser and save your login session")
    login.add_argument("--url", default=browser.BOOKING_URL)
    login.add_argument("--timeout-ms", type=int, default=30_000)
    login.set_defaults(handler=command_login)

    bookings = subparsers.add_parser(
        "bookings",
        help="capture existing bookings before making a new reservation",
    )
    bookings.add_argument("--url", default=browser.MY_BOOKINGS_URL)
    bookings.add_argument("--headless", action="store_true")
    bookings.add_argument("--settle-ms", type=int, default=5_000)
    bookings.add_argument("--timeout-ms", type=int, default=30_000)
    bookings.set_defaults(handler=command_bookings)

    rooms = subparsers.add_parser("rooms", help="capture current room availability")
    rooms.add_argument("--url", default=browser.BOOKING_URL)
    rooms.add_argument("--headless", action="store_true")
    rooms.add_argument("--settle-ms", type=int, default=5_000)
    rooms.add_argument("--timeout-ms", type=int, default=30_000)
    rooms.set_defaults(handler=command_rooms)

    book = subparsers.add_parser(
        "book",
        help="capture existing bookings, then open an assisted booking page",
    )
    book.add_argument("--url", default=browser.BOOKING_URL)
    book.add_argument("--headless", action="store_true")
    book.add_argument("--settle-ms", type=int, default=5_000)
    book.add_argument("--timeout-ms", type=int, default=30_000)
    book.set_defaults(handler=command_book)

    session = subparsers.add_parser(
        "session",
        help="show non-secret session diagnostics",
    )
    session.add_argument("--url", default=browser.BOOKING_URL)
    session.add_argument("--timeout-ms", type=int, default=30_000)
    session.set_defaults(handler=command_session)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())


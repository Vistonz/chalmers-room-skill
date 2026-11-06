from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import browser
from .booking import (
    BookingError,
    BookingPlan,
    ExistingBooking,
    create_booking_request,
    get_booking_source,
)


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
    url = args.url or get_booking_source(args.location).booking_url
    result = browser.capture(
        url=url,
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


def command_availability(args: argparse.Namespace) -> int:
    start_after = (
        datetime.fromisoformat(args.start_after)
        if args.start_after
        else datetime.now()
    )
    try:
        candidate = browser.find_earliest_availability(
            location=args.location,
            start_after=start_after,
            duration_minutes=args.duration_minutes,
            horizon_days=args.horizon_days,
            state_file=browser.auth_state_path(_state_dir(args.state_dir)),
            headless=args.headless,
            settle_ms=args.settle_ms,
            timeout_ms=args.timeout_ms,
        )
    except (BookingError, browser.BookingDataError) as exc:
        print(f"查询未完成：{exc}", file=sys.stderr)
        return 2

    if candidate is None:
        print("查询范围内没有找到符合条件的小组会议室空档。")
        return 0

    source = get_booking_source(args.location)
    print(f"地点：{source.label}")
    print(f"房间：{candidate.room_name}（{candidate.room_id}）")
    print(f"时间：{candidate.start_at:%Y-%m-%d %H:%M}-{candidate.end_at:%H:%M}")
    print(f"时长：{args.duration_minutes} 分钟")
    return 0


def _format_booking(booking: ExistingBooking) -> str:
    room = booking.room_name or booking.room_id or "未知房间"
    title = booking.title or "未命名"
    return (
        f"- {booking.start:%Y-%m-%d %H:%M}-{booking.end:%H:%M} "
        f"{room}（{title}）"
    )


def _print_booking_plan(plan: BookingPlan) -> None:
    request = plan.request
    weekdays = "一二三四五六日"
    weekday = weekdays[request.booking_date.weekday()]
    hours, remainder = divmod(request.duration_minutes, 60)
    duration = f"{hours} 小时" if hours else ""
    if remainder:
        duration += f" {remainder} 分钟"

    print("\n预订前检查通过")
    print("=" * 48)
    print(f"房间：{request.room_name}（{request.room_id}）")
    print(
        f"日期：{request.booking_date:%Y-%m-%d}（周{weekday}）"
    )
    print(f"时间：{request.start:%H:%M}-{request.end_text}（{duration.strip()}）")
    print(f"用途：{request.title}")
    print(f"现有有效预订：{len(plan.existing_bookings)} 条")
    for booking in plan.existing_bookings:
        print(_format_booking(booking))
    print("=" * 48)


def command_book(args: argparse.Namespace) -> int:
    state_dir = _state_dir(args.state_dir)
    try:
        request = create_booking_request(
            date_text=args.date,
            start_text=args.start,
            end_text=args.end,
            room_name=args.room,
            room_id=args.room_id,
            title=args.message,
            location=args.location,
        )
        result = browser.book_room(
            request,
            state_file=browser.auth_state_path(state_dir),
            submit=args.yes,
            headless=args.headless,
            settle_ms=args.settle_ms,
            timeout_ms=args.timeout_ms,
            on_plan=_print_booking_plan,
        )
    except (BookingError, browser.BookingSubmissionError) as exc:
        print(f"预订未完成：{exc}", file=sys.stderr)
        return 2

    if not result.submitted:
        print("\n这是预览，尚未提交。")
        print("确认房间、日期和时间无误后，在命令末尾添加 --yes 才会真正预订。")
        return 0

    print(f"\n预订请求已提交，确认编号：{result.reservation_id}")
    if result.post_booking_error:
        print(f"注意：{result.post_booking_error}")
        print("请不要重复提交，稍后运行 `chalmers-room bookings` 核对。")
        return 0

    after = result.after_bookings or []
    print(f"提交后重新读取到 {len(after)} 条有效预订。")
    for booking in after:
        print(_format_booking(booking))
    matching = [
        booking
        for booking in after
        if booking.room_id == request.room_id
        and booking.start == request.start_at
        and booking.end == request.end_at
    ]
    if matching:
        print("新预订已在预订列表中确认。")
    else:
        print("提交已获确认，但列表中暂未出现完全匹配项；请稍后运行 bookings 核对。")
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
        description="Automated Chalmers group-room booking helper",
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
    rooms.add_argument("--location", choices=("library", "ed"), default="library")
    rooms.add_argument("--url")
    rooms.add_argument("--headless", action="store_true")
    rooms.add_argument("--settle-ms", type=int, default=5_000)
    rooms.add_argument("--timeout-ms", type=int, default=30_000)
    rooms.set_defaults(handler=command_rooms)

    availability = subparsers.add_parser(
        "availability",
        help="find the earliest available room for a requested duration",
    )
    availability.add_argument("--location", choices=("library", "ed"), default="ed")
    availability.add_argument("--duration-minutes", type=int, default=60)
    availability.add_argument("--horizon-days", type=int, default=2)
    availability.add_argument(
        "--start-after",
        help="search after this local datetime in ISO format; defaults to now",
    )
    availability.add_argument("--headless", action="store_true")
    availability.add_argument("--settle-ms", type=int, default=5_000)
    availability.add_argument("--timeout-ms", type=int, default=30_000)
    availability.set_defaults(handler=command_availability)

    book = subparsers.add_parser(
        "book",
        help="validate and automatically submit one room reservation",
    )
    book.add_argument("--location", choices=("library", "ed"), default="library")
    book.add_argument("--date", required=True, help="booking date in YYYY-MM-DD format")
    book.add_argument("--start", required=True, help="start time in HH:MM format")
    book.add_argument("--end", required=True, help="end time in HH:MM format")
    room = book.add_mutually_exclusive_group(required=True)
    room.add_argument("--room", help="room name, for example EG-3207A")
    room.add_argument("--room-id", help="TimeEdit room ID, for example 501.4")
    book.add_argument("--message", required=True, help="booking title")
    book.add_argument(
        "--yes",
        action="store_true",
        help="submit the booking; without this flag the command only previews",
    )
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


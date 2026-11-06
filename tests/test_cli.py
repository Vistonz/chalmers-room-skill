from datetime import date, datetime, time

from chalmers_room_skill import browser
from chalmers_room_skill.booking import (
    BookingPlan,
    BookingRequest,
    ExistingBooking,
)
from chalmers_room_skill.cli import build_parser, main


def test_cli_exposes_required_commands() -> None:
    parser = build_parser()
    for command in ("login", "bookings", "rooms", "availability", "book", "session"):
        argv = [command]
        if command == "book":
            argv.extend(
                [
                    "--date",
                    "2026-11-10",
                    "--start",
                    "13:00",
                    "--end",
                    "15:00",
                    "--room",
                    "BIB-G134C",
                    "--message",
                    "Grupparbete",
                ]
            )
        elif command == "availability":
            argv.extend(["--location", "ed", "--duration-minutes", "60"])
        args = parser.parse_args(argv)
        assert args.command == command
        assert callable(args.handler)


def test_bookings_command_defaults_to_my_bookings_url() -> None:
    parser = build_parser()
    args = parser.parse_args(["bookings"])
    assert args.url.endswith("/my.html")
    assert args.handler.__name__ == "command_bookings"


def test_book_without_yes_only_previews(monkeypatch, capsys) -> None:
    calls: list[bool] = []
    request = BookingRequest(
        booking_date=date(2026, 11, 10),
        start=time(13, 0),
        end=time(15, 0),
        room_id="18836.4",
        room_name="BIB-G134C",
        title="Grupparbete",
    )
    plan = BookingPlan(request=request, existing_bookings=[], availability=[])

    def fake_book_room(*args, **kwargs):
        calls.append(kwargs["submit"])
        kwargs["on_plan"](plan)
        return browser.BookingResult(plan=plan, submitted=False)

    monkeypatch.setattr(browser, "book_room", fake_book_room)

    exit_code = main(
        [
            "book",
            "--date",
            "2026-11-10",
            "--start",
            "13:00",
            "--end",
            "15:00",
            "--room",
            "BIB-G134C",
            "--message",
            "Grupparbete",
        ]
    )

    assert exit_code == 0
    assert calls == [False]
    assert "尚未提交" in capsys.readouterr().out


def test_book_with_yes_reports_post_booking_data(monkeypatch, capsys) -> None:
    request = BookingRequest(
        booking_date=date(2026, 11, 10),
        start=time(13, 0),
        end=time(15, 0),
        room_id="18836.4",
        room_name="BIB-G134C",
        title="Grupparbete",
    )
    plan = BookingPlan(request=request, existing_bookings=[], availability=[])
    new_booking = ExistingBooking(
        title=request.title,
        room_name=request.room_name,
        room_id=request.room_id,
        start=datetime.combine(request.booking_date, request.start),
        end=datetime.combine(request.booking_date, request.end),
        status="Reserverad",
    )

    def fake_book_room(*args, **kwargs):
        kwargs["on_plan"](plan)
        return browser.BookingResult(
            plan=plan,
            submitted=True,
            reservation_id="9876543",
            after_bookings=[new_booking],
        )

    monkeypatch.setattr(browser, "book_room", fake_book_room)

    exit_code = main(
        [
            "book",
            "--date",
            "2026-11-10",
            "--start",
            "13:00",
            "--end",
            "15:00",
            "--room",
            "BIB-G134C",
            "--message",
            "Grupparbete",
            "--yes",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "9876543" in output
    assert "新预订已在预订列表中确认" in output


def test_book_passes_ed_location_to_request(monkeypatch, capsys) -> None:
    captured: list[BookingRequest] = []
    plan_holder: list[BookingPlan] = []

    def fake_book_room(request, **kwargs):
        captured.append(request)
        plan = BookingPlan(request=request, existing_bookings=[], availability=[])
        plan_holder.append(plan)
        kwargs["on_plan"](plan)
        return browser.BookingResult(plan=plan, submitted=False)

    monkeypatch.setattr(browser, "book_room", fake_book_room)

    exit_code = main(
        [
            "book",
            "--location",
            "ed",
            "--date",
            "2026-11-10",
            "--start",
            "13:00",
            "--end",
            "14:00",
            "--room",
            "EG-3207A",
            "--message",
            "Grupparbete",
        ]
    )

    assert exit_code == 0
    assert captured[0].source == "ed"
    assert captured[0].room_id == "501.4"
    assert "EG-3207A" in capsys.readouterr().out


def test_availability_command_prints_candidate(monkeypatch, capsys) -> None:
    candidate = browser.AvailabilityCandidate(
        booking_date=date(2026, 11, 6),
        room_id="501.4",
        room_name="EG-3207A",
        start_minute=19 * 60,
        end_minute=20 * 60,
    )
    monkeypatch.setattr(
        browser,
        "find_earliest_availability",
        lambda **kwargs: candidate,
    )

    exit_code = main(
        [
            "availability",
            "--location",
            "ed",
            "--duration-minutes",
            "60",
            "--start-after",
            "2026-11-06T18:47:03",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "EG-3207A" in output
    assert "2026-11-06 19:00-20:00" in output


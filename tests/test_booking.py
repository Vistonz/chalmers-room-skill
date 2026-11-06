from __future__ import annotations

from datetime import date, datetime

import pytest

from chalmers_room_skill.booking import (
    AvailabilitySlot,
    BookingError,
    BookingRequest,
    ExistingBooking,
    build_submission_form,
    create_booking_request,
    parse_availability_html,
    parse_bookings_csv,
    parse_reservation_id,
    resolve_room,
    validate_booking_plan,
    week_url_for_date,
)


def make_request(start: str = "10:00", end: str = "12:00") -> BookingRequest:
    return create_booking_request(
        date_text="2026-11-10",
        start_text=start,
        end_text=end,
        room_name="BIB-G134C",
        room_id=None,
        title="Grupparbete",
    )


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("10:07", "11:00", "15 分钟"),
        ("10:00", "10:15", "至少需要 30 分钟"),
        ("18:00", "21:15", "21:00"),
        ("09:00", "13:15", "不能超过 4 小时"),
    ],
)
def test_request_rules_reject_invalid_times(
    start: str,
    end: str,
    message: str,
) -> None:
    with pytest.raises(BookingError, match=message):
        make_request(start, end)


def test_availability_must_cover_the_whole_request() -> None:
    request = make_request("10:00", "12:00")
    availability = [
        AvailabilitySlot(
            booking_date=request.booking_date,
            room_id=request.room_id,
            begin_minute=8 * 60,
            end_minute=11 * 60,
        )
    ]

    with pytest.raises(BookingError, match="连续空档"):
        validate_booking_plan(request, [], availability)


def test_adjacent_availability_slots_are_merged() -> None:
    request = make_request("08:30", "09:30")
    availability = [
        AvailabilitySlot(
            booking_date=request.booking_date,
            room_id=request.room_id,
            begin_minute=8 * 60,
            end_minute=9 * 60,
        ),
        AvailabilitySlot(
            booking_date=request.booking_date,
            room_id=request.room_id,
            begin_minute=9 * 60,
            end_minute=10 * 60,
        ),
    ]

    validate_booking_plan(request, [], availability)


def test_resolve_ed_room_uses_ed_source() -> None:
    assert resolve_room(location="ed", room_name="EG-3207A") == (
        "EG-3207A",
        "501.4",
    )
    assert resolve_room(location="ed", room_id="574.4") == (
        "EG-4205A",
        "574.4",
    )


def test_ed_booking_can_end_at_midnight() -> None:
    request = create_booking_request(
        date_text="2026-11-10",
        start_text="23:00",
        end_text="24:00",
        room_name="EG-3207A",
        room_id=None,
        title="Grupparbete",
        location="ed",
    )

    assert request.source == "ed"
    assert request.end_minute == 24 * 60
    assert request.end_at == datetime(2026, 11, 11, 0, 0)
    assert build_submission_form(request, "https://example.test/ri.html")["endtime"] == (
        "24:00"
    )


def test_ed_rolling_two_week_limit_fails_closed() -> None:
    request = create_booking_request(
        date_text="2026-11-10",
        start_text="10:00",
        end_text="11:00",
        room_name="EG-3207A",
        room_id=None,
        title="Grupparbete",
        location="ed",
    )
    existing = [
        ExistingBooking(
            title=f"Bokning {day}",
            room_name="EG-3207A",
            room_id="501.4",
            start=datetime(2026, 11, day, 8, 0),
            end=datetime(2026, 11, day, 9, 0),
            status="Reserverad",
        )
        for day in (1, 2, 3, 4)
    ]
    availability = [
        AvailabilitySlot(
            booking_date=request.booking_date,
            room_id=request.room_id,
            begin_minute=8 * 60,
            end_minute=18 * 60,
        )
    ]

    with pytest.raises(BookingError, match="滚动 14 天"):
        validate_booking_plan(request, existing, availability)


def test_parse_availability_from_timeedit_markup() -> None:
    html = """
    <div class="slotfree2 slotfreetarget"
         data-dates="20261110"
         data-object="18836.4"
         data-beginminute="480"
         data-resmaxend="21"
         style="left: 0%; width: 15.3846154%;"></div>
    """

    slots = parse_availability_html(html, room_id="18836.4")

    assert len(slots) == 1
    assert slots[0].booking_date == date(2026, 11, 10)
    assert slots[0].begin_minute == 480
    assert slots[0].end_minute == pytest.approx(600)


def test_parse_ed_availability_subtracts_booked_rows() -> None:
    html = """
    <div class="weekDay" data-day="20261107">
      <div class="weekDiv">
        <a class="boxlink hour" onclick="return openObject(501.4, this, 't')">
          <div class="objbase">EG-3207A</div>
        </a>
        <a class="boxlink hour" onclick="return openObject(502.4, this, 't')">
          <div class="objbase">EG-3207B</div>
        </a>
      </div>
      <div class="slotfree2 slotfreetarget"
           data-resminheight="40"
           data-dates="20261107"
           data-beginminute="480"
           data-object="501.4"></div>
      <div class="bookingDiv"
           style="top: 0px; left: 0%; width: 50%; height: 40px;"
           title=" 2026-11-07 08:00 - 12:00 Grupparbete"></div>
      <div class="bookingDiv"
           style="top: 40px; left: 0%; width: 25%; height: 40px;"
           title=" 2026-11-07 08:00 - 10:00 Möte"></div>
    </div>
    """

    slots = parse_availability_html(html, location="ed")

    room_a = [slot for slot in slots if slot.room_id == "501.4"]
    room_b = [slot for slot in slots if slot.room_id == "502.4"]
    assert [(slot.begin_minute, slot.end_minute) for slot in room_a] == [
        (12 * 60, 24 * 60)
    ]
    assert [(slot.begin_minute, slot.end_minute) for slot in room_b] == [
        (10 * 60, 24 * 60)
    ]


def test_parse_bookings_csv_ignores_cancelled_rows() -> None:
    csv_text = (
        "\n"
        "TimeEdit,Chalmers\n"
        "Mina bokningar,2026-11-06 - 2027-05-06,\n"
        "Startdatum,Starttid,Slutdatum,Sluttid,Title,Kommentar,Lokalnamn,"
        "Rumsnummer,Kart länk,Hus,Campus,Utrustning,Antal datorer,"
        "Spärraktivitet,Status,Övriga objekt,Kurstillfälle\n"
        "2026-11-01,09:00,2026-11-01,10:00,Projekt,,BIB-G134C,"
        "18836.4,,,,,,,Reserverad,,\n"
        "2026-11-02,09:00,2026-11-02,10:00,Avbokad,,BIB-G134C,"
        "18836.4,,,,,,,Avbokad,,\n"
    )

    bookings = parse_bookings_csv(csv_text)

    assert len(bookings) == 1
    assert bookings[0].title == "Projekt"
    assert bookings[0].room_id == "18836.4"


def test_parse_bookings_csv_accepts_empty_minimal_export() -> None:
    csv_text = (
        "\n"
        "TimeEdit,Chalmers\n"
        "Mina bokningar,2026-11-06 - 2027-05-06,\n"
        "Startdatum,Starttid,Slutdatum,Sluttid, \n"
    )

    assert parse_bookings_csv(csv_text) == []


def test_parse_bookings_csv_accepts_data_without_optional_detail_columns() -> None:
    csv_text = (
        "Startdatum,Starttid,Slutdatum,Sluttid, \n"
        "2026-11-01,09:00,2026-11-01,10:00,\n"
    )

    bookings = parse_bookings_csv(csv_text)

    assert len(bookings) == 1
    assert bookings[0].room_id == ""
    assert bookings[0].title == ""


def test_rolling_four_week_limit_fails_closed() -> None:
    request = make_request()
    existing = [
        ExistingBooking(
            title=f"Bokning {day}",
            room_name="BIB-G134C",
            room_id="18836.4",
            start=datetime(2026, 11, day, 8, 0),
            end=datetime(2026, 11, day, 9, 0),
            status="Reserverad",
        )
        for day in (1, 2, 3, 4)
    ]
    availability = [
        AvailabilitySlot(
            booking_date=request.booking_date,
            room_id=request.room_id,
            begin_minute=8 * 60,
            end_minute=18 * 60,
        )
    ]

    with pytest.raises(BookingError, match="4 次"):
        validate_booking_plan(request, existing, availability)


def test_submission_form_matches_timeedit_contract() -> None:
    request = make_request("13:00", "15:00")

    form = build_submission_form(
        request,
        "https://cloud.timeedit.net/chalmers/web/student/ri.html#grid",
    )

    assert form == {
        "kind": "reserve",
        "nocache": "4",
        "l": "sv_SE",
        "o": "18836.4",
        "aos": "",
        "dates": "20261110",
        "starttime": "13:00",
        "endtime": "15:00",
        "url": "https://cloud.timeedit.net/chalmers/web/student/ri.html",
        "fe1": "Grupparbete",
    }


def test_parse_reservation_id_from_confirmation() -> None:
    html = '<table id="table0" data-resid="9876543"></table>'

    assert parse_reservation_id(html) == "9876543"
    assert parse_reservation_id("<p>No confirmation</p>") is None


def test_week_url_contains_monday_to_sunday() -> None:
    url = week_url_for_date(
        "https://example.test/ri.html?objects=18836.4&p=old",
        date(2026, 11, 10),
    )

    assert "p=20261109-20261115" in url
    assert "objects=18836.4" in url

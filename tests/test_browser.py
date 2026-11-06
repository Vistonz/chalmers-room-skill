from __future__ import annotations

from datetime import date, datetime, time

from chalmers_room_skill.booking import AvailabilitySlot, BookingRequest
from chalmers_room_skill.browser import (
    _candidate_from_slot,
    _submit_booking_once,
)
from chalmers_room_skill.booking import get_booking_source


class FakeResponse:
    def __init__(self, text: str, *, status: int = 200) -> None:
        self._text = text
        self.status = status
        self.ok = 200 <= status < 400

    def text(self) -> str:
        return self._text


class FakeRequestContext:
    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []
        self.request = self

    def post(self, url: str, *, form: dict[str, str], timeout: int) -> FakeResponse:
        self.posts.append({"url": url, "form": form, "timeout": timeout})
        if len(self.posts) == 1:
            return FakeResponse("123456789")
        return FakeResponse('<table id="table0" data-resid="9876543"></table>')


def test_submit_booking_posts_booking_exactly_once() -> None:
    request = BookingRequest(
        booking_date=date(2026, 11, 10),
        start=time(13, 0),
        end=time(15, 0),
        room_id="18836.4",
        room_name="BIB-G134C",
        title="Grupparbete",
    )
    context = FakeRequestContext()

    reservation_id, _ = _submit_booking_once(
        context,
        "https://example.test/ri.html",
        request,
        30_000,
    )

    assert reservation_id == "9876543"
    assert len(context.posts) == 2
    assert context.posts[0]["form"] == {"CSTTG": "gen"}
    booking_form = context.posts[1]["form"]
    assert booking_form["kind"] == "reserve"
    assert booking_form["CSTT"] == "123456789"
    assert booking_form["o"] == "18836.4"


def test_earliest_candidate_rounds_forward_and_respects_duration() -> None:
    source = get_booking_source("ed")
    candidate = _candidate_from_slot(
        AvailabilitySlot(
            booking_date=date(2026, 11, 6),
            room_id="501.4",
            begin_minute=18 * 60,
            end_minute=20 * 60,
        ),
        source=source,
        start_after=datetime(2026, 11, 6, 18, 47, 3),
        duration_minutes=60,
    )

    assert candidate is not None
    assert candidate.room_name == "EG-3207A"
    assert candidate.start_at == datetime(2026, 11, 6, 19, 0)
    assert candidate.end_at == datetime(2026, 11, 6, 20, 0)


def test_candidate_rejects_slot_that_is_too_short() -> None:
    candidate = _candidate_from_slot(
        AvailabilitySlot(
            booking_date=date(2026, 11, 6),
            room_id="501.4",
            begin_minute=18 * 60,
            end_minute=18 * 60 + 45,
        ),
        source=get_booking_source("ed"),
        start_after=datetime(2026, 11, 6, 18, 47, 3),
        duration_minutes=60,
    )

    assert candidate is None

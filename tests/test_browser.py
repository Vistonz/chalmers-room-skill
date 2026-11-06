from __future__ import annotations

from datetime import date, time

from chalmers_room_skill.booking import BookingRequest
from chalmers_room_skill.browser import _submit_booking_once


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

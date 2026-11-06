from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from io import StringIO


MAX_BOOKING_MINUTES = 4 * 60
MIN_BOOKING_MINUTES = 30
BOOKING_INCREMENT_MINUTES = 15
LATEST_END_MINUTE = 21 * 60
ROLLING_WINDOW_DAYS = 28
MAX_BOOKINGS_PER_WINDOW = 4
GRID_START_MINUTE = 8 * 60
GRID_END_MINUTE = 21 * 60

ROOMS_BY_NAME = {
    "BIB-G134C": "18836.4",
    "BIB-G134D": "18837.4",
    "BIB-G134E": "18838.4",
    "BIB-G134F": "18839.4",
    "BIB-G230B": "18842.4",
    "BIB-G234A": "18843.4",
    "BIB-G234B": "18844.4",
    "BIB-G234C": "18845.4",
    "BIB-G234D": "18846.4",
    "BIB-G234E": "18847.4",
    "BIB-G031C": "18834.4",
    "Agafyren": "699.4",
    "Blixtlåset": "697.4",
    "Kullagret": "698.4",
    "Skiftnyckel": "696.4",
    "Trepunktsbältet": "444.4",
}
ROOMS_BY_ID = {room_id: name for name, room_id in ROOMS_BY_NAME.items()}

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_ROOM_ID_PATTERN = re.compile(r"^\d+\.\d+$")
_WIDTH_PATTERN = re.compile(r"(?:^|;)\s*width\s*:\s*([0-9.]+)%", re.IGNORECASE)


class BookingError(ValueError):
    """A safe, user-facing booking validation error."""


class BookingDataError(BookingError):
    """Existing bookings or room availability could not be read reliably."""


@dataclass(frozen=True)
class BookingRequest:
    booking_date: date
    start: time
    end: time
    room_id: str
    room_name: str
    title: str

    @property
    def start_minute(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_minute(self) -> int:
        return self.end.hour * 60 + self.end.minute

    @property
    def duration_minutes(self) -> int:
        return self.end_minute - self.start_minute

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.booking_date, self.start)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.booking_date, self.end)


@dataclass(frozen=True)
class ExistingBooking:
    title: str
    room_name: str
    room_id: str
    start: datetime
    end: datetime
    status: str


@dataclass(frozen=True)
class AvailabilitySlot:
    booking_date: date
    room_id: str
    begin_minute: int
    end_minute: float


@dataclass(frozen=True)
class BookingPlan:
    request: BookingRequest
    existing_bookings: list[ExistingBooking]
    availability: list[AvailabilitySlot]


def resolve_room(
    *,
    room_name: str | None = None,
    room_id: str | None = None,
) -> tuple[str, str]:
    if bool(room_name) == bool(room_id):
        raise BookingError("请只指定房间名称或房间 ID 其中一个。")

    if room_name:
        normalized = room_name.strip()
        matching_name = next(
            (name for name in ROOMS_BY_NAME if name.casefold() == normalized.casefold()),
            None,
        )
        if matching_name is None:
            known = "、".join(ROOMS_BY_NAME)
            raise BookingError(f"未知房间“{normalized}”。可用房间：{known}")
        return matching_name, ROOMS_BY_NAME[matching_name]

    normalized_id = (room_id or "").strip()
    if not _ROOM_ID_PATTERN.fullmatch(normalized_id):
        raise BookingError("房间 ID 的格式应为数字.数字，例如 18836.4。")
    return ROOMS_BY_ID.get(normalized_id, normalized_id), normalized_id


def create_booking_request(
    *,
    date_text: str,
    start_text: str,
    end_text: str,
    room_name: str | None,
    room_id: str | None,
    title: str,
) -> BookingRequest:
    if not _DATE_PATTERN.fullmatch(date_text):
        raise BookingError("日期必须使用 YYYY-MM-DD 格式，例如 2026-11-10。")
    if not _TIME_PATTERN.fullmatch(start_text) or not _TIME_PATTERN.fullmatch(end_text):
        raise BookingError("时间必须使用 HH:MM 格式，例如 13:00。")

    try:
        booking_date = date.fromisoformat(date_text)
        start = time.fromisoformat(start_text)
        end = time.fromisoformat(end_text)
    except ValueError as exc:
        raise BookingError("日期或时间无效。") from exc

    resolved_name, resolved_id = resolve_room(
        room_name=room_name,
        room_id=room_id,
    )
    normalized_title = " ".join(title.split())
    if not normalized_title:
        raise BookingError("预订用途不能为空。")
    if len(normalized_title) > 100:
        raise BookingError("预订用途不能超过 100 个字符。")

    request = BookingRequest(
        booking_date=booking_date,
        start=start,
        end=end,
        room_id=resolved_id,
        room_name=resolved_name,
        title=normalized_title,
    )
    validate_request_rules(request)
    return request


def validate_request_rules(request: BookingRequest) -> None:
    if request.end <= request.start:
        raise BookingError("结束时间必须晚于开始时间。")
    if request.start.minute % BOOKING_INCREMENT_MINUTES:
        raise BookingError("开始时间必须按 15 分钟递增。")
    if request.end.minute % BOOKING_INCREMENT_MINUTES:
        raise BookingError("结束时间必须按 15 分钟递增。")

    duration = request.duration_minutes
    if duration < MIN_BOOKING_MINUTES:
        raise BookingError("单次预订至少需要 30 分钟。")
    if duration > MAX_BOOKING_MINUTES:
        raise BookingError("单次预订不能超过 4 小时。")
    if request.end_minute > LATEST_END_MINUTE:
        raise BookingError("预订必须在 21:00 或之前结束。")


def validate_booking_plan(
    request: BookingRequest,
    existing_bookings: list[ExistingBooking],
    availability: list[AvailabilitySlot],
) -> None:
    validate_request_rules(request)
    _validate_no_room_overlap(request, existing_bookings)
    _validate_rolling_limit(request, existing_bookings)
    _validate_availability(request, availability)


def _validate_no_room_overlap(
    request: BookingRequest,
    existing_bookings: list[ExistingBooking],
) -> None:
    for booking in existing_bookings:
        if booking.room_id != request.room_id:
            continue
        if request.start_at < booking.end and booking.start < request.end_at:
            raise BookingError("该房间在这段时间已有你的预订，未提交。")


def _validate_rolling_limit(
    request: BookingRequest,
    existing_bookings: list[ExistingBooking],
) -> None:
    starts = [booking.start for booking in existing_bookings] + [request.start_at]
    window = timedelta(days=ROLLING_WINDOW_DAYS)

    for candidate_start in starts:
        count = sum(
            1 for booking_start in starts
            if candidate_start <= booking_start < candidate_start + window
        )
        includes_new_booking = candidate_start <= request.start_at < candidate_start + window
        if includes_new_booking and count > MAX_BOOKINGS_PER_WINDOW:
            raise BookingError(
                "这次预订会超过滚动 4 周内最多 4 次的上限，未提交。"
            )


def _validate_availability(
    request: BookingRequest,
    availability: list[AvailabilitySlot],
) -> None:
    relevant = [
        slot
        for slot in availability
        if slot.booking_date == request.booking_date and slot.room_id == request.room_id
    ]
    if not relevant:
        raise BookingError("所选房间在目标日期没有可读取的空档，未提交。")

    for slot in _merge_slots(relevant):
        if slot.begin_minute <= request.start_minute and request.end_minute <= slot.end_minute:
            return
    raise BookingError("所选时间没有完全落在连续空档内，未提交。")


def _merge_slots(slots: list[AvailabilitySlot]) -> list[AvailabilitySlot]:
    ordered = sorted(slots, key=lambda slot: (slot.begin_minute, slot.end_minute))
    merged: list[AvailabilitySlot] = []
    for slot in ordered:
        if not merged or slot.begin_minute > merged[-1].end_minute:
            merged.append(slot)
            continue
        previous = merged[-1]
        merged[-1] = AvailabilitySlot(
            booking_date=previous.booking_date,
            room_id=previous.room_id,
            begin_minute=previous.begin_minute,
            end_minute=max(previous.end_minute, slot.end_minute),
        )
    return merged


def parse_bookings_csv(text: str) -> list[ExistingBooking]:
    if not text.strip():
        raise BookingDataError("预订列表为空，无法确认现有预订。")

    required_time_columns = {
        "Startdatum",
        "Starttid",
        "Slutdatum",
        "Sluttid",
    }
    rows = list(csv.reader(StringIO(text.lstrip("\ufeff"))))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if required_time_columns.issubset(set(row))
        ),
        None,
    )
    if header_index is None:
        raise BookingDataError("预订列表格式无法识别，已停止以避免超限。")

    fieldnames = rows[header_index]
    data_rows = [
        values
        for values in rows[header_index + 1 :]
        if any((value or "").strip() for value in values)
    ]
    bookings: list[ExistingBooking] = []
    for row_number, values in enumerate(data_rows, start=header_index + 2):
        row = dict(zip(fieldnames, values))
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            status = (row.get("Status") or "").strip()
            if _is_cancelled_status(status):
                continue
            start = _parse_csv_datetime(
                row.get("Startdatum") or "",
                row.get("Starttid") or "",
            )
            end = _parse_csv_datetime(
                row.get("Slutdatum") or row.get("Startdatum") or "",
                row.get("Sluttid") or "",
            )
        except BookingDataError as exc:
            raise BookingDataError(
                f"预订列表第 {row_number} 行无法识别，已停止以避免超限。"
            ) from exc
        if end <= start:
            raise BookingDataError(
                f"预订列表第 {row_number} 行时间无效，已停止以避免超限。"
            )
        bookings.append(
            ExistingBooking(
                title=(row.get("Title") or "").strip(),
                room_name=(row.get("Lokalnamn") or "").strip(),
                room_id=(row.get("Rumsnummer") or "").strip(),
                start=start,
                end=end,
                status=status,
            )
        )
    return bookings


def _is_cancelled_status(status: str) -> bool:
    normalized = status.casefold()
    return any(
        marker in normalized
        for marker in ("avbok", "cancel", "inställd", "installd")
    )


def _parse_csv_datetime(date_text: str, time_text: str) -> datetime:
    normalized_date = date_text.strip()
    normalized_time = time_text.strip()
    parsed_date: date | None = None
    for date_format in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            parsed_date = datetime.strptime(normalized_date, date_format).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        raise BookingDataError("invalid date")

    parsed_time: time | None = None
    for time_format in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_time = datetime.strptime(normalized_time, time_format).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        raise BookingDataError("invalid time")
    return datetime.combine(parsed_date, parsed_time)


class _AvailabilityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.slots: list[AvailabilitySlot] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "div":
            return
        attributes = {key.casefold(): value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if not {"slotfree2", "slotfreetarget"}.issubset(classes):
            return

        try:
            booking_date = datetime.strptime(
                attributes["data-dates"],
                "%Y%m%d",
            ).date()
            room_id = attributes["data-object"]
            begin_minute = int(attributes["data-beginminute"])
        except (KeyError, ValueError):
            return

        width_match = _WIDTH_PATTERN.search(attributes.get("style", ""))
        if width_match is None:
            return
        try:
            width_percent = float(width_match.group(1))
            max_end_hour = int(float(attributes.get("data-resmaxend", "21")))
        except ValueError:
            return

        duration = width_percent * (GRID_END_MINUTE - GRID_START_MINUTE) / 100
        end_minute = min(
            begin_minute + duration,
            max_end_hour * 60,
            float(GRID_END_MINUTE),
        )
        if end_minute <= begin_minute:
            return
        self.slots.append(
            AvailabilitySlot(
                booking_date=booking_date,
                room_id=room_id,
                begin_minute=begin_minute,
                end_minute=end_minute,
            )
        )


def parse_availability_html(html: str, *, room_id: str | None = None) -> list[AvailabilitySlot]:
    parser = _AvailabilityParser()
    parser.feed(html)
    if room_id is None:
        return parser.slots
    return [slot for slot in parser.slots if slot.room_id == room_id]


def build_submission_form(request: BookingRequest, page_url: str) -> dict[str, str]:
    return {
        "kind": "reserve",
        "nocache": "4",
        "l": "sv_SE",
        "o": request.room_id,
        "aos": "",
        "dates": request.booking_date.strftime("%Y%m%d"),
        "starttime": request.start.strftime("%H:%M"),
        "endtime": request.end.strftime("%H:%M"),
        "url": page_url.split("#", 1)[0],
        "fe1": request.title,
    }


class _ReservationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.reservation_id: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if attributes.get("id") == "table0" and attributes.get("data-resid"):
            self.reservation_id = attributes["data-resid"].strip()


def parse_reservation_id(html: str) -> str | None:
    parser = _ReservationParser()
    parser.feed(html)
    return parser.reservation_id


def week_url_for_date(url: str, booking_date: date) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    monday = booking_date - timedelta(days=booking_date.weekday())
    sunday = monday + timedelta(days=6)
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "p"
    ]
    query.append(("p", f"{monday:%Y%m%d}-{sunday:%Y%m%d}"))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )

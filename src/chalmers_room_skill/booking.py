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

LIBRARY_BOOKING_URL = (
    "https://cloud.timeedit.net/chalmers/web/student/ri.html"
    "?exw=t&fe=0&h=t&objects=699.4%2C18834.4%2C18836.4%2C18837.4"
    "%2C18838.4%2C18839.4%2C18842.4%2C18843.4%2C18844.4%2C18845.4"
    "%2C18846.4%2C18847.4%2C697.4%2C698.4%2C696.4%2C444.4%2C"
    "&ox=0&part=f&rr=1&se=f&sid=5&tg=-1&type=room&types=0"
)
ED_BOOKING_URL = (
    "https://cloud.timeedit.net/chalmers/web/student/ri.html"
    "?h=t&sid=4&objects=501.4%2C502.4%2C504.4%2C505.4%2C508.4"
    "%2C509.4%2C510.4%2C511.4%2C512.4%2C513.4%2C574.4%2C575.4"
    "%2C576.4%2C577.4%2C663.4%2C664.4%2C665.4%2C666.4%2C"
    "&ox=0&types=0&fe=0&part=f&tg=-1&se=f&exw=t&rr=1"
)

LIBRARY_ROOMS_BY_NAME = {
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

ED_ROOMS_BY_NAME = {
    "EG-3207A": "501.4",
    "EG-3207B": "502.4",
    "EG-3209A": "504.4",
    "EG-3209B": "505.4",
    "EG-3211A": "508.4",
    "EG-3211B": "509.4",
    "EG-3213A": "510.4",
    "EG-3213B": "511.4",
    "EG-3215A": "512.4",
    "EG-3215B": "513.4",
    "EG-4205A": "574.4",
    "EG-4205B": "575.4",
    "EG-4207A": "576.4",
    "EG-4207B": "577.4",
    "EG-6205A": "663.4",
    "EG-6205B": "664.4",
    "EG-6207A": "665.4",
    "EG-6207B": "666.4",
}


@dataclass(frozen=True)
class BookingSource:
    key: str
    label: str
    booking_url: str
    rooms_by_name: dict[str, str]
    rolling_window_days: int
    max_bookings_per_window: int
    latest_end_minute: int
    grid_start_minute: int = 8 * 60
    grid_end_minute: int = 21 * 60

    @property
    def rooms_by_id(self) -> dict[str, str]:
        return {room_id: name for name, room_id in self.rooms_by_name.items()}


BOOKING_SOURCES = {
    "library": BookingSource(
        key="library",
        label="Chalmers 图书馆小组室",
        booking_url=LIBRARY_BOOKING_URL,
        rooms_by_name=LIBRARY_ROOMS_BY_NAME,
        rolling_window_days=28,
        max_bookings_per_window=4,
        latest_end_minute=21 * 60,
        grid_end_minute=21 * 60,
    ),
    "ed": BookingSource(
        key="ed",
        label="ED-blocket 小组会议室",
        booking_url=ED_BOOKING_URL,
        rooms_by_name=ED_ROOMS_BY_NAME,
        rolling_window_days=14,
        max_bookings_per_window=4,
        latest_end_minute=24 * 60,
        grid_end_minute=24 * 60,
    ),
}


def get_booking_source(location: str | None) -> BookingSource:
    normalized = (location or "library").strip().casefold()
    source = BOOKING_SOURCES.get(normalized)
    if source is None:
        known = "、".join(BOOKING_SOURCES)
        raise BookingError(f"未知预订入口“{location}”。可用入口：{known}")
    return source


# Backwards-compatible aliases for code using the original library-only API.
ROOMS_BY_NAME = LIBRARY_ROOMS_BY_NAME
ROOMS_BY_ID = {room_id: name for name, room_id in ROOMS_BY_NAME.items()}
LATEST_END_MINUTE = BOOKING_SOURCES["library"].latest_end_minute
ROLLING_WINDOW_DAYS = BOOKING_SOURCES["library"].rolling_window_days
MAX_BOOKINGS_PER_WINDOW = BOOKING_SOURCES["library"].max_bookings_per_window
GRID_START_MINUTE = BOOKING_SOURCES["library"].grid_start_minute
GRID_END_MINUTE = BOOKING_SOURCES["library"].grid_end_minute

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_END_TIME_PATTERN = re.compile(r"^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$")
_ROOM_ID_PATTERN = re.compile(r"^\d+\.\d+$")
_WIDTH_PATTERN = re.compile(r"(?:^|;)\s*width\s*:\s*([0-9.]+)%", re.IGNORECASE)
_TOP_PATTERN = re.compile(r"(?:^|;)\s*top\s*:\s*(-?[0-9.]+)px", re.IGNORECASE)
_HEIGHT_PATTERN = re.compile(r"(?:^|;)\s*height\s*:\s*([0-9.]+)px", re.IGNORECASE)
_OBJECT_PATTERN = re.compile(r"openObject\(\s*([^,\s]+)")
_BOOKING_TIME_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})\b"
)


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
    source: str = "library"
    ends_at_midnight: bool = False

    @property
    def start_minute(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_minute(self) -> int:
        if self.ends_at_midnight:
            return 24 * 60
        return self.end.hour * 60 + self.end.minute

    @property
    def duration_minutes(self) -> int:
        return self.end_minute - self.start_minute

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.booking_date, self.start)

    @property
    def end_at(self) -> datetime:
        end = datetime.combine(self.booking_date, self.end)
        if self.ends_at_midnight:
            return end + timedelta(days=1)
        return end

    @property
    def end_text(self) -> str:
        if self.ends_at_midnight:
            return "24:00"
        return self.end.strftime("%H:%M")


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
    location: str = "library",
    room_name: str | None = None,
    room_id: str | None = None,
) -> tuple[str, str]:
    source = get_booking_source(location)
    if bool(room_name) == bool(room_id):
        raise BookingError("请只指定房间名称或房间 ID 其中一个。")

    if room_name:
        normalized = room_name.strip()
        matching_name = next(
            (
                name
                for name in source.rooms_by_name
                if name.casefold() == normalized.casefold()
            ),
            None,
        )
        if matching_name is None:
            known = "、".join(source.rooms_by_name)
            raise BookingError(f"未知房间“{normalized}”。可用房间：{known}")
        return matching_name, source.rooms_by_name[matching_name]

    normalized_id = (room_id or "").strip()
    if not _ROOM_ID_PATTERN.fullmatch(normalized_id):
        raise BookingError("房间 ID 的格式应为数字.数字，例如 18836.4。")
    return source.rooms_by_id.get(normalized_id, normalized_id), normalized_id


def create_booking_request(
    *,
    date_text: str,
    start_text: str,
    end_text: str,
    room_name: str | None,
    room_id: str | None,
    title: str,
    location: str = "library",
) -> BookingRequest:
    if not _DATE_PATTERN.fullmatch(date_text):
        raise BookingError("日期必须使用 YYYY-MM-DD 格式，例如 2026-11-10。")
    if not _TIME_PATTERN.fullmatch(start_text) or not _END_TIME_PATTERN.fullmatch(end_text):
        raise BookingError("时间必须使用 HH:MM 格式；结束时间也可以使用 24:00。")

    try:
        booking_date = date.fromisoformat(date_text)
        start = time.fromisoformat(start_text)
        ends_at_midnight = end_text == "24:00"
        end = time.min if ends_at_midnight else time.fromisoformat(end_text)
    except ValueError as exc:
        raise BookingError("日期或时间无效。") from exc

    resolved_name, resolved_id = resolve_room(
        location=location,
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
        source=get_booking_source(location).key,
        ends_at_midnight=ends_at_midnight,
    )
    validate_request_rules(request)
    return request


def validate_request_rules(request: BookingRequest) -> None:
    source = get_booking_source(request.source)
    if request.end_minute <= request.start_minute:
        raise BookingError("结束时间必须晚于开始时间。")
    if request.start.minute % BOOKING_INCREMENT_MINUTES:
        raise BookingError("开始时间必须按 15 分钟递增。")
    if request.end_minute % BOOKING_INCREMENT_MINUTES:
        raise BookingError("结束时间必须按 15 分钟递增。")

    duration = request.duration_minutes
    if duration < MIN_BOOKING_MINUTES:
        raise BookingError("单次预订至少需要 30 分钟。")
    if duration > MAX_BOOKING_MINUTES:
        raise BookingError("单次预订不能超过 4 小时。")
    if request.end_minute > source.latest_end_minute:
        latest_hour = source.latest_end_minute // 60
        raise BookingError(f"预订必须在 {latest_hour:02d}:00 或之前结束。")


def validate_booking_plan(
    request: BookingRequest,
    existing_bookings: list[ExistingBooking],
    availability: list[AvailabilitySlot],
    *,
    now: datetime | None = None,
) -> None:
    validate_request_rules(request)
    if now is not None and request.start_at <= now:
        raise BookingError("预订开始时间必须晚于当前时间。")
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
    source = get_booking_source(request.source)
    starts = [booking.start for booking in existing_bookings] + [request.start_at]
    window = timedelta(days=source.rolling_window_days)

    for candidate_start in starts:
        count = sum(
            1 for booking_start in starts
            if candidate_start <= booking_start < candidate_start + window
        )
        includes_new_booking = candidate_start <= request.start_at < candidate_start + window
        if includes_new_booking and count > source.max_bookings_per_window:
            raise BookingError(
                f"这次预订会超过滚动 {source.rolling_window_days} 天内最多 "
                f"{source.max_bookings_per_window} 次的上限，未提交。"
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

    if normalized_time in ("24:00", "24:00:00"):
        return datetime.combine(parsed_date + timedelta(days=1), time.min)

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


def _parse_minute_of_day(time_text: str) -> int:
    if time_text in ("24:00", "24:00:00"):
        return 24 * 60
    parsed = time.fromisoformat(time_text)
    return parsed.hour * 60 + parsed.minute


@dataclass(frozen=True)
class _RawBooking:
    top: float
    height: float
    title: str


class _AvailabilityParser(HTMLParser):
    def __init__(self, source: BookingSource) -> None:
        super().__init__()
        self.source = source
        self.slots: list[AvailabilitySlot] = []
        self._div_depth = 0
        self._week_day_depth: int | None = None
        self._current_day: date | None = None
        self._current_objects: list[str] = []
        self._current_bookings: list[_RawBooking] = []
        self._row_height = 40.0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        normalized_tag = tag.casefold()

        if normalized_tag == "a" and self._current_day is not None:
            if "boxlink" in classes:
                object_match = _OBJECT_PATTERN.search(attributes.get("onclick", ""))
                if object_match is not None:
                    self._current_objects.append(object_match.group(1))
            return

        if normalized_tag != "div":
            return

        self._div_depth += 1
        if "weekDay" in classes and attributes.get("data-day"):
            if self._current_day is not None:
                self._finish_day()
            try:
                self._current_day = datetime.strptime(
                    attributes["data-day"],
                    "%Y%m%d",
                ).date()
            except ValueError:
                self._current_day = None
                self._week_day_depth = None
            else:
                self._week_day_depth = self._div_depth
                self._current_objects = []
                self._current_bookings = []
                self._row_height = 40.0
            return

        is_free_slot = {"slotfree2", "slotfreetarget"}.issubset(classes)
        if self._current_day is None:
            if is_free_slot:
                self._add_free_slot(attributes)
            return

        if is_free_slot:
            try:
                self._row_height = float(
                    attributes.get("data-resminheight", self._row_height)
                )
            except ValueError:
                pass
            return

        if "bookingDiv" in classes:
            title = attributes.get("title", "").strip()
            style = attributes.get("style", "")
            top_match = _TOP_PATTERN.search(style)
            if not title or top_match is None:
                return
            height_match = _HEIGHT_PATTERN.search(style)
            try:
                top = float(top_match.group(1))
                height = (
                    float(height_match.group(1))
                    if height_match is not None
                    else self._row_height
                )
            except ValueError:
                return
            self._current_bookings.append(
                _RawBooking(top=top, height=height, title=title)
            )

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "div":
            return
        if (
            self._current_day is not None
            and self._week_day_depth is not None
            and self._div_depth == self._week_day_depth
        ):
            self._finish_day()
        self._div_depth = max(0, self._div_depth - 1)

    def close(self) -> None:
        super().close()
        if self._current_day is not None:
            self._finish_day()

    def _add_free_slot(self, attributes: dict[str, str]) -> None:
        # Legacy free-slot markup is only used when no week-day structure exists.
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
            first_minute = int(
                float(attributes.get("data-firsthour", self.source.grid_start_minute))
            )
            max_end_hour = int(
                float(
                    attributes.get(
                        "data-resmaxend",
                        str(self.source.grid_end_minute // 60),
                    )
                )
            )
        except ValueError:
            return

        duration = width_percent * (max_end_hour * 60 - first_minute) / 100
        end_minute = min(
            begin_minute + duration,
            max_end_hour * 60,
            float(self.source.grid_end_minute),
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

    def _finish_day(self) -> None:
        day = self._current_day
        objects = self._current_objects
        raw_bookings = self._current_bookings
        self._current_day = None
        self._week_day_depth = None
        self._current_objects = []
        self._current_bookings = []
        if day is None or not objects:
            return

        busy_by_room: dict[str, list[tuple[int, int]]] = {}
        for raw in raw_bookings:
            match = _BOOKING_TIME_PATTERN.search(raw.title)
            if match is None:
                continue
            try:
                event_date = date.fromisoformat(match.group(1))
                start_minute = _parse_minute_of_day(match.group(2))
                end_minute = _parse_minute_of_day(match.group(3))
            except ValueError:
                continue
            if end_minute <= start_minute and match.group(3) == "00:00":
                end_minute = 24 * 60
            if event_date != day or end_minute <= start_minute:
                continue

            row_height = self._row_height or 40.0
            start_row = max(0, round(raw.top / row_height))
            row_count = max(1, round(raw.height / row_height))
            for room_id in objects[start_row : start_row + row_count]:
                busy_by_room.setdefault(room_id, []).append(
                    (start_minute, end_minute)
                )

        for room_id in objects:
            self.slots.extend(
                _free_intervals(
                    day,
                    room_id,
                    busy_by_room.get(room_id, []),
                    self.source.grid_start_minute,
                    self.source.grid_end_minute,
                )
            )


def _free_intervals(
    booking_date: date,
    room_id: str,
    busy: list[tuple[int, int]],
    grid_start: int,
    grid_end: int,
) -> list[AvailabilitySlot]:
    clipped = sorted(
        (max(grid_start, start), min(grid_end, end))
        for start, end in busy
        if end > grid_start and start < grid_end
    )
    merged: list[tuple[int, int]] = []
    for start, end in clipped:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    free: list[AvailabilitySlot] = []
    cursor = grid_start
    for start, end in merged:
        if cursor < start:
            free.append(
                AvailabilitySlot(
                    booking_date=booking_date,
                    room_id=room_id,
                    begin_minute=cursor,
                    end_minute=start,
                )
            )
        cursor = max(cursor, end)
    if cursor < grid_end:
        free.append(
            AvailabilitySlot(
                booking_date=booking_date,
                room_id=room_id,
                begin_minute=cursor,
                end_minute=grid_end,
            )
        )
    return free


def parse_availability_html(
    html: str,
    *,
    room_id: str | None = None,
    location: str = "library",
) -> list[AvailabilitySlot]:
    parser = _AvailabilityParser(get_booking_source(location))
    parser.feed(html)
    parser.close()
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
        "endtime": request.end_text,
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

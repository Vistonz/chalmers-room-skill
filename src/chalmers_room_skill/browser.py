from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

from .booking import (
    BookingDataError,
    BookingPlan,
    BookingRequest,
    AvailabilitySlot,
    ExistingBooking,
    build_submission_form,
    parse_availability_html,
    parse_bookings_csv,
    parse_reservation_id,
    validate_booking_plan,
    week_url_for_date,
)


BOOKING_URL = (
    "https://cloud.timeedit.net/chalmers/web/student/ri.html"
    "?exw=t&fe=0&h=t&objects=699.4%2C18834.4%2C18836.4%2C18837.4"
    "%2C18838.4%2C18839.4%2C18842.4%2C18843.4%2C18844.4%2C18845.4"
    "%2C18846.4%2C18847.4%2C697.4%2C698.4%2C696.4%2C444.4%2C"
    "&ox=0&part=f&rr=1&se=f&sid=5&tg=-1&type=room&types=0"
)
MY_BOOKINGS_URL = "https://cloud.timeedit.net/chalmers/web/student/my.html"
ORGANIZATION_URL = "https://cloud.timeedit.net/chalmers/web/"


@dataclass
class CapturedResponse:
    url: str
    status: int
    content_type: str
    body: str | None


@dataclass
class CaptureResult:
    final_url: str
    title: str
    text: str
    html: str
    responses: list[CapturedResponse]


@dataclass
class BookingResult:
    plan: BookingPlan
    submitted: bool
    reservation_id: str | None = None
    after_bookings: list[ExistingBooking] | None = None
    post_booking_error: str | None = None


class BookingSubmissionError(RuntimeError):
    """The one allowed booking submission did not return a reservation ID."""


def default_state_dir() -> Path:
    return Path.home() / ".chalmers-room-skill"


def auth_state_path(state_dir: Path | None = None) -> Path:
    return (state_dir or default_state_dir()) / "auth-state.json"


def captures_dir(state_dir: Path | None = None) -> Path:
    path = (state_dir or default_state_dir()) / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _response_is_interesting(response: Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return "json" in content_type or "timeedit" in response.url


def _read_response(response: Response) -> CapturedResponse:
    body: str | None
    try:
        body = response.text()
    except Exception:
        body = None
    return CapturedResponse(
        url=response.url,
        status=response.status,
        content_type=response.headers.get("content-type", ""),
        body=body,
    )


def _accept_cookies(page: Page) -> None:
    try:
        accept = page.get_by_role("button", name="Accept", exact=True)
        if accept.count() > 0:
            accept.first.click(timeout=2_000)
    except Exception:
        pass


def _select_student(page: Page, timeout_ms: int) -> None:
    page.goto(ORGANIZATION_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    _accept_cookies(page)

    auth_buttons = page.locator("button.auth-config-button")
    if auth_buttons.count() > 0:
        sso_button = auth_buttons.filter(has_text="Anställda och studenter")
        if sso_button.count() == 0:
            sso_button = auth_buttons.first
        sso_button.first.click(timeout=timeout_ms)
    else:
        student_role = page.get_by_text(
            "Student Schemasökningar och bokning av grupprum"
        )
        student_role.first.click(timeout=timeout_ms)

    page.wait_for_timeout(2_000)


def open_page(
    url: str,
    *,
    headless: bool,
    state_file: Path,
    on_page: Callable[[Page, BrowserContext], None],
    timeout_ms: int = 30_000,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=headless)
        context = browser.new_context(
            storage_state=str(state_file) if state_file.exists() else None,
            viewport={"width": 1440, "height": 1000},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            on_page(page, context)
        finally:
            context.close()
            browser.close()


def login(
    *,
    state_file: Path,
    url: str = BOOKING_URL,
    timeout_ms: int = 30_000,
) -> None:
    def run(page: Page, context: BrowserContext) -> None:
        _select_student(page, timeout_ms)

        print("A browser window is open.")
        print("The Chalmers SSO login has been selected.")
        print("Log in with your CID and complete any MFA.")
        print("Wait until the TimeEdit booking page is fully loaded.")
        input("Press Enter to save the session and close the browser... ")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_file))
        print(f"Saved login state locally: {state_file}")

    open_page(
        url,
        headless=False,
        state_file=state_file,
        on_page=run,
        timeout_ms=timeout_ms,
    )


def capture(
    *,
    url: str,
    state_file: Path,
    headless: bool = False,
    settle_ms: int = 5_000,
    timeout_ms: int = 30_000,
) -> CaptureResult:
    responses: list[CapturedResponse] = []
    result: dict[str, object] = {}

    def run(page: Page, context: BrowserContext) -> None:
        _select_student(page, timeout_ms)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        def handle_response(response: Response) -> None:
            if _response_is_interesting(response):
                responses.append(_read_response(response))

        page.on("response", handle_response)
        try:
            page.wait_for_function(
                "() => !document.body.innerText.includes('TE Auth')",
                timeout=settle_ms,
            )
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=settle_ms)
        except Exception:
            pass
        page.wait_for_timeout(2_000)

        result.update(
            {
                "final_url": page.url,
                "title": page.title(),
                "text": page.inner_text("body"),
                "html": page.content(),
                "responses": [asdict(response) for response in responses],
            }
        )

    open_page(
        ORGANIZATION_URL,
        headless=headless,
        state_file=state_file,
        on_page=run,
        timeout_ms=timeout_ms,
    )

    return CaptureResult(
        final_url=str(result.get("final_url", "")),
        title=str(result.get("title", "")),
        text=str(result.get("text", "")),
        html=str(result.get("html", "")),
        responses=responses,
    )


def write_capture(result: CaptureResult, path: Path) -> Path:
    payload = {
        "final_url": result.final_url,
        "title": result.title,
        "text": result.text,
        "responses": [asdict(response) for response in result.responses],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = path.with_suffix(".html")
    html_path.write_text(result.html, encoding="utf-8")
    return path


def assisted_booking(
    *,
    state_file: Path,
    url: str = BOOKING_URL,
    timeout_ms: int = 30_000,
) -> CaptureResult:
    responses: list[CapturedResponse] = []
    result: dict[str, object] = {}

    def run(page: Page, context: BrowserContext) -> None:
        _select_student(page, timeout_ms)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        def handle_response(response: Response) -> None:
            if _response_is_interesting(response):
                responses.append(_read_response(response))

        page.on("response", handle_response)
        print("The booking page is open in your browser.")
        print("Choose the room and time, then submit the booking yourself.")
        print("Keep this browser window open until the confirmation is visible.")
        input("Press Enter after the booking is complete... ")

        result.update(
            {
                "final_url": page.url,
                "title": page.title(),
                "text": page.inner_text("body"),
                "html": page.content(),
                "responses": [asdict(response) for response in responses],
            }
        )

    open_page(
        ORGANIZATION_URL,
        headless=False,
        state_file=state_file,
        on_page=run,
        timeout_ms=timeout_ms,
    )

    return CaptureResult(
        final_url=str(result.get("final_url", "")),
        title=str(result.get("title", "")),
        text=str(result.get("text", "")),
        html=str(result.get("html", "")),
        responses=responses,
    )


def _read_existing_bookings(
    page: Page,
    context: BrowserContext,
    timeout_ms: int,
) -> list[ExistingBooking]:
    page.goto(MY_BOOKINGS_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_selector(
            'a[title="CSV"]',
            state="attached",
            timeout=timeout_ms,
        )
        href = page.locator('a[title="CSV"]').first.get_attribute("href")
    except Exception as exc:
        raise BookingDataError("无法读取现有预订，已停止以避免超限。") from exc
    if not href:
        raise BookingDataError("找不到预订数据下载链接，已停止以避免超限。")

    csv_url = urljoin(page.url, href)
    response = context.request.get(csv_url, timeout=timeout_ms)
    if not response.ok:
        raise BookingDataError(
            f"读取现有预订失败（HTTP {response.status}），已停止以避免超限。"
        )
    try:
        csv_text = response.body().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BookingDataError("现有预订数据编码无法识别，已停止以避免超限。") from exc
    return parse_bookings_csv(csv_text)


def _read_availability(
    page: Page,
    request: BookingRequest,
    *,
    settle_ms: int,
    timeout_ms: int,
) -> list[AvailabilitySlot]:
    target_url = week_url_for_date(BOOKING_URL, request.booking_date)
    page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_selector("#reserveformedit", state="attached", timeout=timeout_ms)
        page.wait_for_selector(
            ".resobjectselector",
            state="attached",
            timeout=timeout_ms,
        )
    except Exception as exc:
        raise BookingDataError("无法读取房间空档，已停止以避免误订。") from exc

    try:
        page.wait_for_load_state("networkidle", timeout=settle_ms)
    except Exception:
        pass
    page.wait_for_timeout(min(settle_ms, 2_000))
    return parse_availability_html(page.content(), room_id=request.room_id)


def _request_csrf_token(
    context: BrowserContext,
    page_url: str,
    timeout_ms: int,
) -> str:
    response = context.request.post(
        page_url,
        form={"CSTTG": "gen"},
        timeout=timeout_ms,
    )
    if not response.ok:
        raise BookingSubmissionError(
            f"提交前的安全检查失败（HTTP {response.status}），未发送预订。"
        )
    token = response.text().strip()
    if not re.fullmatch(r"\d+", token):
        raise BookingSubmissionError("提交前的安全令牌无法识别，未发送预订。")
    return token


def _submit_booking_once(
    context: BrowserContext,
    page_url: str,
    request: BookingRequest,
    timeout_ms: int,
) -> tuple[str, str]:
    token = _request_csrf_token(context, page_url, timeout_ms)
    form = build_submission_form(request, page_url)
    form["CSTT"] = token
    response = context.request.post(
        page_url,
        form=form,
        timeout=timeout_ms,
    )
    try:
        body = response.text()
    except Exception as exc:
        raise BookingSubmissionError(
            f"预订请求返回 HTTP {response.status}，但响应无法读取；未重试。"
        ) from exc
    if not response.ok:
        raise BookingSubmissionError(
            f"预订请求返回 HTTP {response.status}，未重试。"
        )
    reservation_id = parse_reservation_id(body)
    if not reservation_id:
        raise BookingSubmissionError(
            "预订请求没有返回确认编号；为避免重复预订，未重试。"
        )
    return reservation_id, body


def book_room(
    request: BookingRequest,
    *,
    state_file: Path,
    submit: bool,
    headless: bool,
    settle_ms: int = 5_000,
    timeout_ms: int = 30_000,
    on_plan: Callable[[BookingPlan], None] | None = None,
) -> BookingResult:
    result: dict[str, object] = {}

    def run(page: Page, context: BrowserContext) -> None:
        _select_student(page, timeout_ms)
        existing_bookings = _read_existing_bookings(page, context, timeout_ms)
        availability = _read_availability(
            page,
            request,
            settle_ms=settle_ms,
            timeout_ms=timeout_ms,
        )
        validate_booking_plan(request, existing_bookings, availability)
        plan = BookingPlan(
            request=request,
            existing_bookings=existing_bookings,
            availability=availability,
        )
        if on_plan is not None:
            on_plan(plan)
        if not submit:
            result["booking_result"] = BookingResult(plan=plan, submitted=False)
            return

        page_url = page.url.split("#", 1)[0]
        reservation_id, _ = _submit_booking_once(
            context,
            page_url,
            request,
            timeout_ms,
        )

        after_bookings: list[ExistingBooking] | None = None
        post_booking_error: str | None = None
        try:
            after_bookings = _read_existing_bookings(page, context, timeout_ms)
        except Exception:
            post_booking_error = (
                "预订请求已返回确认编号，但提交后无法重新读取预订列表。"
            )
        result["booking_result"] = BookingResult(
            plan=plan,
            submitted=True,
            reservation_id=reservation_id,
            after_bookings=after_bookings,
            post_booking_error=post_booking_error,
        )

    open_page(
        MY_BOOKINGS_URL,
        headless=headless,
        state_file=state_file,
        on_page=run,
        timeout_ms=timeout_ms,
    )
    booking_result = result.get("booking_result")
    if not isinstance(booking_result, BookingResult):
        raise BookingDataError("预订流程没有完成，未提交。")
    return booking_result


def session_info(
    *,
    state_file: Path,
    url: str = BOOKING_URL,
    timeout_ms: int = 30_000,
) -> dict[str, object]:
    info: dict[str, object] = {}

    def run(page: Page, context: BrowserContext) -> None:
        cookies = [
            {
                "name": cookie["name"],
                "domain": cookie["domain"],
                "path": cookie["path"],
            }
            for cookie in context.cookies()
        ]
        local_storage = page.evaluate(
            """() => Object.keys(window.localStorage ?? {})"""
        )
        session_storage = page.evaluate(
            """() => Object.keys(window.sessionStorage ?? {})"""
        )
        info.update(
            {
                "final_url": page.url,
                "title": page.title(),
                "text": page.inner_text("body"),
                "cookies": cookies,
                "local_storage_keys": local_storage,
                "session_storage_keys": session_storage,
            }
        )

    open_page(
        url,
        headless=False,
        state_file=state_file,
        on_page=run,
        timeout_ms=timeout_ms,
    )
    return info


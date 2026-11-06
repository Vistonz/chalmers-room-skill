---
name: chalmers-room-booking
description: Help Chalmers students inspect availability and automatically reserve a specified library or ED-blocket group room through a locally stored browser session; use for existing bookings and explicitly confirmed reservations.
---

# Chalmers Room Booking

Use the `chalmers-room` command from this repository. It drives a real Edge window, so the user can complete Chalmers SSO and any MFA manually, then stores a local Playwright browser state.

## Workflow

- If the browser session is missing or expired, ask the user to run `chalmers-room login`. The user must complete login personally.
- Read-only inspection is safe: `chalmers-room availability`, `chalmers-room rooms`, and `chalmers-room bookings`.
- Use `--location ed` for `ED-blocket` student group rooms or `--location library` for Chalmers library group rooms. The `availability` command defaults to `ed`.
- When the user asks for the nearest available room, run `chalmers-room availability --location ed --duration-minutes <minutes> --horizon-days <days>` and present the exact room, date, time, and duration.
- Use `chalmers-room session` only for non-secret diagnostics about whether the saved login state is present.
- Do not choose a room, date, start time, end time, or title for the user. If any value is missing or ambiguous, ask before running the command.
- Run `chalmers-room book` without `--yes` first. Show the complete room, date, time, title, duration, and pre-booking summary to the user.
- Submit only after the user explicitly confirms that exact summary. Then rerun the same command with `--yes`.
- The command downloads existing bookings and live availability before submission and revalidates them. If either cannot be read reliably, do not bypass the error.
- Send at most one booking request. Never retry automatically, use multiple accounts, poll aggressively, or attempt to bypass TimeEdit limits.
- After submission, report the reservation ID and the bookings that the command reads back. If the follow-up read fails, tell the user not to repeat the request and to run `chalmers-room bookings` later.

## Data and Safety

- Browser state and captured pages are stored under `~/.chalmers-room-skill` by default.
- Never commit `auth-state.json`, captures, cookies, CID credentials, or personal booking data.
- Chalmers library rules allow a maximum of 4 bookings of up to 4 hours each in a rolling 4-week period.
- A single reservation must be 30 minutes to 4 hours, use 15-minute increments, and end no later than 21:00.
- ED-blocket rules allow a maximum of 4 bookings of up to 4 hours each in a rolling 14-day period.
- ED bookings must use the room within 30 minutes of the start time and may end no later than 24:00.
- The requested interval must fit entirely inside a continuous available slot.


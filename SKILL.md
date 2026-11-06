---
name: chalmers-room-booking
description: Help Chalmers students inspect and reserve library group rooms through a locally stored browser session; use for room availability, existing bookings, and assisted reservations.
---

# Chalmers Room Booking

Use the `chalmers-room` command from this repository. It drives a real Edge window, so the user can complete Chalmers SSO and any MFA manually, then stores a local Playwright browser state.

## Workflow

- If the browser session is missing or expired, ask the user to run `chalmers-room login`. The user must complete login personally.
- Read-only inspection is safe: `chalmers-room rooms` and `chalmers-room bookings`.
- Use `chalmers-room session` only for non-secret diagnostics about whether the saved login state is present.
- Before any reservation, run or require `chalmers-room bookings`. The `book` command does this automatically and saves the pre-booking data.
- Reservations are currently assisted, not silently automatic. Ask the user for explicit confirmation before `chalmers-room book`, then let the user submit the reservation in the browser.
- Do not retry failed bookings in a loop, use multiple accounts, or attempt to bypass TimeEdit limits.

## Data and Safety

- Browser state and captured pages are stored under `~/.chalmers-room-skill` by default.
- Never commit `auth-state.json`, captures, cookies, CID credentials, or personal booking data.
- Chalmers library rules allow a maximum of 4 bookings of up to 4 hours each in a 4-week period. Remind the user when relevant.


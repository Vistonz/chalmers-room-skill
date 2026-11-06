# Chalmers Room Booking Skill

A local, browser-session based tool for Chalmers library group-room bookings. It does not store your Chalmers password. Instead, you log in once in a real browser window and later commands reuse a locally saved Playwright browser state.

The `book` command checks your existing bookings and live room availability, prints a complete summary, and submits only when `--yes` is present. It never chooses a room, date, or time for you and never retries a booking automatically.

## Install

```bash
python -m pip install -e .
```

On Windows, the default browser channel is Microsoft Edge. If Playwright cannot find Edge, install its browser runtime:

```bash
python -m playwright install chromium
```

## Log in once

```bash
chalmers-room login
```

A browser window opens. Sign in with your Chalmers ID and complete any MFA. Return to the terminal and press Enter. The session is stored locally as `~/.chalmers-room-skill/auth-state.json`.

## Inspect existing bookings

Run this before booking:

```bash
chalmers-room bookings
```

The command saves the current bookings page and its TimeEdit network responses under `~/.chalmers-room-skill/captures`, then prints the page text.

If you need to check whether the saved login state is still valid, run:

```bash
chalmers-room session
```

The command prints cookie names and storage keys only; it never prints cookie values or tokens.

## Inspect rooms

```bash
chalmers-room rooms
```

## Automatic booking

```bash
chalmers-room book \
  --date 2026-11-10 \
  --start 13:00 \
  --end 15:00 \
  --room BIB-G134C \
  --message "Grupparbete"
```

Without `--yes`, this is a preview. The command reads your current bookings and the room's live availability, validates the request, and prints exactly what would be booked. Nothing is submitted.

After reviewing the summary, add `--yes` to the same command:

```bash
chalmers-room book \
  --date 2026-11-10 \
  --start 13:00 \
  --end 15:00 \
  --room BIB-G134C \
  --message "Grupparbete" \
  --yes
```

Before submitting, the tool rechecks the saved login, existing bookings, rolling booking limit, and availability. It sends at most one booking request. A successful TimeEdit response must include a reservation ID. The command then downloads your bookings again and displays the updated list.

You can use `--room-id` instead of `--room`:

```bash
chalmers-room book \
  --date 2026-11-10 \
  --start 13:00 \
  --end 15:00 \
  --room-id 18836.4 \
  --message "Grupparbete"
```

## Rules

- Chalmers library group rooms can be booked at most 4 times, for up to 4 hours each, during a 4-week period.
- A single reservation must be at least 30 minutes and at most 4 hours.
- Start and end times use 15-minute increments and must end by 21:00.
- The requested interval must fit entirely inside one continuous available slot.
- Existing bookings are downloaded before submission. If that data cannot be read reliably, the command stops without submitting.
- Use this project only for rooms you intend to use.
- Do not use multiple accounts, aggressive polling, or automated retries to bypass limits.

## Failure behavior

The tool deliberately fails closed. It does not submit when the login is invalid, existing bookings cannot be parsed, availability cannot be read, the rolling limit would be exceeded, or any required booking detail is missing.

If the single submission returns a reservation ID but the follow-up booking download fails, the command reports that the reservation may already exist and asks you to run `chalmers-room bookings` later. It does not submit again.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Privacy

The saved browser state and captures contain your login session and personal bookings. Keep them local. They are excluded from Git by default. Never publish `auth-state.json`, cookies, captured pages, downloaded CSV files, or terminal output containing personal bookings.

## License

MIT


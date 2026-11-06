# Chalmers Room Booking Skill

A local, browser-session based helper for Chalmers library group-room bookings. It does not store your Chalmers password. Instead, you log in once in a real browser window and later commands reuse a locally saved Playwright browser state.

This project is currently an assisted booking tool, not an unattended booking bot. It captures room availability and your existing bookings, then opens the booking page for you to submit the reservation after review.

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

## Assisted booking

```bash
chalmers-room book
```

The command first captures your existing bookings. After you press Enter, it opens the booking page. You choose the room and time and submit the reservation yourself. When you return to the terminal and press Enter, the tool saves the confirmation page and relevant network responses.

## Rules

- Chalmers library group rooms can be booked at most 4 times, for up to 4 hours each, during a 4-week period.
- A booked room must be used within 30 minutes of the start time.
- Use this project only for rooms you intend to use.
- Do not use multiple accounts, aggressive polling, or automated retries to bypass limits.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Privacy

The saved browser state and captures contain your login session and personal bookings. Keep them local. They are excluded from Git by default.

## License

MIT


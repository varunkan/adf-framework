# Countdown Timer — `countdown-timer-set-minutes`

A self-contained countdown timer web app. Set minutes and seconds, then start,
pause, and reset, with a large legible display.

## Requirements

- Python 3 (standard library only — no pip installs)

## Run

```bash
python3 server.py
```

Then open http://localhost:8000 in your browser.

To use a different port:

```bash
PORT=9000 python3 server.py
```

## Test

```bash
python3 test_app.py
```

All tests must pass with zero failures.

## API

| Method | Path                | Body                         | Description                          |
|--------|---------------------|------------------------------|--------------------------------------|
| GET    | `/`                 | —                            | Serves the frontend (index.html)     |
| GET    | `/api/timer`        | —                            | Returns current timer state          |
| POST   | `/api/timer`        | `{"minutes":2,"seconds":30}` | Set timer (minutes 0–60, seconds 0–59) → 201 |
| POST   | `/api/timer/start`  | —                            | Start countdown                      |
| POST   | `/api/timer/pause`  | —                            | Pause countdown                      |
| POST   | `/api/timer/reset`  | —                            | Reset to the last set value          |
| POST   | `/api/timer/tick`   | —                            | Decrement remaining by 1s if running |
| POST   | `/api/timer/finish` | —                            | Skip to end: complete the current cycle now (400 if already at zero) |
| PUT    | `/api/timer/presets/<name>` | `{"label":"…","seconds":120}` | Edit a custom preset's label and/or seconds (404 if unknown) |
| GET    | `/api/timer/stats/labels` | —                       | Completed-session stats grouped by label |
| GET    | `/api/timer/history.csv`  | —                       | Download completed-session history as CSV |

### State shape

```json
{ "minutes": 2, "seconds": 30, "remaining": 150, "running": false }
```

### Validation

- `minutes` must be an integer between 0 and 60.
- `seconds` must be an integer between 0 and 59.
- Missing fields or out-of-range values return `400` with an `error` message.
- Unknown routes return `404`.

## Requirement traceability

- **REQ-001** — set minutes: `POST /api/timer` accepts and stores minutes.
- **REQ-002** — seconds, start, pause: seconds stored; `start`/`pause` endpoints.
- **REQ-003** — reset, with a big display: `reset` endpoint + large display in UI.

# Countdown Timer — `countdown-timer-set-minutes`

A self-contained countdown timer web app. Set minutes and seconds, start,
pause, and reset, with a big live display. Backend is Python 3 standard
library only; frontend is a single static HTML file with vanilla JS.

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

All tests should pass with zero failures.

## API

| Method | Path                | Body                              | Description                          |
|--------|---------------------|-----------------------------------|--------------------------------------|
| GET    | `/`                 | —                                 | Serves the frontend (index.html).    |
| GET    | `/api/timer`        | —                                 | Returns current timer state.         |
| POST   | `/api/timer/set`    | `{"minutes":int,"seconds":int}`   | Sets the timer (REQ-001/002).        |
| POST   | `/api/timer/start`  | —                                 | Starts countdown (REQ-002).          |
| POST   | `/api/timer/pause`  | —                                 | Pauses countdown (REQ-002).          |
| POST   | `/api/timer/tick`   | —                                 | Decrements remaining by one second.  |
| POST   | `/api/timer/reset`  | —                                 | Resets to set duration (REQ-003).    |

### State shape

```json
{
  "minutes": 1,
  "seconds": 5,
  "remaining": 65,
  "running": false,
  "display": "01:05"
}
```

### Validation

- `minutes` must be an integer in range 0–1439.
- `seconds` must be an integer in range 0–59.
- Invalid input returns HTTP 400 with `{"error": "..."}`.
- Starting with zero remaining returns HTTP 400.
- Unknown routes return HTTP 404.

## Requirement traceability

- **REQ-001** — set minutes → `/api/timer/set`
- **REQ-002** — seconds, start, pause → `/api/timer/set`, `/api/timer/start`, `/api/timer/pause`, `/api/timer/tick`
- **REQ-003** — reset, big display → `/api/timer/reset`, large `.display` element in `index.html`

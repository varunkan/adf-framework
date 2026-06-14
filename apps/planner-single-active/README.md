# planner-single-active — URL Shortener with Single-Active Session

A self-contained web app built with Python 3 standard library only (backend)
and a single static HTML file (frontend). Implements a URL shortener plus a
**single-active** session guard (REQ-001): only one active session may hold the
lock at a time; concurrent acquire attempts are blocked.

## Requirements

- Python 3 (standard library only — no pip installs, no third-party packages)

## Run

```
python3 server.py
```

Then open http://127.0.0.1:8000 in your browser.

- Enter a URL (must start with `http://` or `https://`) and click **Shorten**.
- Copy the resulting short URL and visit it — it redirects (302) to the original.

## API

- `POST /api/shorten` — body `{"url": "https://..."}` → `200 {"short_url": ..., "code": ...}`
  - empty/invalid url → `400`
- `GET /<code>` — `302` redirect to original URL (Location header); unknown code → `404`
- `POST /api/acquire` — body `{"session_id": "..."}` → `200 {"acquired": true}` or `409` if already held (single active)
- `POST /api/release` — body `{"session_id": "..."}` → `200 {"released": true}`
- `GET /api/active` — current active holder

## Test

```
python3 test_app.py
```

All tests must pass with zero failures. The tests start the server on an
ephemeral port (port 0) in a background thread, read the real port from
`server.server_address[1]`, and use `http.client` so 302 redirects are not
auto-followed.

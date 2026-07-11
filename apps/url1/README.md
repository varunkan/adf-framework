# URL Shortener (url1)

A self-contained URL shortener web app. Paste a long URL, get a short shareable
link that 301-redirects to the original. Built with Python 3 standard library
only (backend) and a single static HTML file (frontend). No pip installs, no
frameworks, no network egress.

## Requirements

- Python 3.7+ (standard library only)

## Run

```bash
python3 server.py
```

Then open http://localhost:8000 in your browser.

The port is configurable via the `PORT` environment variable:

```bash
PORT=9000 python3 server.py
```

Data is persisted to `urls.json` next to `server.py`.

## API

### `POST /api/shorten`
Request body (JSON):
```json
{ "url": "https://example.com/very/long/path" }
```
Responses:
- `201 Created` — new short URL created
- `200 OK` — URL already shortened (returns existing code)
- `400 Bad Request` — missing body or invalid URL (must start with `http://` or `https://`)

Response body:
```json
{ "code": "b", "url": "https://example.com/very/long/path", "short_url": "http://host/b" }
```

### `GET /api/urls`
Returns all stored mappings:
```json
{ "items": [ { "code": "b", "url": "https://example.com/..." } ] }
```

### `GET /<code>`
- `301 Moved Permanently` with `Location` header pointing to the original URL
- `404 Not Found` if the code does not exist

## Test

```bash
python3 test_app.py
```

This starts the server on an ephemeral port in a background thread and exercises
the main success path (shorten → redirect), deduplication, the list endpoint,
and error cases (invalid URL, missing body, unknown code). All tests must pass
with zero failures.

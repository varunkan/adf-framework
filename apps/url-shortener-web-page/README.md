# URL Shortener Web Page

A self-contained URL shortener: enter a long URL, get a short code, and visiting
the short URL redirects to the original. Pure Python standard library backend +
single static HTML/CSS/JS frontend. No third-party packages, no build step.

## Requirements

- Python 3.7+ (standard library only)

## Run

```bash
python3 server.py
```

The server binds to the `PORT` environment variable (default `8000`):

```bash
PORT=9000 python3 server.py
```

Then open the printed URL in a browser, e.g. http://localhost:8000

## Usage

1. Paste a long `http://` or `https://` URL into the field.
2. Click **Shorten**.
3. Copy the short link (e.g. `http://localhost:8000/abc123`) and share it.
4. Visiting the short link redirects (HTTP 302) to the original URL.

Created links are listed under **Your links** and persisted to `urls.json`
next to `server.py`.

## API

| Method | Path                  | Body / Params        | Success | Errors |
|--------|-----------------------|----------------------|---------|--------|
| GET    | `/`                   | —                    | 200 HTML | — |
| POST   | `/api/shorten`        | `{"url": "https://..."}` | 201 JSON | 400 invalid input |
| POST   | `/api/shorten_bulk`   | `{"urls": [...]}`    | 200 JSON | 400 invalid input |
| GET    | `/api/expand/{code}`  | —                    | 200 JSON | 404 / 410 expired |
| GET    | `/api/stats/{code}`   | —                    | 200 JSON | 404 not found |
| GET    | `/api/list`           | `?q=&sort=&order=`   | 200 JSON | — |
| GET    | `/api/summary`        | —                    | 200 JSON | — |
| GET    | `/api/tags`           | —                    | 200 JSON | — |
| GET    | `/api/health`         | —                    | 200 JSON | — |
| GET    | `/api/export`         | —                    | 200 CSV | — |
| PUT/POST | `/api/update/{code}` | `{"url"?, "tags"?, "disabled"?}` | 200 JSON | 400 / 404 |
| POST   | `/api/disable/{code}` | —                    | 200 JSON | 404 not found |
| POST   | `/api/enable/{code}`  | —                    | 200 JSON | 404 not found |
| DELETE/POST | `/api/delete/{code}` | —               | 200 JSON | 404 not found |
| GET    | `/{code}`             | —                    | 302 redirect | 403 disabled / 404 / 410 expired |

### Tags

Any link may carry tags. Supply `tags` on `/api/shorten` (and per-item on
`/api/shorten_bulk`) as either a comma-separated string (`"work, reading"`) or a
JSON array (`["work", "reading"]`). Tags are trimmed, lowercased, de-duplicated,
and bounded to 32 chars each. Filter the list with `/api/list?tag=work`, retag a
link in place via `/api/update/{code}` with `{"tags": "..."}`, and see counts
across all links at `/api/tags`.

### Disable / enable

`POST /api/disable/{code}` parks a link without deleting it: its short URL stops
redirecting (returns **403**, `/api/expand` returns 403) and clicks are not
counted. `POST /api/enable/{code}` restores it. Disabling can also be done via
`/api/update/{code}` with `{"disabled": true}`. Disabled links still appear in
the list and are counted in `/api/summary` (`disabled_links`, and excluded from
`active_links`).

### POST /api/shorten_bulk

Shorten up to 100 URLs in one call. Each item may be a bare URL string or an
object `{"url", "alias", "expires_in", "tags"}`. The response reports per-item
results:

```json
{ "results": [ {"code": "...", "ok": true, "status": 201}, {"error": "...", "ok": false, "status": 400} ],
  "created": 1, "total": 2 }
```

### GET /api/list query params

- `q` — case-insensitive substring filter over code and URL.
- `sort` — one of `clicks`, `created`, `code`, `url`.
- `order` — `asc` (default) or `desc`.

### GET /api/export

Returns all links as CSV (`code,url,clicks,created,custom,expires_at,expired`)
with a `Content-Disposition: attachment` header for one-click download.

### POST /api/shorten

Request:
```json
{ "url": "https://example.com/very/long/path" }
```
Response (201):
```json
{
  "code": "abc123",
  "url": "https://example.com/very/long/path",
  "short_path": "/abc123",
  "short_url": "http://localhost:8000/abc123"
}
```

Validation: URL must be non-empty, ≤ 2048 chars, and start with `http://` or
`https://`. Otherwise returns 400 with `{"error": "..."}`.

## Test

```bash
python3 test_app.py
```

All tests must pass with zero failures. Tests start the server on an ephemeral
port (0) in a background thread and exercise the create → redirect → expand flow
plus validation (400) and not-found (404) error cases.

## Notes

- Short codes are generated deterministically with collision handling, so the
  same URL maps to the same code and conflicts are resolved automatically.
- The in-memory store is mirrored to `urls.json` for simple durability across
  restarts.

# Notes — `notes-where-can-note`

A tiny notes app: add a note and see the list of notes. Backend is Python
standard library only; frontend is a single static HTML file.

## Run

```bash
python3 server.py
```

The server binds to the `PORT` environment variable (default `8000`).

Open: http://localhost:8000

Override the port:

```bash
PORT=9000 python3 server.py
```

## API

- `GET /` — serves the frontend (`index.html`).
- `GET /api/notes` — returns `{"notes": [{"id": 1, "text": "..."}, ...]}` with status `200`.
- `POST /api/notes` — body `{"text": "your note"}`.
  - `201` with the created note `{"id": N, "text": "..."}` on success.
  - `400` `{"error": "..."}` if the JSON body is invalid or text is empty.
- Any other path returns `404`.

Notes are persisted to `notes_data.json` next to `server.py`.

## Test

```bash
python3 test_app.py
```

This starts the server on an ephemeral port in a background thread, exercises
the create + list success path, and asserts the validation (`400`) and
not-found (`404`) error cases. It uses an isolated test data file that is
removed afterward.

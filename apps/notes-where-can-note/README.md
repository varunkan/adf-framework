# Notes App (notes-where-can-note)

A minimal notes app: add a note and see the list of notes.
Pure Python standard library backend + single static HTML frontend.

## Requirements

- Python 3 (standard library only — no pip installs)

## Run

```bash
python3 server.py
```

Then open your browser to:

```
http://127.0.0.1:8000
```

You will see a text box. Type a note, click **Add Note** (or press Ctrl/Cmd+Enter),
and it appears in the list below. The list and count update immediately.

## API

- `GET /` — serves the frontend (index.html)
- `GET /api/notes` — returns `{"notes": [{"id":1,"text":"..."}, ...]}`
- `POST /api/notes` with JSON body `{"text": "my note"}`
  - `200` → `{"note": {"id": N, "text": "my note"}}`
  - `400` → empty text or invalid JSON

Notes are stored in memory and reset when the server restarts.

## Test

```bash
python3 test_app.py
```

All tests should pass with zero failures. The test suite starts the server on a
random free port in a background thread and exercises the API directly.

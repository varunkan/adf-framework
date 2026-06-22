#!/usr/bin/env python3
"""
ANDS Submission Portal — MVP HTTP server.

A thin shell over ``domain.py``: it serves a single-page HTML/JS UI at ``/`` and
a small JSON API for validating and storing ANDS submissions. Storage is sqlite
(stdlib). No third-party packages, no outbound network — run with:

    python3 server.py            # serves on http://127.0.0.1:8000

The real value (the four Health-Canada validation rules) lives in
``domain.validate_intake``; this module only wires it to HTTP + sqlite.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import domain

DB_PATH = "submissions.db"
RECORD_COLUMNS = (
    "id", "applicant", "drug_product", "dossier_id",
    "submission_type", "sequence", "contact_email", "created_at",
)


# ---------------------------------------------------------------------------
# Persistence (sqlite, stdlib)
# ---------------------------------------------------------------------------

class SubmissionStore:
    """Stores accepted submissions and answers the lifecycle's prior-sequence
    question. Thread-safe (the server is threaded) via a single guarded
    connection."""

    def __init__(self, db_path: str = DB_PATH):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    applicant       TEXT NOT NULL,
                    drug_product    TEXT NOT NULL,
                    dossier_id      TEXT NOT NULL,
                    submission_type TEXT NOT NULL,
                    sequence        TEXT NOT NULL,
                    contact_email   TEXT NOT NULL,
                    created_at      TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def prior_sequences(self, dossier_id: str) -> list:
        """Already-accepted sequences for a dossier (for the lifecycle check)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT sequence FROM submissions WHERE dossier_id = ? "
                "ORDER BY sequence",
                (str(dossier_id or "").strip(),),
            ).fetchall()
        return [r["sequence"] for r in rows]

    def add(self, data: dict) -> dict:
        """Insert an accepted submission and return the stored record."""
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO submissions
                    (applicant, drug_product, dossier_id, submission_type,
                     sequence, contact_email, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(data.get("applicant", "")).strip(),
                    str(data.get("drug_product", "")).strip(),
                    str(data.get("dossier_id", "")).strip(),
                    domain.MVP_SUBMISSION_TYPE,
                    str(data.get("sequence", "")).strip(),
                    str(data.get("contact_email", "")).strip(),
                    created_at,
                ),
            )
            self._conn.commit()
            new_id = cur.lastrowid
        return self.get(new_id)

    def list(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM submissions ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, submission_id: int):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

def make_handler(store: SubmissionStore):
    """Build a request handler bound to a given store (keeps it testable)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "ANDSPortal/1.0"

        # -- helpers --------------------------------------------------------
        def _send_json(self, payload, status: int = 200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status: int = 200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def log_message(self, *args):  # keep test output quiet
            pass

        # -- routing --------------------------------------------------------
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send_html(INDEX_HTML)
                return
            if path == "/api/submissions":
                self._send_json({"submissions": store.list()})
                return
            if path.startswith("/api/submissions/"):
                ident = path[len("/api/submissions/"):]
                try:
                    record = store.get(int(ident))
                except ValueError:
                    record = None
                if record is None:
                    self._send_json({"error": "submission not found"}, 404)
                else:
                    self._send_json(record)
                return
            self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/validate":
                self._handle_validate(store_record=False)
                return
            if path == "/api/submissions":
                self._handle_validate(store_record=True)
                return
            self._send_json({"error": "not found"}, 404)

        # -- core handler ---------------------------------------------------
        def _handle_validate(self, store_record: bool):
            data = self._read_json()
            prior = store.prior_sequences(data.get("dossier_id", ""))
            errors = domain.validate_intake(data, prior)
            valid = not errors
            if not store_record:
                self._send_json({"valid": valid, "errors": errors})
                return
            # /api/submissions: store only when valid.
            if not valid:
                self._send_json({"valid": False, "errors": errors}, 422)
                return
            record = store.add(data)
            self._send_json({"valid": True, "record": record}, 201)

    return Handler


# ---------------------------------------------------------------------------
# Single-page UI
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ANDS Submission Portal</title>
<style>
  :root { --ink:#1d2b3a; --line:#d7dee6; --ok:#0a7b34; --bad:#b3261e; --bg:#f4f7fb; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
         color:var(--ink); background:var(--bg); }
  header { background:#13344f; color:#fff; padding:20px 28px; }
  header h1 { margin:0; font-size:20px; }
  header p { margin:4px 0 0; opacity:.8; font-size:13px; }
  main { max-width:980px; margin:24px auto; padding:0 20px; display:grid;
         grid-template-columns:1fr 1fr; gap:24px; }
  .card { background:#fff; border:1px solid var(--line); border-radius:10px;
          padding:20px; }
  h2 { font-size:15px; margin:0 0 14px; text-transform:uppercase;
       letter-spacing:.04em; color:#4a5b6d; }
  label { display:block; font-size:13px; font-weight:600; margin:10px 0 4px; }
  input { width:100%; padding:9px 10px; border:1px solid var(--line);
          border-radius:6px; font:inherit; }
  .hint { font-size:12px; color:#6b7886; margin-top:3px; }
  .row { display:flex; gap:12px; }
  .row > div { flex:1; }
  .actions { margin-top:18px; display:flex; gap:10px; }
  button { font:inherit; font-weight:600; padding:10px 16px; border-radius:6px;
           border:1px solid transparent; cursor:pointer; }
  .primary { background:#13344f; color:#fff; }
  .ghost { background:#fff; border-color:var(--line); color:var(--ink); }
  #result { margin-top:16px; }
  .badge { display:inline-block; padding:3px 10px; border-radius:999px;
           font-size:12px; font-weight:700; }
  .badge.ok { background:#e3f5e9; color:var(--ok); }
  .badge.bad { background:#fde8e6; color:var(--bad); }
  ul.errs { margin:10px 0 0; padding-left:18px; }
  ul.errs li { color:var(--bad); margin:4px 0; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); }
  th { font-size:12px; color:#6b7886; text-transform:uppercase; }
  .empty { color:#6b7886; font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>ANDS Submission Portal</h1>
  <p>Abbreviated New Drug Submission intake &amp; eCTD sequence validation</p>
</header>
<main>
  <section class="card">
    <h2>New submission</h2>
    <form id="form">
      <label>Applicant / company name</label>
      <input name="applicant" placeholder="Acme Generics Inc.">
      <label>Drug product name</label>
      <input name="drug_product" placeholder="Metformin HCl 500 mg tablets">
      <div class="row">
        <div>
          <label>Dossier ID</label>
          <input name="dossier_id" placeholder="e123456">
          <div class="hint">lowercase 'e' + 6 or 7 digits</div>
        </div>
        <div>
          <label>Sequence</label>
          <input name="sequence" placeholder="0000">
          <div class="hint">4 digits; first must be 0000</div>
        </div>
      </div>
      <label>Submission type</label>
      <input name="submission_type" value="ANDS" readonly>
      <label>Contact email</label>
      <input name="contact_email" placeholder="ra@acme.example">
      <div class="actions">
        <button type="button" class="ghost" onclick="run('/api/validate')">Validate</button>
        <button type="button" class="primary" onclick="run('/api/submissions')">Submit</button>
      </div>
    </form>
    <div id="result"></div>
  </section>

  <section class="card">
    <h2>Accepted submissions</h2>
    <div id="list"><p class="empty">Loading…</p></div>
  </section>
</main>

<script>
function payload() {
  const f = document.getElementById('form');
  const d = {};
  for (const el of f.elements) if (el.name) d[el.name] = el.value;
  return d;
}

async function run(url) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload())
  });
  const data = await res.json();
  render(data, url);
  if (url === '/api/submissions' && data.valid) {
    document.getElementById('form').reset();
    document.querySelector('[name=submission_type]').value = 'ANDS';
    loadList();
  }
}

function render(data, url) {
  const el = document.getElementById('result');
  if (data.valid) {
    const msg = url === '/api/submissions'
      ? 'Submission accepted and stored (id ' + data.record.id + ').'
      : 'All rules pass — this submission would be accepted.';
    el.innerHTML = '<span class="badge ok">PASS</span> ' + msg;
  } else {
    let html = '<span class="badge bad">FAIL</span> ' +
               (data.errors.length) + ' rule(s) failed:<ul class="errs">';
    for (const e of data.errors) html += '<li>' + e.message + '</li>';
    el.innerHTML = html + '</ul>';
  }
}

async function loadList() {
  const res = await fetch('/api/submissions');
  const data = await res.json();
  const el = document.getElementById('list');
  if (!data.submissions.length) {
    el.innerHTML = '<p class="empty">No submissions yet.</p>';
    return;
  }
  let html = '<table><thead><tr><th>ID</th><th>Dossier</th><th>Seq</th>' +
             '<th>Drug product</th></tr></thead><tbody>';
  for (const s of data.submissions) {
    html += '<tr><td>' + s.id + '</td><td>' + s.dossier_id + '</td><td>' +
            s.sequence + '</td><td>' + s.drug_product + '</td></tr>';
  }
  el.innerHTML = html + '</tbody></table>';
}

loadList();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(host: str = "127.0.0.1", port: int = 8000, db_path: str = DB_PATH):
    store = SubmissionStore(db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"ANDS Submission Portal serving on http://{host}:{port}  (db: {db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
        store.close()


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""Countdown timer — set minutes/seconds, start, pause, reset; show remaining time.

Python 3 standard library ONLY. Run with:  python3 server.py
Serves a single-page UI at /  and a JSON API under /api/.

Domain model
------------
A timer is server-authoritative: remaining time is computed from wall-clock so
that the displayed value keeps counting down even between client polls.

States:  idle -> running -> paused -> running ... -> finished
- set(minutes, seconds): configure duration (allowed when idle/paused/finished),
  resets remaining to the full duration and status to idle.
- start():  idle/paused -> running, anchoring a deadline = now + remaining.
- pause():  running -> paused, freezing the remaining seconds.
- reset():  -> idle, remaining = configured duration.
A running timer whose deadline has passed reports status "finished", remaining 0.
"""

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DB_PATH = "data.db"
MAX_SECONDS = 99 * 60 + 59  # 99:59 display ceiling

# --------------------------------------------------------------------------- #
# Domain logic                                                                 #
# --------------------------------------------------------------------------- #


class TimerError(ValueError):
    """Raised on invalid domain operations (bad input / illegal transition)."""


def normalize_duration(minutes, seconds):
    """Validate and fold minutes/seconds into a total number of seconds."""
    try:
        minutes = int(minutes)
        seconds = int(seconds)
    except (TypeError, ValueError):
        raise TimerError("minutes and seconds must be integers")
    if minutes < 0 or seconds < 0:
        raise TimerError("minutes and seconds must be non-negative")
    if seconds > 59:
        raise TimerError("seconds must be between 0 and 59")
    total = minutes * 60 + seconds
    if total <= 0:
        raise TimerError("duration must be greater than zero")
    if total > MAX_SECONDS:
        raise TimerError("duration must not exceed 99:59")
    return total


class Timer:
    """Pure, clock-injected countdown timer.

    `deadline` is the wall-clock time (epoch seconds) at which a running timer
    hits zero. `frozen_remaining` holds remaining seconds while not running.
    Exactly one of those is authoritative depending on `status`.
    """

    def __init__(self, id=None, name="Timer", duration=60, status="idle",
                 deadline=None, frozen_remaining=None):
        self.id = id
        self.name = name
        self.duration = duration
        self.status = status
        self.deadline = deadline
        self.frozen_remaining = frozen_remaining if frozen_remaining is not None else duration

    # -- queries ---------------------------------------------------------- #
    def remaining(self, now):
        """Remaining whole seconds at wall-clock time `now`."""
        if self.status == "running":
            return max(0, int(round(self.deadline - now)))
        return max(0, int(self.frozen_remaining))

    def effective_status(self, now):
        """Status accounting for a running timer that has elapsed."""
        if self.status == "running" and self.remaining(now) <= 0:
            return "finished"
        return self.status

    # -- transitions ------------------------------------------------------ #
    def set_duration(self, minutes, seconds):
        total = normalize_duration(minutes, seconds)
        self.duration = total
        self.frozen_remaining = total
        self.deadline = None
        self.status = "idle"

    def start(self, now):
        eff = self.effective_status(now)
        if eff == "running":
            raise TimerError("timer is already running")
        remaining = self.duration if eff in ("idle", "finished") else self.frozen_remaining
        if remaining <= 0:
            raise TimerError("nothing to count down; reset or set a duration")
        self.deadline = now + remaining
        self.frozen_remaining = None
        self.status = "running"

    def pause(self, now):
        if self.effective_status(now) != "running":
            raise TimerError("timer is not running")
        self.frozen_remaining = self.remaining(now)
        self.deadline = None
        self.status = "paused"

    def reset(self, now):
        self.frozen_remaining = self.duration
        self.deadline = None
        self.status = "idle"

    def add_time(self, minutes, seconds, now):
        """Extend the countdown by a positive delta, capped at the 99:59 ceiling.

        While running, the deadline is pushed out so the clock keeps ticking;
        a running timer that already elapsed (effective "finished") restarts with
        exactly the added time. While idle/paused, the frozen remaining grows.
        """
        delta = normalize_duration(minutes, seconds)
        if self.status == "running":
            new_remaining = min(MAX_SECONDS, self.remaining(now) + delta)
            self.deadline = now + new_remaining
            self.frozen_remaining = None
        else:  # idle or paused
            self.frozen_remaining = min(MAX_SECONDS, int(self.remaining(now)) + delta)

    # -- serialization ---------------------------------------------------- #
    def to_dict(self, now):
        rem = self.remaining(now)
        return {
            "id": self.id,
            "name": self.name,
            "duration": self.duration,
            "status": self.effective_status(now),
            "remaining": rem,
            "remaining_label": "%02d:%02d" % (rem // 60, rem % 60),
            "duration_label": "%02d:%02d" % (self.duration // 60, self.duration % 60),
        }


# --------------------------------------------------------------------------- #
# Persistence                                                                  #
# --------------------------------------------------------------------------- #


class Store:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS timers (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL,
                   duration INTEGER NOT NULL,
                   status TEXT NOT NULL,
                   deadline REAL,
                   frozen_remaining REAL
               )"""
        )
        self._conn.commit()

    def _row_to_timer(self, row):
        return Timer(
            id=row["id"], name=row["name"], duration=row["duration"],
            status=row["status"], deadline=row["deadline"],
            frozen_remaining=row["frozen_remaining"],
        )

    def create(self, name, minutes, seconds):
        total = normalize_duration(minutes, seconds)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO timers (name, duration, status, deadline, frozen_remaining)"
                " VALUES (?, ?, 'idle', NULL, ?)",
                (name or "Timer", total, total),
            )
            self._conn.commit()
            return self.get(cur.lastrowid)

    def get(self, timer_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM timers WHERE id = ?", (timer_id,)
            ).fetchone()
        return self._row_to_timer(row) if row else None

    def list(self):
        with self._lock:
            rows = self._conn.execute("SELECT * FROM timers ORDER BY id").fetchall()
        return [self._row_to_timer(r) for r in rows]

    def save(self, timer):
        with self._lock:
            self._conn.execute(
                "UPDATE timers SET name=?, duration=?, status=?, deadline=?,"
                " frozen_remaining=? WHERE id=?",
                (timer.name, timer.duration, timer.status, timer.deadline,
                 timer.frozen_remaining, timer.id),
            )
            self._conn.commit()

    def delete(self, timer_id):
        with self._lock:
            cur = self._conn.execute("DELETE FROM timers WHERE id=?", (timer_id,))
            self._conn.commit()
            return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# HTTP layer                                                                   #
# --------------------------------------------------------------------------- #


def make_handler(store, clock=time.time):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default logging
            pass

        # -- helpers ------------------------------------------------------ #
        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html, status=200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise TimerError("invalid JSON body")

        def _timer_id(self, parts):
            try:
                return int(parts[2])
            except (IndexError, ValueError):
                raise TimerError("invalid timer id")

        # -- routing ------------------------------------------------------ #
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/" or path == "/index.html":
                return self._send_html(INDEX_HTML)
            if path == "/api/timers":
                now = clock()
                return self._send_json([t.to_dict(now) for t in store.list()])
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "timers":
                try:
                    tid = self._timer_id(parts)
                except TimerError as e:
                    return self._send_json({"error": str(e)}, 400)
                t = store.get(tid)
                if not t:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_json(t.to_dict(clock()))
            return self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            now = clock()
            try:
                if path == "/api/timers":
                    data = self._read_json()
                    t = store.create(
                        data.get("name", "Timer"),
                        data.get("minutes", 0),
                        data.get("seconds", 0),
                    )
                    return self._send_json(t.to_dict(now), 201)

                # /api/timers/<id>/<action>
                if len(parts) == 4 and parts[0] == "api" and parts[1] == "timers":
                    tid = self._timer_id(parts)
                    action = parts[3]
                    t = store.get(tid)
                    if not t:
                        return self._send_json({"error": "not found"}, 404)
                    if action == "set":
                        data = self._read_json()
                        t.set_duration(data.get("minutes", 0), data.get("seconds", 0))
                    elif action == "start":
                        t.start(now)
                    elif action == "pause":
                        t.pause(now)
                    elif action == "reset":
                        t.reset(now)
                    elif action == "add":
                        data = self._read_json()
                        t.add_time(data.get("minutes", 0), data.get("seconds", 0), now)
                    else:
                        return self._send_json({"error": "unknown action"}, 404)
                    store.save(t)
                    return self._send_json(t.to_dict(now))

                return self._send_json({"error": "not found"}, 404)
            except TimerError as e:
                return self._send_json({"error": str(e)}, 400)

        def do_DELETE(self):
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "timers":
                try:
                    tid = self._timer_id(parts)
                except TimerError as e:
                    return self._send_json({"error": str(e)}, 400)
                ok = store.delete(tid)
                return self._send_json({"deleted": ok}, 200 if ok else 404)
            return self._send_json({"error": "not found"}, 404)

    return Handler


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Countdown Timer</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; display: flex; min-height: 100vh;
         align-items: center; justify-content: center; }
  .card { background: #1e293b; padding: 32px 40px; border-radius: 18px;
          box-shadow: 0 20px 60px rgba(0,0,0,.45); width: min(440px, 92vw); }
  h1 { margin: 0 0 8px; font-size: 20px; font-weight: 600; }
  .display { font-variant-numeric: tabular-nums; font-weight: 700; text-align: center;
             font-size: clamp(64px, 22vw, 120px); line-height: 1.1; margin: 18px 0 6px;
             letter-spacing: 2px; }
  .display.finished { color: #f87171; animation: blink 1s steps(2) infinite; }
  .display.running { color: #4ade80; }
  @keyframes blink { 50% { opacity: .35; } }
  .status { text-align: center; text-transform: uppercase; letter-spacing: 2px;
            font-size: 12px; color: #94a3b8; margin-bottom: 18px; min-height: 16px; }
  .inputs { display: flex; gap: 10px; justify-content: center; margin-bottom: 16px; }
  .inputs label { font-size: 12px; color: #94a3b8; display: block; text-align: center; }
  .inputs input { width: 80px; font-size: 24px; text-align: center; padding: 8px;
                  border-radius: 10px; border: 1px solid #334155; background: #0f172a;
                  color: #e2e8f0; }
  .buttons { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  button { padding: 12px; font-size: 15px; font-weight: 600; border: none;
           border-radius: 10px; cursor: pointer; background: #334155; color: #e2e8f0; }
  button.primary { background: #2563eb; }
  button:disabled { opacity: .4; cursor: not-allowed; }
  .err { color: #f87171; text-align: center; min-height: 16px; font-size: 13px; margin-top: 10px; }
</style>
</head>
<body>
  <div class="card">
    <h1>Countdown Timer</h1>
    <div id="display" class="display">00:00</div>
    <div id="status" class="status"></div>
    <div class="inputs">
      <div><label for="min">Minutes</label><input id="min" type="number" min="0" max="99" value="5"></div>
      <div><label for="sec">Seconds</label><input id="sec" type="number" min="0" max="59" value="0"></div>
    </div>
    <div class="buttons">
      <button id="start" class="primary">Start</button>
      <button id="pause">Pause</button>
      <button id="reset">Reset</button>
    </div>
    <div class="buttons" style="margin-top:10px; grid-template-columns:repeat(3, 1fr);">
      <button id="add60">+1:00</button>
      <button id="add10">+0:10</button>
      <button id="set">Set Duration</button>
    </div>
    <div id="err" class="err"></div>
  </div>
<script>
let timerId = null;
let poll = null;

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

function render(t) {
  const d = document.getElementById('display');
  d.textContent = t.remaining_label;
  d.className = 'display ' + t.status;
  document.getElementById('status').textContent = t.status;
  document.getElementById('start').disabled = t.status === 'running';
  document.getElementById('pause').disabled = t.status !== 'running';
}

function setError(msg) { document.getElementById('err').textContent = msg || ''; }

async function refresh() {
  if (timerId == null) return;
  try { render(await api('GET', '/api/timers/' + timerId)); }
  catch (e) { setError(e.message); }
}

async function ensureTimer() {
  if (timerId != null) return;
  const min = +document.getElementById('min').value || 0;
  const sec = +document.getElementById('sec').value || 0;
  const t = await api('POST', '/api/timers', { name: 'Timer', minutes: min, seconds: sec });
  timerId = t.id;
  render(t);
}

async function act(action, body) {
  setError('');
  try {
    await ensureTimer();
    render(await api('POST', '/api/timers/' + timerId + '/' + action, body));
  } catch (e) { setError(e.message); }
}

document.getElementById('start').onclick = () => act('start');
document.getElementById('pause').onclick = () => act('pause');
document.getElementById('reset').onclick = () => act('reset');
document.getElementById('add60').onclick = () => act('add', { minutes: 1, seconds: 0 });
document.getElementById('add10').onclick = () => act('add', { minutes: 0, seconds: 10 });
document.getElementById('set').onclick = () => {
  const min = +document.getElementById('min').value || 0;
  const sec = +document.getElementById('sec').value || 0;
  act('set', { minutes: min, seconds: sec });
};

poll = setInterval(refresh, 250);
</script>
</body>
</html>
"""


def main(port=8000):
    store = Store()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    print("Countdown timer server running on http://127.0.0.1:%d" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main(int(os.environ.get("ADF_SMOKE_PORT") or os.environ.get("PORT") or 8000))

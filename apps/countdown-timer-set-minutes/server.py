import os
import io
import csv
import json
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import unquote, urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, 'index.html')

# Upper bound for any single timer (24h in seconds). Lets users "add time"
# well beyond the 0-60 minute set range without unbounded growth.
MAX_SECONDS = 24 * 60 * 60 - 1  # 86399

# Named quick-set presets (seconds). Keys are stable ids; label is for display.
PRESETS = [
    {'name': 'one-minute', 'label': 'One minute', 'seconds': 60},
    {'name': 'five-minutes', 'label': 'Five minutes', 'seconds': 5 * 60},
    {'name': 'ten-minutes', 'label': 'Ten minutes', 'seconds': 10 * 60},
    {'name': 'pomodoro', 'label': 'Pomodoro', 'seconds': 25 * 60},
    {'name': 'short-break', 'label': 'Short break', 'seconds': 5 * 60},
    {'name': 'long-break', 'label': 'Long break', 'seconds': 15 * 60},
]
_PRESET_BY_NAME = {p['name']: p for p in PRESETS}

# In-memory timer state with a lock for thread safety.
_lock = threading.Lock()
_state = {
    'minutes': 5,
    'seconds': 0,
    'total': 5 * 60,       # the configured duration (seconds) reset returns to
    'remaining': 5 * 60,   # remaining seconds
    'running': False,
    'label': '',
    'completed': 0,        # how many times this timer has reached zero
    'repeat': 0,           # configured interval repeats (0 = run once)
    'repeats_left': 0,     # repeats still pending for the live session
}

# Log of completed countdown sessions (most recent last).
_history = []

# User-defined quick-set presets (alongside the built-in PRESETS above).
_custom_presets = []

# Names of presets (built-in or custom) the user has pinned as favorites.
_favorites = set()

# How many times each preset (by name) has been applied. Powers usage
# analytics so the UI can surface the most-reached-for durations.
_preset_usage = {}

# Optional focus goal: a target number of completed-session seconds to reach.
# A target of 0 means no goal is set. Progress is derived from history totals.
GOAL_MAX = 100 * 60 * 60  # 100 hours — generous ceiling for a focus goal
_goal = {'target': 0}


def _clamp_int(value, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < lo or n > hi:
        return None
    return n


def format_clock(total_seconds):
    """Render seconds as mm:ss, or hh:mm:ss once an hour or more is present."""
    total_seconds = max(0, int(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return '%02d:%02d:%02d' % (hours, minutes, seconds)
    return '%02d:%02d' % (minutes, seconds)


def _snapshot():
    """Return a copy of state plus derived progress fields. Call under lock."""
    snap = dict(_state)
    total = snap['total']
    remaining = snap['remaining']
    elapsed = max(0, total - remaining)
    snap['elapsed'] = elapsed
    snap['percent'] = round(elapsed / total * 100) if total > 0 else 0
    snap['done'] = remaining == 0
    snap['formatted'] = format_clock(remaining)
    # Defensive .get: older state dicts (e.g. test resets) may omit repeat keys.
    snap['repeat'] = _state.get('repeat', 0)
    snap['repeats_left'] = _state.get('repeats_left', 0)
    return snap


def get_state():
    with _lock:
        return _snapshot()


def set_timer(minutes, seconds, label='', repeat=0):
    """Set timer minutes (0-60) and seconds (0-59).

    Optional ``repeat`` (0-99) turns the timer into an interval timer that
    auto-restarts that many additional times after reaching zero. Returns
    (state, error).
    """
    m = _clamp_int(minutes, 0, 60)
    s = _clamp_int(seconds, 0, 59)
    if m is None or s is None:
        return None, 'minutes must be 0-60 and seconds must be 0-59'
    if not isinstance(label, str):
        return None, 'label must be a string'
    r = _clamp_int(repeat, 0, 99)
    if r is None:
        return None, 'repeat must be an integer between 0 and 99'
    with _lock:
        _state['minutes'] = m
        _state['seconds'] = s
        _state['total'] = m * 60 + s
        _state['remaining'] = m * 60 + s
        _state['running'] = False
        _state['label'] = label
        _state['repeat'] = r
        _state['repeats_left'] = r
        return _snapshot(), None


def apply_preset(name):
    """Set the timer from a named preset (built-in or custom).

    Applying a preset clears any interval-repeat configuration. Returns
    (state, error).
    """
    with _lock:
        preset = _PRESET_BY_NAME.get(name)
        if preset is None:
            for c in _custom_presets:
                if c['name'] == name:
                    preset = c
                    break
        if preset is None:
            return None, 'unknown preset'
        secs = preset['seconds']
        _state['minutes'] = secs // 60
        _state['seconds'] = secs % 60
        _state['total'] = secs
        _state['remaining'] = secs
        _state['running'] = False
        _state['label'] = preset['label']
        _state['repeat'] = 0
        _state['repeats_left'] = 0
        _preset_usage[preset['name']] = _preset_usage.get(preset['name'], 0) + 1
        return _snapshot(), None


def add_time(seconds):
    """Add (or, if negative, subtract) seconds from the remaining time.

    Adding past the configured total raises total so progress stays coherent;
    subtracting cannot drop below zero. Returns (state, error).
    """
    delta = _clamp_int(seconds, -MAX_SECONDS, MAX_SECONDS)
    if delta is None or delta == 0:
        return None, 'seconds must be a non-zero integer'
    with _lock:
        new_remaining = _state['remaining'] + delta
        new_remaining = max(0, min(new_remaining, MAX_SECONDS))
        _state['remaining'] = new_remaining
        if new_remaining > _state['total']:
            _state['total'] = new_remaining
        return _snapshot(), None


def start_timer():
    with _lock:
        if _state['remaining'] > 0:
            _state['running'] = True
        return _snapshot()


def pause_timer():
    with _lock:
        _state['running'] = False
        return _snapshot()


def reset_timer():
    with _lock:
        _state['running'] = False
        _state['remaining'] = _state['total']
        return _snapshot()


def _complete_cycle():
    """Record one completed countdown cycle and handle interval repeats.

    Call under lock when the current cycle has reached its end. Forces
    remaining to zero, logs the session, and — if interval repeats remain —
    rolls straight into the next cycle (remaining -> total, still armed);
    otherwise it stops the timer.
    """
    _state['remaining'] = 0
    _state['completed'] += 1
    _history.append({
        'label': _state['label'],
        'total': _state['total'],
        'minutes': _state['minutes'],
        'seconds': _state['seconds'],
        'sequence': _state['completed'],
    })
    if _state.get('repeats_left', 0) > 0:
        # Interval timer: roll straight into the next cycle.
        _state['repeats_left'] -= 1
        _state['remaining'] = _state['total']
    else:
        _state['running'] = False


def tick():
    """Decrement remaining by one second if running. Returns state.

    On reaching zero a completed session is recorded. If interval repeats
    remain, the timer immediately restarts (remaining -> total) and keeps
    running; otherwise it stops.
    """
    with _lock:
        if _state['running'] and _state['remaining'] > 0:
            _state['remaining'] -= 1
            if _state['remaining'] <= 0:
                _complete_cycle()
        return _snapshot()


def finish_timer():
    """Skip to the end of the current cycle, completing it immediately.

    Works whether the timer is running or paused, as long as time remains.
    The cycle is recorded exactly as if it had ticked down to zero, so
    interval repeats and history stay consistent. Returns (state, error).
    """
    with _lock:
        if _state['remaining'] <= 0:
            return None, 'timer is already at zero'
        _complete_cycle()
        return _snapshot(), None


def get_history(label=None):
    """Return completed-session history, optionally filtered by label.

    With no ``label`` the full log is returned. Passing a label keeps only
    sessions logged under it; the sentinel ``'(unlabeled)'`` selects sessions
    that were completed without a label. Filtered responses also carry the
    requested ``label`` and a ``count`` of matches.
    """
    with _lock:
        completed = _state['completed']
        rows = list(_history)
    if label is None:
        return {'completed': completed, 'history': rows}
    if label == '(unlabeled)':
        filtered = [h for h in rows if not h['label']]
    else:
        filtered = [h for h in rows if h['label'] == label]
    return {'completed': completed, 'history': filtered,
            'label': label, 'count': len(filtered)}


def _goal_snapshot():
    """Compute focus-goal progress from completed-session totals.

    Call under ``_lock``. ``achieved`` is the summed duration of every logged
    session, so clearing history naturally resets progress.
    """
    target = _goal['target']
    achieved = sum(h['total'] for h in _history)
    remaining = max(0, target - achieved) if target > 0 else 0
    percent = round(achieved / target * 100) if target > 0 else 0
    return {
        'target': target,
        'target_formatted': format_clock(target),
        'achieved': achieved,
        'achieved_formatted': format_clock(achieved),
        'remaining': remaining,
        'remaining_formatted': format_clock(remaining),
        'percent': percent,
        'met': target > 0 and achieved >= target,
    }


def get_goal():
    with _lock:
        return _goal_snapshot()


def set_goal(seconds):
    """Set the focus goal to a target of completed seconds. Returns (goal, error)."""
    secs = _clamp_int(seconds, 1, GOAL_MAX)
    if secs is None:
        return None, 'seconds must be an integer between 1 and %d' % GOAL_MAX
    with _lock:
        _goal['target'] = secs
        return _goal_snapshot(), None


def clear_goal():
    """Remove the focus goal (target -> 0). Returns the cleared goal snapshot."""
    with _lock:
        _goal['target'] = 0
        return _goal_snapshot()


def clear_history():
    """Forget all recorded completed sessions and reset the completed counter.

    The live timer (remaining/running/total) is left untouched. Returns the
    emptied history payload so callers can render the cleared state directly.
    """
    with _lock:
        _history.clear()
        _state['completed'] = 0
        return {'completed': 0, 'history': []}


def delete_history_entry(sequence):
    """Remove a single completed-session record by its sequence number.

    ``completed`` is a lifetime counter (how many cycles have ever finished)
    and is intentionally left untouched; only the retained history shrinks, so
    stats and goal progress — which derive from the kept records — drop that
    session's contribution. Returns (deleted_row, error).
    """
    seq = _clamp_int(sequence, 1, 10 ** 9)
    if seq is None:
        return None, 'sequence must be a positive integer'
    with _lock:
        for i, h in enumerate(_history):
            if h['sequence'] == seq:
                return _history.pop(i), None
        return None, 'unknown session'


def relabel_history_entry(sequence, label):
    """Change the label of a single completed-session record.

    The new label flows through to label stats, history filters and CSV export
    since those all read the live history. Returns (updated_row, error).
    """
    seq = _clamp_int(sequence, 1, 10 ** 9)
    if seq is None:
        return None, 'sequence must be a positive integer'
    if not isinstance(label, str):
        return None, 'label must be a string'
    label = label.strip()
    with _lock:
        for h in _history:
            if h['sequence'] == seq:
                h['label'] = label
                return dict(h), None
        return None, 'unknown session'


def _is_known_preset(name):
    """True if ``name`` matches a built-in or custom preset. Call under lock."""
    if name in _PRESET_BY_NAME:
        return True
    return any(c['name'] == name for c in _custom_presets)


def toggle_favorite(name):
    """Pin or unpin a preset (built-in or custom) as a favorite.

    Toggling is idempotent per call: favoriting an already-favorite preset
    unpins it. Returns ({'name', 'favorite'}, error).
    """
    with _lock:
        if not _is_known_preset(name):
            return None, 'unknown preset'
        if name in _favorites:
            _favorites.discard(name)
            favorite = False
        else:
            _favorites.add(name)
            favorite = True
        return {'name': name, 'favorite': favorite}, None


def favorite_presets():
    """Return only the presets currently marked favorite, in list order."""
    return [p for p in list_presets() if p['favorite']]


def list_presets():
    """Return built-in presets followed by any user-defined custom presets.

    Each entry carries a ``custom`` flag so the UI can offer deletion only for
    user-defined ones.
    """
    with _lock:
        builtin = [dict(p, custom=False, applied=_preset_usage.get(p['name'], 0),
                        favorite=p['name'] in _favorites)
                   for p in PRESETS]
        custom = [dict(p, custom=True, applied=_preset_usage.get(p['name'], 0),
                       favorite=p['name'] in _favorites)
                  for p in _custom_presets]
        return builtin + custom


def popular_presets():
    """Presets ordered by how often they have been applied (descending).

    Ties break alphabetically by name. Every preset is included; ones never
    applied report ``applied`` 0 and sort to the end.
    """
    presets = list_presets()
    presets.sort(key=lambda p: (-p['applied'], p['name']))
    return presets


def add_custom_preset(name, label, seconds):
    """Create a user-defined quick-set preset. Returns (preset, error)."""
    if not isinstance(name, str) or not name.strip():
        return None, 'name is required'
    name = name.strip()
    if name in _PRESET_BY_NAME:
        return None, 'name conflicts with a built-in preset'
    secs = _clamp_int(seconds, 1, MAX_SECONDS)
    if secs is None:
        return None, 'seconds must be an integer between 1 and %d' % MAX_SECONDS
    if not isinstance(label, str) or not label.strip():
        label = name
    else:
        label = label.strip()
    with _lock:
        for p in _custom_presets:
            if p['name'] == name:
                return None, 'a custom preset with that name already exists'
        preset = {'name': name, 'label': label, 'seconds': secs}
        _custom_presets.append(preset)
        return dict(preset, custom=True), None


def delete_custom_preset(name):
    """Remove a user-defined preset by name. Returns (ok, error)."""
    with _lock:
        for i, p in enumerate(_custom_presets):
            if p['name'] == name:
                _custom_presets.pop(i)
                return True, None
        return False, 'unknown custom preset'


def update_custom_preset(name, label=None, seconds=None):
    """Edit a user-defined preset in place. Returns (preset, error).

    Only the provided fields change; passing ``seconds=None``/``label=None``
    leaves that field untouched. Built-in presets cannot be edited.
    """
    if seconds is None and label is None:
        return None, 'provide label and/or seconds to update'
    new_seconds = None
    if seconds is not None:
        new_seconds = _clamp_int(seconds, 1, MAX_SECONDS)
        if new_seconds is None:
            return None, 'seconds must be an integer between 1 and %d' % MAX_SECONDS
    new_label = None
    if label is not None:
        if not isinstance(label, str) or not label.strip():
            return None, 'label must be a non-empty string'
        new_label = label.strip()
    with _lock:
        for p in _custom_presets:
            if p['name'] == name:
                if new_seconds is not None:
                    p['seconds'] = new_seconds
                if new_label is not None:
                    p['label'] = new_label
                return dict(p, custom=True), None
        return None, 'unknown custom preset'


def get_label_stats():
    """Aggregate completed sessions grouped by label.

    Sessions logged without a label are grouped under '(unlabeled)'. Each
    group reports its session count and total/longest/average durations.
    Groups are ordered by total time spent (descending).
    """
    with _lock:
        groups = {}
        for h in _history:
            key = h['label'] if h['label'] else '(unlabeled)'
            g = groups.setdefault(key, [])
            g.append(h['total'])
    out = []
    for label, totals in groups.items():
        sessions = len(totals)
        total_seconds = sum(totals)
        longest = max(totals)
        average = round(total_seconds / sessions)
        out.append({
            'label': label,
            'sessions': sessions,
            'total_seconds': total_seconds,
            'total_formatted': format_clock(total_seconds),
            'longest_seconds': longest,
            'longest_formatted': format_clock(longest),
            'average_seconds': average,
            'average_formatted': format_clock(average),
        })
    out.sort(key=lambda g: g['total_seconds'], reverse=True)
    return {'labels': out}


def history_csv():
    """Render the completed-session history as CSV text.

    Columns: sequence, label, total_seconds, formatted, minutes, seconds.
    Always emits the header row so an empty history is still a valid file.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['sequence', 'label', 'total_seconds', 'formatted',
                     'minutes', 'seconds'])
    with _lock:
        rows = list(_history)
    for h in rows:
        writer.writerow([
            h['sequence'], h['label'], h['total'],
            format_clock(h['total']), h['minutes'], h['seconds'],
        ])
    return buf.getvalue()


def _median(values):
    """Median of a list of ints, rounded for the even case. 0 when empty."""
    if not values:
        return 0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2)


def get_stats():
    """Aggregate metrics over all recorded completed sessions."""
    with _lock:
        totals = [h['total'] for h in _history]
        sessions = len(totals)
        total_seconds = sum(totals)
        longest = max(totals) if totals else 0
        shortest = min(totals) if totals else 0
        average = round(total_seconds / sessions) if sessions else 0
        median = _median(totals)
        return {
            'completed': _state['completed'],
            'sessions': sessions,
            'total_seconds': total_seconds,
            'total_formatted': format_clock(total_seconds),
            'longest_seconds': longest,
            'longest_formatted': format_clock(longest),
            'shortest_seconds': shortest,
            'shortest_formatted': format_clock(shortest),
            'average_seconds': average,
            'average_formatted': format_clock(average),
            'median_seconds': median,
            'median_formatted': format_clock(median),
        }


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_csv(self, status, text, filename):
        body = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition',
                         'attachment; filename="%s"' % filename)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == '/' or route == '/index.html':
            try:
                with open(INDEX_PATH, 'r', encoding='utf-8') as f:
                    html = f.read()
            except OSError:
                self._send_html(500, '<h1>index.html not found</h1>')
                return
            self._send_html(200, html)
            return

        if route == '/api/timer':
            self._send_json(200, get_state())
            return

        if route == '/api/timer/presets':
            self._send_json(200, {'presets': list_presets()})
            return

        if route == '/api/timer/presets/popular':
            self._send_json(200, {'presets': popular_presets()})
            return

        if route == '/api/timer/presets/favorites':
            self._send_json(200, {'presets': favorite_presets()})
            return

        if route == '/api/timer/history':
            label = parse_qs(parsed.query).get('label', [None])[0]
            self._send_json(200, get_history(label))
            return

        if route == '/api/timer/goal':
            self._send_json(200, get_goal())
            return

        if route == '/api/timer/stats':
            self._send_json(200, get_stats())
            return

        if route == '/api/timer/stats/labels':
            self._send_json(200, get_label_stats())
            return

        if route == '/api/timer/history.csv':
            self._send_csv(200, history_csv(), 'timer-history.csv')
            return

        self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path == '/api/timer':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'minutes' not in body or 'seconds' not in body:
                self._send_json(400, {'error': 'minutes and seconds are required'})
                return
            state, err = set_timer(
                body.get('minutes'), body.get('seconds'),
                body.get('label', ''), body.get('repeat', 0))
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(201, state)
            return

        if self.path == '/api/timer/presets':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'name' not in body or 'seconds' not in body:
                self._send_json(400, {'error': 'name and seconds are required'})
                return
            preset, err = add_custom_preset(
                body.get('name'), body.get('label', ''), body.get('seconds'))
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(201, preset)
            return

        if self.path == '/api/timer/preset':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'name' not in body:
                self._send_json(400, {'error': 'name is required'})
                return
            state, err = apply_preset(body.get('name'))
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(200, state)
            return

        if self.path == '/api/timer/add':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'seconds' not in body:
                self._send_json(400, {'error': 'seconds is required'})
                return
            state, err = add_time(body.get('seconds'))
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(200, state)
            return

        if self.path == '/api/timer/goal':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'seconds' not in body:
                self._send_json(400, {'error': 'seconds is required'})
                return
            goal, err = set_goal(body.get('seconds'))
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(201, goal)
            return

        if self.path == '/api/timer/start':
            self._send_json(200, start_timer())
            return

        if self.path == '/api/timer/pause':
            self._send_json(200, pause_timer())
            return

        if self.path == '/api/timer/reset':
            self._send_json(200, reset_timer())
            return

        if self.path == '/api/timer/tick':
            self._send_json(200, tick())
            return

        if self.path == '/api/timer/finish':
            state, err = finish_timer()
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(200, state)
            return

        fav_prefix = '/api/timer/presets/'
        fav_suffix = '/favorite'
        if self.path.startswith(fav_prefix) and self.path.endswith(fav_suffix):
            name = unquote(self.path[len(fav_prefix):-len(fav_suffix)])
            result, err = toggle_favorite(name)
            if err:
                self._send_json(404, {'error': err})
                return
            self._send_json(200, result)
            return

        self._send_json(404, {'error': 'not found'})

    def do_PUT(self):
        hist_prefix = '/api/timer/history/'
        if self.path.startswith(hist_prefix):
            seq = unquote(self.path[len(hist_prefix):])
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'label' not in body:
                self._send_json(400, {'error': 'label is required'})
                return
            row, err = relabel_history_entry(seq, body.get('label'))
            if err:
                status = 404 if err == 'unknown session' else 400
                self._send_json(status, {'error': err})
                return
            self._send_json(200, row)
            return

        prefix = '/api/timer/presets/'
        if self.path.startswith(prefix):
            name = unquote(self.path[len(prefix):])
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            preset, err = update_custom_preset(
                name, body.get('label'), body.get('seconds'))
            if err:
                status = 404 if err == 'unknown custom preset' else 400
                self._send_json(status, {'error': err})
                return
            self._send_json(200, preset)
            return

        self._send_json(404, {'error': 'not found'})

    def do_DELETE(self):
        if self.path == '/api/timer/history':
            self._send_json(200, clear_history())
            return

        hist_prefix = '/api/timer/history/'
        if self.path.startswith(hist_prefix):
            seq = unquote(self.path[len(hist_prefix):])
            row, err = delete_history_entry(seq)
            if err:
                status = 404 if err == 'unknown session' else 400
                self._send_json(status, {'error': err})
                return
            self._send_json(200, {'deleted': row['sequence']})
            return

        if self.path == '/api/timer/goal':
            self._send_json(200, clear_goal())
            return

        prefix = '/api/timer/presets/'
        if self.path.startswith(prefix):
            name = unquote(self.path[len(prefix):])
            ok, err = delete_custom_preset(name)
            if not ok:
                self._send_json(404, {'error': err})
                return
            self._send_json(200, {'deleted': name})
            return

        self._send_json(404, {'error': 'not found'})


class _Server(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(port=0):
    return _Server(('', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print('Server ready on port %d (http://localhost:%d)' % (server.server_address[1], server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

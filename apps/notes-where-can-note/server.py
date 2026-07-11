import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

import domain

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'notes_data.json')
INDEX_FILE = os.path.join(BASE_DIR, 'index.html')

_lock = threading.Lock()


def _now():
    """Current epoch seconds as an int (monotonic-friendly timestamps)."""
    return int(time.time())


def _load_notes():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get('notes', []), data.get('next_id', 1)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return [], 1


def _save_notes(notes, next_id):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'notes': notes, 'next_id': next_id}, f, indent=2)


def _find_note(notes, note_id):
    for n in notes:
        if n.get('id') == note_id:
            return n
    return None


def _filter_notes(notes, query):
    """Case-insensitive substring filter over note text. Empty query == all.

    Retained for backward compatibility; richer querying lives in domain.py.
    """
    if not query:
        return notes
    q = query.strip().lower()
    if not q:
        return notes
    return [n for n in notes if q in str(n.get('text', '')).lower()]


def _archived_mode(raw):
    """Map the ?archived= query value to a domain filter mode.

    'true'/'1'/'only' -> archived-only, 'all' -> both, anything else -> active.
    """
    val = (raw or '').strip().lower()
    if val in ('true', '1', 'only', 'yes'):
        return 'only'
    if val == 'all':
        return 'all'
    return 'active'


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
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
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            return None

    def _note_id_from_path(self, path):
        """Parse '/api/notes/<id>' -> int id, or None if not that shape/invalid."""
        prefix = '/api/notes/'
        if not path.startswith(prefix):
            return None
        tail = path[len(prefix):]
        if not tail or '/' in tail:
            return None
        try:
            return int(tail)
        except ValueError:
            return None

    def _note_id_from_action(self, path, action):
        """Parse '/api/notes/<id>/<action>' -> int id, or None if it doesn't match."""
        prefix = '/api/notes/'
        suffix = '/' + action
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None
        tail = path[len(prefix):-len(suffix)]
        if not tail or '/' in tail:
            return None
        try:
            return int(tail)
        except ValueError:
            return None

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path

        if path == '/' or path == '/index.html':
            try:
                with open(INDEX_FILE, 'rb') as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_error(404, 'index.html not found')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/api/notes':
            qs = parse_qs(parts.query)
            query = qs.get('q', [''])[0]
            tag = qs.get('tag', [''])[0]
            archived = _archived_mode(qs.get('archived', [''])[0])
            with _lock:
                notes, _ = _load_notes()
            visible = domain.filter_notes(notes, query=query, tag=tag, archived=archived)
            self._send_json({'notes': domain.sort_notes(visible)})
            return

        if path == '/api/tags':
            with _lock:
                notes, _ = _load_notes()
            self._send_json({'tags': domain.collect_tags(notes)})
            return

        if path == '/api/colors':
            self._send_json({'colors': list(domain.NOTE_COLORS)})
            return

        if path == '/api/stats':
            with _lock:
                notes, _ = _load_notes()
            self._send_json(domain.compute_stats(notes))
            return

        if path == '/api/export':
            with _lock:
                notes, _ = _load_notes()
            self._send_json(domain.export_bundle(domain.sort_notes(notes), _now()))
            return

        # GET /api/notes/<id> — fetch a single note
        note_id = self._note_id_from_path(path)
        if note_id is not None:
            with _lock:
                notes, _ = _load_notes()
                note = _find_note(notes, note_id)
            if note is None:
                self._send_json({'error': 'note not found'}, 404)
                return
            self._send_json(note)
            return

        self._send_json({'error': 'not found'}, 404)

    def do_POST(self):
        parts = urlsplit(self.path)

        # POST /api/import — merge an export bundle back in (counterpart of export)
        if parts.path == '/api/import':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json({'error': 'invalid JSON body'}, 400)
                return
            try:
                ts = _now()
                with _lock:
                    notes, next_id = _load_notes()
                    merged, next_id, imported = domain.import_notes(
                        notes, body, next_id, ts)
                    _save_notes(merged, next_id)
            except domain.ValidationError as exc:
                self._send_json({'error': str(exc)}, 400)
                return
            self._send_json({'imported': imported, 'total': len(merged)}, 201)
            return

        # POST /api/tags/rename — rename or remove a tag across every note
        if parts.path == '/api/tags/rename':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json({'error': 'invalid JSON body'}, 400)
                return
            try:
                ts = _now()
                with _lock:
                    notes, next_id = _load_notes()
                    renamed = domain.rename_tag(
                        notes, body.get('old', ''), body.get('new', ''), ts)
                    _save_notes(notes, next_id)
            except domain.ValidationError as exc:
                self._send_json({'error': str(exc)}, 400)
                return
            self._send_json({'renamed': renamed})
            return

        # POST /api/notes/<id>/duplicate — clone an existing note
        dup_id = self._note_id_from_action(parts.path, 'duplicate')
        if dup_id is not None:
            try:
                ts = _now()
                with _lock:
                    notes, next_id = _load_notes()
                    src = _find_note(notes, dup_id)
                    if src is None:
                        self._send_json({'error': 'note not found'}, 404)
                        return
                    copy = domain.duplicate_note(src, next_id, ts)
                    notes.append(copy)
                    next_id += 1
                    _save_notes(notes, next_id)
            except domain.ValidationError as exc:
                self._send_json({'error': str(exc)}, 400)
                return
            self._send_json(copy, 201)
            return

        if parts.path == '/api/notes':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json({'error': 'invalid JSON body'}, 400)
                return
            try:
                ts = _now()
                with _lock:
                    notes, next_id = _load_notes()
                    note = domain.make_note(next_id, body.get('text', ''),
                                            body.get('tags'), ts,
                                            color=body.get('color'))
                    notes.append(note)
                    next_id += 1
                    _save_notes(notes, next_id)
            except domain.ValidationError as exc:
                self._send_json({'error': str(exc)}, 400)
                return
            self._send_json(note, 201)
            return

        self._send_json({'error': 'not found'}, 404)

    def do_PUT(self):
        parts = urlsplit(self.path)
        note_id = self._note_id_from_path(parts.path)
        if note_id is None:
            self._send_json({'error': 'not found'}, 404)
            return
        body = self._read_body()
        if body is None or not isinstance(body, dict):
            self._send_json({'error': 'invalid JSON body'}, 400)
            return
        # A bare PUT with no recognized field is a no-op request; treat as
        # invalid so callers don't silently think they updated something.
        if not any(k in body for k in ('text', 'tags', 'pinned', 'archived', 'color')):
            self._send_json({'error': 'note text is required'}, 400)
            return
        with _lock:
            notes, next_id = _load_notes()
            note = _find_note(notes, note_id)
            if note is None:
                self._send_json({'error': 'note not found'}, 404)
                return
            try:
                domain.apply_update(note, body, _now())
            except domain.ValidationError as exc:
                self._send_json({'error': str(exc)}, 400)
                return
            _save_notes(notes, next_id)
            updated = dict(note)
        self._send_json(updated)

    def do_DELETE(self):
        parts = urlsplit(self.path)
        note_id = self._note_id_from_path(parts.path)
        if note_id is None:
            self._send_json({'error': 'not found'}, 404)
            return
        with _lock:
            notes, next_id = _load_notes()
            note = _find_note(notes, note_id)
            if note is None:
                self._send_json({'error': 'note not found'}, 404)
                return
            notes = [n for n in notes if n.get('id') != note_id]
            _save_notes(notes, next_id)
        self._send_json({'deleted': note_id})


def make_server(port=0):
    return ThreadingHTTPServer(('0.0.0.0', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print(f'Notes app ready on http://0.0.0.0:{port}')
    server.serve_forever()

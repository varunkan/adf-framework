import os
import re
import io
import csv
import json
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'urls.json')
INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')

_lock = threading.Lock()

BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Aliases must be URL-path safe and may not collide with reserved routes.
ALIAS_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
RESERVED_CODES = {'api', 'index.html', 'index', 'favicon.ico', ''}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm_tags(value):
    """Coerce an arbitrary tags input into a clean, de-duplicated list.

    Accepts a list of strings or a comma-separated string. Each tag is trimmed,
    lowercased, and bounded to 32 chars; blanks are dropped and order of first
    appearance is preserved. Anything else yields an empty list.
    """
    if value is None or value == '':
        return []
    if isinstance(value, str):
        parts = value.split(',')
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        return []
    out = []
    for p in parts:
        if not isinstance(p, str):
            continue
        t = p.strip().lower()[:32]
        if t and t not in out:
            out.append(t)
    return out


# Cap on how many click timestamps we retain per link, so an extremely
# popular link cannot grow the store without bound.
CLICK_LOG_CAP = 50


def _coerce_max_clicks(value):
    """Coerce a stored max_clicks into a positive int or None."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n > 0 else None


def _coerce_click_log(value):
    """Coerce a stored click log into a bounded list of ISO strings."""
    if not isinstance(value, list):
        return []
    out = [v for v in value if isinstance(v, str) and v]
    return out[-CLICK_LOG_CAP:]


def _normalize_entry(value):
    """Coerce a stored value into the canonical metadata dict.

    Older stores (and older tests) used a bare URL string per code; we keep
    reading those transparently so existing data and behavior are preserved.
    """
    if isinstance(value, str):
        return {'url': value, 'clicks': 0, 'created': None,
                'custom': False, 'expires_at': None, 'last_clicked': None,
                'tags': [], 'disabled': False, 'max_clicks': None,
                'click_log': []}
    if isinstance(value, dict) and isinstance(value.get('url'), str):
        return {
            'url': value['url'],
            'clicks': int(value.get('clicks') or 0),
            'created': value.get('created'),
            'custom': bool(value.get('custom', False)),
            'expires_at': value.get('expires_at'),
            'last_clicked': value.get('last_clicked'),
            'tags': _norm_tags(value.get('tags')),
            'disabled': bool(value.get('disabled', False)),
            'max_clicks': _coerce_max_clicks(value.get('max_clicks')),
            'click_log': _coerce_click_log(value.get('click_log')),
        }
    return None


def _parse_iso(value):
    """Parse an ISO-8601 timestamp, returning a tz-aware UTC datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_expired(entry):
    """True when the entry carries an expiry that is now in the past."""
    if not isinstance(entry, dict):
        return False
    dt = _parse_iso(entry.get('expires_at'))
    if dt is None:
        return False
    return datetime.now(timezone.utc) >= dt


def _is_exhausted(entry):
    """True when the entry has a click cap that has been reached."""
    if not isinstance(entry, dict):
        return False
    cap = _coerce_max_clicks(entry.get('max_clicks'))
    if cap is None:
        return False
    return int(entry.get('clicks') or 0) >= cap


def _load_store():
    try:
        with open(STORE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                out = {}
                for code, value in data.items():
                    entry = _normalize_entry(value)
                    if entry is not None:
                        out[code] = entry
                return out
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def _save_store(store):
    try:
        with open(STORE_FILE, 'w', encoding='utf-8') as f:
            json.dump(store, f)
    except OSError:
        pass


# in-memory store loaded from disk: {code: {url, clicks, created, custom}}
STORE = _load_store()


def _entry_url(code):
    """Return the destination URL for a code, tolerating legacy string values."""
    entry = STORE.get(code)
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry
    return entry.get('url')


def _public_entry(code):
    """Shape a store entry for JSON responses, normalizing legacy values."""
    entry = _normalize_entry(STORE.get(code))
    if entry is None:
        return None
    return {
        'code': code,
        'url': entry['url'],
        'clicks': entry['clicks'],
        'created': entry['created'],
        'custom': entry['custom'],
        'expires_at': entry['expires_at'],
        'last_clicked': entry['last_clicked'],
        'expired': _is_expired(entry),
        'tags': entry['tags'],
        'disabled': entry['disabled'],
        'max_clicks': entry['max_clicks'],
        'exhausted': _is_exhausted(entry),
    }


def _encode_base62(n):
    if n == 0:
        return BASE62[0]
    s = []
    while n > 0:
        n, r = divmod(n, 62)
        s.append(BASE62[r])
    return ''.join(reversed(s))


def _gen_code(url):
    """Deterministic, collision-aware short code generator."""
    h = 0
    for ch in url:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFFFFFF
    salt = 0
    while True:
        candidate = _encode_base62((h + salt * 1000003) & 0xFFFFFFFFFFFF)[:7]
        if not candidate:
            candidate = BASE62[0]
        existing = _entry_url(candidate)
        if existing is None:
            return candidate
        if existing == url:
            return candidate
        salt += 1


def _is_valid_url(url):
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False
    if len(url) > 2048:
        return False
    return url.startswith('http://') or url.startswith('https://')


def _is_valid_alias(alias):
    if not isinstance(alias, str):
        return False
    if alias in RESERVED_CODES:
        return False
    return bool(ALIAS_RE.match(alias))


# Upper bound on a link's lifetime: 10 years in seconds.
MAX_EXPIRES_IN = 10 * 365 * 24 * 3600


def _parse_expires_in(value):
    """Validate an optional expires_in (seconds from now).

    Returns (ok, seconds_or_None). A missing/blank value is valid and yields
    None (never expires). Non-integer, non-positive, or absurdly large values
    are rejected so the link lifetime stays sane.
    """
    if value is None or value == '':
        return True, None
    if isinstance(value, bool):
        return False, None
    try:
        secs = int(value)
    except (ValueError, TypeError):
        return False, None
    if secs <= 0 or secs > MAX_EXPIRES_IN:
        return False, None
    return True, secs


# Upper bound on a link's click cap, to keep the value sane.
MAX_MAX_CLICKS = 10 ** 9


def _parse_max_clicks(value):
    """Validate an optional max_clicks (a positive click cap).

    Returns (ok, cap_or_None). A missing/blank value is valid and yields None
    (unlimited). Non-integer, non-positive, or absurdly large values are
    rejected so the cap stays sane.
    """
    if value is None or value == '':
        return True, None
    if isinstance(value, bool):
        return False, None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return False, None
    if n <= 0 or n > MAX_MAX_CLICKS:
        return False, None
    return True, n


def _parse_nonneg_int(value):
    """Parse a non-negative int from a query-string value, else None."""
    if value is None or value == '':
        return None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n >= 0 else None


def _create_entry(url, alias, raw_expires, raw_tags=None, raw_max_clicks=None):
    """Core create logic shared by single and bulk shorten.

    Returns (status, payload). On success status is 201 and payload carries the
    new code plus its public metadata; on failure status is 4xx and payload
    carries an ``error``. ``short_url`` (which depends on the request Host) is
    layered on by the handler, not here, so this stays transport-agnostic.
    """
    if not _is_valid_url(url):
        return 400, {'error': 'invalid url; must be http:// or https:// and non-empty'}
    url = url.strip()
    if alias is not None and alias != '':
        if not _is_valid_alias(alias):
            return 400, {'error': 'invalid alias; use 1-32 letters, digits, _ or -'}
    ok, expires_secs = _parse_expires_in(raw_expires)
    if not ok:
        return 400, {'error': 'invalid expires_in; use a positive number of seconds'}
    ok, max_clicks = _parse_max_clicks(raw_max_clicks)
    if not ok:
        return 400, {'error': 'invalid max_clicks; use a positive integer'}
    tags = _norm_tags(raw_tags)
    expires_at = None
    if expires_secs is not None:
        expires_at = (datetime.now(timezone.utc).replace(microsecond=0)
                      + timedelta(seconds=expires_secs)).isoformat()
    with _lock:
        if alias:
            existing = _entry_url(alias)
            if existing is not None and existing != url:
                return 409, {'error': 'alias already in use'}
            code = alias
            custom = True
        else:
            code = _gen_code(url)
            custom = False
        if STORE.get(code) is None:
            STORE[code] = {'url': url, 'clicks': 0,
                           'created': _now_iso(), 'custom': custom,
                           'expires_at': expires_at, 'tags': tags,
                           'disabled': False, 'max_clicks': max_clicks,
                           'click_log': []}
            _save_store(STORE)
        elif tags:
            # Merge tags into an already-existing entry (e.g. duplicate URL)
            # so a repeat shorten can enrich an existing link's labels.
            existing_entry = _normalize_entry(STORE.get(code))
            merged = _norm_tags(existing_entry['tags'] + tags)
            existing_entry['tags'] = merged
            STORE[code] = existing_entry
            _save_store(STORE)
    entry = _public_entry(code)
    return 201, {'code': code, 'url': url,
                 'short_path': '/{}'.format(code),
                 'clicks': entry['clicks'],
                 'created': entry['created'],
                 'custom': entry['custom'],
                 'expires_at': entry['expires_at'],
                 'expired': entry['expired'],
                 'tags': entry['tags'],
                 'disabled': entry['disabled'],
                 'max_clicks': entry['max_clicks'],
                 'exhausted': entry['exhausted']}


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "URLShortener/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _full_short(self, short_path):
        """Build an absolute short URL from the request Host, if present."""
        host = self.headers.get('Host', '')
        return ('http://' + host + short_path) if host else short_path

    def _send_csv(self, code, filename, body):
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition',
                         'attachment; filename="{}"'.format(filename))
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code, body):
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?', 1)[0]

        if path == '/' or path == '/index.html':
            try:
                with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                    self._send_html(200, f.read())
            except OSError:
                self._send_html(500, "<h1>index.html not found</h1>")
            return

        if path == '/api/list':
            query = self.path.split('?', 1)[1] if '?' in self.path else ''
            params = parse_qs(query)
            needle = (params.get('q', [''])[0] or '').strip().lower()
            tag = (params.get('tag', [''])[0] or '').strip().lower()
            with _lock:
                items = [_public_entry(c) for c in STORE]
            if needle:
                items = [it for it in items
                         if needle in it['code'].lower()
                         or needle in it['url'].lower()]
            if tag:
                items = [it for it in items if tag in it['tags']]
            sort = (params.get('sort', [''])[0] or '').strip().lower()
            order = (params.get('order', ['asc'])[0] or 'asc').strip().lower()
            if sort in ('clicks', 'created', 'code', 'url'):
                reverse = (order == 'desc')
                if sort == 'clicks':
                    items.sort(key=lambda it: it['clicks'], reverse=reverse)
                else:
                    items.sort(key=lambda it: (it.get(sort) or ''), reverse=reverse)
            total = len(items)
            # Optional pagination. Absent/invalid limit returns all items, so
            # existing callers see no behavior change.
            limit = _parse_nonneg_int(params.get('limit', [''])[0])
            offset = _parse_nonneg_int(params.get('offset', [''])[0]) or 0
            if limit is not None:
                items = items[offset:offset + limit]
            elif offset:
                items = items[offset:]
            self._send_json(200, {'items': items, 'total': total,
                                  'limit': limit, 'offset': offset})
            return

        if path == '/api/health':
            with _lock:
                n = len(STORE)
            self._send_json(200, {'status': 'ok', 'links': n})
            return

        if path == '/api/export':
            with _lock:
                entries = [_public_entry(c) for c in STORE]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['code', 'url', 'clicks', 'created',
                             'custom', 'expires_at', 'expired'])
            for e in entries:
                writer.writerow([e['code'], e['url'], e['clicks'],
                                 e['created'] or '', e['custom'],
                                 e['expires_at'] or '', e['expired']])
            self._send_csv(200, 'links.csv', buf.getvalue())
            return

        if path == '/api/summary':
            with _lock:
                entries = [_public_entry(c) for c in STORE]
            total_links = len(entries)
            total_clicks = sum(e['clicks'] for e in entries)
            expired = sum(1 for e in entries if e['expired'])
            disabled = sum(1 for e in entries if e['disabled'])
            exhausted = sum(1 for e in entries if e['exhausted'])
            custom = sum(1 for e in entries if e['custom'])
            tagged = sum(1 for e in entries if e['tags'])
            # An active link is one that is not expired, disabled or exhausted.
            active = sum(1 for e in entries
                         if not e['expired'] and not e['disabled']
                         and not e['exhausted'])
            tag_counts = {}
            for e in entries:
                for t in e['tags']:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            top = None
            for e in entries:
                if top is None or e['clicks'] > top['clicks']:
                    top = e
            self._send_json(200, {
                'total_links': total_links,
                'total_clicks': total_clicks,
                'active_links': active,
                'expired_links': expired,
                'disabled_links': disabled,
                'exhausted_links': exhausted,
                'custom_links': custom,
                'tagged_links': tagged,
                'tags': tag_counts,
                'top_link': top,
            })
            return

        if path == '/api/tags':
            with _lock:
                entries = [_public_entry(c) for c in STORE]
            tag_counts = {}
            for e in entries:
                for t in e['tags']:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            tags = [{'tag': t, 'count': n}
                    for t, n in sorted(tag_counts.items())]
            self._send_json(200, {'tags': tags, 'total': len(tags)})
            return

        if path.startswith('/api/expand/'):
            code = path[len('/api/expand/'):]
            with _lock:
                entry = _public_entry(code)
            if entry is None:
                self._send_json(404, {'error': 'code not found'})
            elif entry['expired']:
                self._send_json(410, {'error': 'link expired'})
            elif entry['disabled']:
                self._send_json(403, {'error': 'link disabled'})
            elif entry['exhausted']:
                self._send_json(410, {'error': 'link exhausted'})
            else:
                self._send_json(200, entry)
            return

        if path.startswith('/api/history/'):
            code = path[len('/api/history/'):]
            with _lock:
                entry = _normalize_entry(STORE.get(code))
                history = list(entry['click_log']) if entry is not None else None
                clicks = int(entry['clicks']) if entry is not None else 0
            if history is None:
                self._send_json(404, {'error': 'code not found'})
            else:
                self._send_json(200, {'code': code, 'clicks': clicks,
                                      'history': history,
                                      'count': len(history)})
            return

        if path.startswith('/api/stats/'):
            code = path[len('/api/stats/'):]
            with _lock:
                entry = _public_entry(code)
            if entry is None:
                self._send_json(404, {'error': 'code not found'})
            else:
                self._send_json(200, entry)
            return

        # Short URL redirect: /<code>
        code = path.lstrip('/')
        if code and '/' not in code:
            url = None
            expired = False
            disabled = False
            exhausted = False
            with _lock:
                entry = _normalize_entry(STORE.get(code))
                if entry is not None:
                    if _is_expired(entry):
                        expired = True
                    elif entry.get('disabled'):
                        disabled = True
                    elif _is_exhausted(entry):
                        exhausted = True
                    else:
                        # record the click before redirecting
                        url = entry['url']
                        entry['clicks'] += 1
                        now = _now_iso()
                        entry['last_clicked'] = now
                        log = entry.get('click_log') or []
                        log.append(now)
                        entry['click_log'] = log[-CLICK_LOG_CAP:]
                        STORE[code] = entry
                        _save_store(STORE)
            if url is not None:
                self.send_response(302)
                self.send_header('Location', url)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if expired:
                self._send_json(410, {'error': 'link expired'})
                return
            if disabled:
                self._send_json(403, {'error': 'link disabled'})
                return
            if exhausted:
                self._send_json(410, {'error': 'link exhausted'})
                return
            self._send_json(404, {'error': 'code not found'})
            return

        self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        path = self.path.split('?', 1)[0]

        if path == '/api/shorten':
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b''
            try:
                payload = json.loads(raw.decode('utf-8')) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {'error': 'invalid JSON'})
                return

            url = payload.get('url') if isinstance(payload, dict) else None
            alias = payload.get('alias') if isinstance(payload, dict) else None
            raw_expires = payload.get('expires_in') if isinstance(payload, dict) else None
            raw_tags = payload.get('tags') if isinstance(payload, dict) else None
            raw_max = payload.get('max_clicks') if isinstance(payload, dict) else None

            status, result = _create_entry(url, alias, raw_expires, raw_tags, raw_max)
            if status == 201:
                result['short_url'] = self._full_short(result['short_path'])
            self._send_json(status, result)
            return

        if path == '/api/shorten_bulk':
            ok, payload = self._read_json()
            if not ok:
                self._send_json(400, {'error': 'invalid JSON'})
                return
            urls = payload.get('urls') if isinstance(payload, dict) else None
            if not isinstance(urls, list) or not urls:
                self._send_json(400, {'error': 'provide a non-empty "urls" array'})
                return
            if len(urls) > 100:
                self._send_json(400, {'error': 'too many urls; max 100 per request'})
                return
            results = []
            created = 0
            for raw in urls:
                # Each item may be a bare URL string or {url, alias, expires_in}.
                if isinstance(raw, dict):
                    u = raw.get('url')
                    a = raw.get('alias')
                    e = raw.get('expires_in')
                    t = raw.get('tags')
                    m = raw.get('max_clicks')
                else:
                    u, a, e, t, m = raw, None, None, None, None
                status, result = _create_entry(u, a, e, t, m)
                if status == 201:
                    result['short_url'] = self._full_short(result['short_path'])
                    created += 1
                result['ok'] = (status == 201)
                result['status'] = status
                results.append(result)
            self._send_json(200, {'results': results,
                                  'created': created,
                                  'total': len(results)})
            return

        if path == '/api/import':
            self._import_csv()
            return

        # Disable a link: it stops redirecting until re-enabled, but is kept.
        if path.startswith('/api/disable/'):
            self._set_disabled(path[len('/api/disable/'):], True)
            return

        # Re-enable a previously disabled link.
        if path.startswith('/api/enable/'):
            self._set_disabled(path[len('/api/enable/'):], False)
            return

        # POST-based update as a fallback for clients that cannot send PUT
        if path.startswith('/api/update/'):
            self._update_code(path[len('/api/update/'):])
            return

        # POST-based delete as a fallback for clients that cannot send DELETE
        if path.startswith('/api/delete/'):
            self._delete_code(path[len('/api/delete/'):])
            return

        self._send_json(404, {'error': 'not found'})

    def do_PUT(self):
        path = self.path.split('?', 1)[0]
        if path.startswith('/api/update/'):
            self._update_code(path[len('/api/update/'):])
            return
        self._send_json(404, {'error': 'not found'})

    def do_DELETE(self):
        path = self.path.split('?', 1)[0]
        if path.startswith('/api/delete/'):
            self._delete_code(path[len('/api/delete/'):])
            return
        self._send_json(404, {'error': 'not found'})

    def _read_json(self):
        """Read and parse a JSON request body. Returns (ok, payload_or_error)."""
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        try:
            return True, (json.loads(raw.decode('utf-8')) if raw else {})
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False, None

    def _import_csv(self):
        """Bulk-create links from CSV — the counterpart to /api/export.

        The CSV text may arrive either as a raw request body (e.g.
        Content-Type text/csv) or wrapped in JSON as {"csv": "..."}. A header
        row is required and must include a ``url`` column; optional ``alias``,
        ``tags``, ``expires_in`` and ``max_clicks`` columns are honored. Each
        row is run through the same create path as the API, so validation and
        de-duplication are identical. Returns a bulk-style result summary.
        """
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        try:
            text = raw.decode('utf-8') if raw else ''
        except UnicodeDecodeError:
            self._send_json(400, {'error': 'invalid encoding; expected utf-8'})
            return
        ctype = (self.headers.get('Content-Type') or '').lower()
        # Allow the CSV to be wrapped in a JSON envelope for clients that
        # prefer to POST application/json.
        if 'application/json' in ctype:
            try:
                env = json.loads(text) if text else {}
            except json.JSONDecodeError:
                self._send_json(400, {'error': 'invalid JSON'})
                return
            text = env.get('csv') if isinstance(env, dict) else None
            if not isinstance(text, str):
                self._send_json(400, {'error': 'provide CSV text in a "csv" field'})
                return
        if not text.strip():
            self._send_json(400, {'error': 'empty CSV; provide at least a header and one row'})
            return
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or 'url' not in [
                (h or '').strip().lower() for h in reader.fieldnames]:
            self._send_json(400, {'error': 'CSV must have a header row with a "url" column'})
            return
        results = []
        created = 0
        for row in reader:
            # Normalize header keys so case/spacing in the CSV doesn't matter.
            norm = {(k or '').strip().lower(): v for k, v in row.items()}
            u = (norm.get('url') or '').strip()
            a = (norm.get('alias') or '').strip() or None
            t = norm.get('tags')
            e = (norm.get('expires_in') or '').strip() or None
            m = (norm.get('max_clicks') or '').strip() or None
            status, result = _create_entry(u, a, e, t, m)
            if status == 201:
                result['short_url'] = self._full_short(result['short_path'])
                created += 1
            result['ok'] = (status == 201)
            result['status'] = status
            results.append(result)
        self._send_json(200, {'results': results, 'created': created,
                              'total': len(results)})

    def _update_code(self, code):
        """Update an existing short code in place.

        The code, click count and creation time are always preserved. Any of
        ``url``, ``tags`` and ``disabled`` may be supplied; a field that is
        omitted is left untouched, so partial updates (e.g. retag without
        repointing) are supported. When ``url`` is present it must be valid.
        Returns the updated public entry.
        """
        ok, payload = self._read_json()
        if not ok:
            self._send_json(400, {'error': 'invalid JSON'})
            return
        if not isinstance(payload, dict):
            payload = {}
        has_url = 'url' in payload
        new_url = payload.get('url')
        if has_url and not _is_valid_url(new_url):
            self._send_json(400, {'error': 'invalid url; must be http:// or https:// and non-empty'})
            return
        if 'max_clicks' in payload:
            ok, new_max = _parse_max_clicks(payload.get('max_clicks'))
            if not ok:
                self._send_json(400, {'error': 'invalid max_clicks; use a positive integer'})
                return
        with _lock:
            entry = _normalize_entry(STORE.get(code))
            if entry is None:
                self._send_json(404, {'error': 'code not found'})
                return
            if has_url:
                entry['url'] = new_url.strip()
            if 'tags' in payload:
                entry['tags'] = _norm_tags(payload.get('tags'))
            if 'disabled' in payload:
                entry['disabled'] = bool(payload.get('disabled'))
            if 'max_clicks' in payload:
                entry['max_clicks'] = new_max
            STORE[code] = entry
            _save_store(STORE)
            result = _public_entry(code)
        self._send_json(200, result)

    def _set_disabled(self, code, value):
        """Flip a code's ``disabled`` flag. Returns the updated public entry."""
        with _lock:
            entry = _normalize_entry(STORE.get(code))
            if entry is None:
                self._send_json(404, {'error': 'code not found'})
                return
            entry['disabled'] = bool(value)
            STORE[code] = entry
            _save_store(STORE)
            result = _public_entry(code)
        self._send_json(200, result)

    def _delete_code(self, code):
        with _lock:
            existed = code in STORE
            if existed:
                del STORE[code]
                _save_store(STORE)
        if existed:
            self._send_json(200, {'deleted': code})
        else:
            self._send_json(404, {'error': 'code not found'})


def make_server(port=0):
    server = ThreadingHTTPServer(('0.0.0.0', port), RequestHandler)
    return server


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    httpd = make_server(port)
    print("URL shortener running on http://0.0.0.0:{}".format(httpd.server_address[1]))
    httpd.serve_forever()

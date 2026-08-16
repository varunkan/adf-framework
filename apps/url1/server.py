import os
import re
import io
import csv
import json
import time
import string
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'urls.json')
INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')

ALPHABET = string.ascii_letters + string.digits

# Allowed characters for a user-supplied custom alias.
CUSTOM_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# Codes that must never be used as short codes because they collide with routes.
RESERVED_CODES = {'api', 'index.html'}

_lock = threading.Lock()


def _now():
    return time.time()


def _normalize_record(value):
    """Coerce a stored value into the canonical record dict.

    Older data files stored plain url strings as the value; newer ones store a
    dict with metadata. This keeps both readable so upgrades never lose data.
    """
    if isinstance(value, str):
        return {'url': value, 'clicks': 0, 'created': None,
                'expires': None, 'custom': False, 'title': '',
                'last_clicked': None, 'active': True, 'max_clicks': None,
                'tags': []}
    if isinstance(value, dict) and isinstance(value.get('url'), str):
        title = value.get('title')
        raw_max = value.get('max_clicks')
        try:
            max_clicks = int(raw_max) if raw_max not in (None, '') else None
        except (ValueError, TypeError):
            max_clicks = None
        if max_clicks is not None and max_clicks <= 0:
            max_clicks = None
        raw_tags = value.get('tags')
        tags = _coerce_tags(raw_tags)
        return {
            'url': value['url'],
            'clicks': int(value.get('clicks', 0) or 0),
            'created': value.get('created'),
            'expires': value.get('expires'),
            'custom': bool(value.get('custom', False)),
            'title': title if isinstance(title, str) else '',
            'last_clicked': value.get('last_clicked'),
            # Disabled links stop redirecting but are kept for re-enabling.
            'active': bool(value.get('active', True)),
            # Optional cap; the link is exhausted once clicks reach it.
            'max_clicks': max_clicks,
            'tags': tags,
        }
    return None


def _coerce_tags(raw):
    """Best-effort normalize a stored/incoming tags value into a clean list."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for t in raw:
        if not isinstance(t, str):
            continue
        t = t.strip().lower()
        if t and t not in out:
            out.append(t)
    return out[:TAGS_MAX]


def _load_store():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    store = {}
    for code, value in data.items():
        rec = _normalize_record(value)
        if rec is not None:
            store[code] = rec
    return store


def _save_store(store):
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(store, f)
    os.replace(tmp, DATA_FILE)


def _is_expired(rec, now=None):
    exp = rec.get('expires')
    if not exp:
        return False
    return (now if now is not None else _now()) >= exp


def _encode(n):
    """Encode an integer into a short base62 code."""
    if n == 0:
        return ALPHABET[0]
    base = len(ALPHABET)
    out = []
    while n > 0:
        out.append(ALPHABET[n % base])
        n //= base
    return ''.join(reversed(out))


def _make_code(store, url):
    """Deterministic-ish unique code. Reuse code if url already shortened."""
    for code, rec in store.items():
        if rec['url'] == url and not rec.get('custom') and not _is_expired(rec):
            return code
    n = len(store) + 1
    code = _encode(n)
    while code in store or code in RESERVED_CODES:
        n += 1
        code = _encode(n)
    return code


def _valid_url(url):
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False
    return url.startswith('http://') or url.startswith('https://')


def _valid_custom(code):
    return isinstance(code, str) and bool(CUSTOM_RE.match(code)) and code not in RESERVED_CODES


# Optional human-friendly label length cap.
TITLE_MAX = 200

# Tag constraints: a small set of short, slug-like labels per link.
TAGS_MAX = 20
TAG_LEN_MAX = 40
TAG_RE = re.compile(r'^[A-Za-z0-9 _-]{1,40}$')


def _clean_tags(tags):
    """Return (clean_tags_list, error). Tags are optional; [] when absent.

    Accepts a list of strings or a single comma-separated string. Tags are
    lower-cased, trimmed, de-duplicated and order-preserving.
    """
    if tags is None or tags == '':
        return [], None
    if isinstance(tags, str):
        tags = [t for t in tags.split(',')]
    if not isinstance(tags, (list, tuple)):
        return None, 'tags must be a list of strings'
    out = []
    for t in tags:
        if not isinstance(t, str):
            return None, 'tags must be a list of strings'
        t = t.strip()
        if not t:
            continue
        if len(t) > TAG_LEN_MAX:
            return None, 'each tag must be at most {} characters'.format(TAG_LEN_MAX)
        if not TAG_RE.match(t):
            return None, 'tags may use letters, digits, spaces, - or _'
        t = t.lower()
        if t not in out:
            out.append(t)
    if len(out) > TAGS_MAX:
        return None, 'at most {} tags per link'.format(TAGS_MAX)
    return out, None


def _parse_max_clicks(max_clicks):
    """Return (max_clicks_or_None, error_or_None) for a max_clicks input."""
    if max_clicks is None or max_clicks == '':
        return None, None
    try:
        n = int(max_clicks)
    except (ValueError, TypeError):
        return None, 'max_clicks must be a positive integer'
    if n <= 0:
        return None, 'max_clicks must be a positive integer'
    return n, None


def _is_exhausted(rec):
    """True when a click-limited link has reached its cap."""
    mx = rec.get('max_clicks')
    if not mx:
        return False
    return rec.get('clicks', 0) >= mx


def _clean_title(title):
    """Return (clean_title, error). Title is optional; empty string when absent."""
    if title is None or title == '':
        return '', None
    if not isinstance(title, str):
        return None, 'title must be a string'
    title = title.strip()
    if len(title) > TITLE_MAX:
        return None, 'title must be at most {} characters'.format(TITLE_MAX)
    return title, None


def _public_item(code, rec):
    """Shape a store record for JSON responses."""
    return {
        'code': code,
        'url': rec['url'],
        'clicks': rec.get('clicks', 0),
        'created': rec.get('created'),
        'expires': rec.get('expires'),
        'custom': bool(rec.get('custom', False)),
        'expired': _is_expired(rec),
        'title': rec.get('title', '') or '',
        'last_clicked': rec.get('last_clicked'),
        'active': bool(rec.get('active', True)),
        'max_clicks': rec.get('max_clicks'),
        'exhausted': _is_exhausted(rec),
        'tags': list(rec.get('tags', []) or []),
    }


def _parse_expires_in(expires_in, now):
    """Return (expires_ts_or_None, error_or_None) for an expires_in input."""
    if expires_in is None or expires_in == '':
        return None, None
    try:
        secs = int(expires_in)
    except (ValueError, TypeError):
        return None, 'expires_in must be a positive integer (seconds)'
    if secs <= 0:
        return None, 'expires_in must be a positive integer (seconds)'
    return now + secs, None


def _shorten(store, url, custom=None, expires_in=None, title=None,
             max_clicks=None, tags=None, now=None):
    """Create (or reuse) a short code for ``url`` inside ``store``.

    Mutates ``store`` in place. Returns a dict describing the outcome:
      {'status': int, 'error': str}                      on failure
      {'status': int, 'code': str, 'rec': dict, 'existed': bool}  on success
    The caller owns persistence (``_save_store``) and lock management so a
    batch of shortens can be committed atomically.
    """
    now = _now() if now is None else now

    if not _valid_url(url):
        return {'status': 400,
                'error': 'invalid url; must start with http:// or https://'}
    url = url.strip()

    if custom is not None and custom != '':
        if not _valid_custom(custom):
            return {'status': 400,
                    'error': 'invalid alias; use letters, digits, - or _ (max 64)'}
    else:
        custom = None

    expires, err = _parse_expires_in(expires_in, now)
    if err is not None:
        return {'status': 400, 'error': err}

    clean_title, terr = _clean_title(title)
    if terr is not None:
        return {'status': 400, 'error': terr}

    max_clicks_val, mcerr = _parse_max_clicks(max_clicks)
    if mcerr is not None:
        return {'status': 400, 'error': mcerr}

    clean_tags, tagerr = _clean_tags(tags)
    if tagerr is not None:
        return {'status': 400, 'error': tagerr}

    if custom:
        existing = store.get(custom)
        if existing is not None and not _is_expired(existing):
            if existing['url'] == url:
                return {'status': 200, 'code': custom, 'rec': existing,
                        'existed': True}
            return {'status': 409, 'error': 'alias already in use'}
        code = custom
        is_custom = True
        existed = False
    else:
        existed = any(
            r['url'] == url and not r.get('custom') and not _is_expired(r)
            for r in store.values()
        )
        code = _make_code(store, url)
        is_custom = False

    rec = store.get(code)
    if rec is None or _is_expired(rec):
        rec = {'url': url, 'clicks': 0, 'created': now,
               'expires': expires, 'custom': is_custom,
               'title': clean_title, 'last_clicked': None,
               'active': True, 'max_clicks': max_clicks_val,
               'tags': clean_tags}
    else:
        # Allow attaching/overwriting optional metadata when re-shortening.
        if clean_title:
            rec['title'] = clean_title
        if max_clicks_val is not None:
            rec['max_clicks'] = max_clicks_val
        if clean_tags:
            merged = list(rec.get('tags', []) or [])
            for t in clean_tags:
                if t not in merged:
                    merged.append(t)
            rec['tags'] = merged[:TAGS_MAX]
    store[code] = rec
    return {'status': 200 if existed else 201, 'code': code, 'rec': rec,
            'existed': existed}


class RequestHandler(BaseHTTPRequestHandler):
    server_version = 'URLShortener/1.1'

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
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

    def _send_csv(self, status, text, filename='urls.csv'):
        body = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition',
                         'attachment; filename="{}"'.format(filename))
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            try:
                with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                    html = f.read()
            except FileNotFoundError:
                self._send_html(404, '<h1>index.html not found</h1>')
                return
            self._send_html(200, html)
            return

        # Lightweight health/metrics probe.
        if path == '/api/health':
            with _lock:
                store = _load_store()
                total = len(store)
                active = sum(1 for r in store.values() if not _is_expired(r))
                disabled = sum(1 for r in store.values()
                               if not _is_expired(r) and not r.get('active', True))
            self._send_json(200, {
                'status': 'ok',
                'count': total,
                'active': active,
                'expired': total - active,
                'disabled': disabled,
            })
            return

        # Export all links as CSV (spreadsheet-friendly).
        if path == '/api/export':
            with _lock:
                store = _load_store()
                items = [_public_item(c, r) for c, r in store.items()]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['code', 'url', 'title', 'clicks',
                             'created', 'expires', 'expired',
                             'active', 'max_clicks', 'tags'])
            for it in items:
                writer.writerow([
                    it['code'], it['url'], it.get('title', ''),
                    it['clicks'], it.get('created'), it.get('expires'),
                    it['expired'], it.get('active', True),
                    it.get('max_clicks'),
                    ','.join(it.get('tags', []) or []),
                ])
            self._send_csv(200, buf.getvalue())
            return

        # Most-clicked links, descending. Optional ?limit=N (default 5).
        if path == '/api/top':
            limit = 5
            raw_limit = (query.get('limit') or [None])[0]
            if raw_limit is not None:
                try:
                    limit = int(raw_limit)
                except (ValueError, TypeError):
                    self._send_json(400, {'error': 'limit must be an integer'})
                    return
                if limit < 0:
                    self._send_json(400, {'error': 'limit must be non-negative'})
                    return
            with _lock:
                store = _load_store()
                items = [_public_item(c, r) for c, r in store.items()
                         if not _is_expired(r)]
            items.sort(key=lambda i: i.get('clicks', 0), reverse=True)
            self._send_json(200, {'items': items[:limit]})
            return

        if path == '/api/urls':
            # Optional ?q= substring filter over code and target url.
            term = (query.get('q') or [''])[0].strip().lower()
            # Optional ?tag= exact-match filter over a link's tags.
            tag = (query.get('tag') or [''])[0].strip().lower()
            # Optional ?active=true|false filter over the enabled flag.
            active = (query.get('active') or [''])[0].strip().lower()
            with _lock:
                store = _load_store()
                items = [_public_item(c, r) for c, r in store.items()]
            if term:
                items = [i for i in items
                         if term in i['code'].lower() or term in i['url'].lower()]
            if tag:
                items = [i for i in items if tag in (i.get('tags') or [])]
            if active in ('true', '1', 'yes'):
                items = [i for i in items if i.get('active', True)]
            elif active in ('false', '0', 'no'):
                items = [i for i in items if not i.get('active', True)]
            self._send_json(200, {'items': items})
            return

        if path.startswith('/api/stats/'):
            code = path[len('/api/stats/'):]
            with _lock:
                store = _load_store()
                rec = store.get(code)
                item = _public_item(code, rec) if rec else None
            if item is None:
                self._send_json(404, {'error': 'unknown code'})
                return
            self._send_json(200, item)
            return

        if path.startswith('/api/'):
            self._send_json(404, {'error': 'not found'})
            return

        # Redirect short code -> original URL
        code = path.lstrip('/')
        if code:
            with _lock:
                store = _load_store()
                rec = store.get(code)
                expired = rec is not None and _is_expired(rec)
                disabled = rec is not None and not expired \
                    and not rec.get('active', True)
                exhausted = rec is not None and not expired and not disabled \
                    and _is_exhausted(rec)
                if rec is not None and not expired and not disabled \
                        and not exhausted:
                    rec['clicks'] = rec.get('clicks', 0) + 1
                    rec['last_clicked'] = _now()
                    store[code] = rec
                    _save_store(store)
                    target = rec['url']
                else:
                    target = None
            if expired:
                self._send_json(410, {'error': 'link expired'})
                return
            if disabled:
                self._send_json(403, {'error': 'link disabled'})
                return
            if exhausted:
                self._send_json(410, {'error': 'link exhausted'})
                return
            if target:
                self.send_response(301)
                self.send_header('Location', target)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return

        self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        path = self.path.split('?', 1)[0]

        if path == '/api/shorten':
            data = self._read_json()
            if data is None or not isinstance(data, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return

            with _lock:
                store = _load_store()
                result = _shorten(store, data.get('url'),
                                  custom=data.get('custom'),
                                  expires_in=data.get('expires_in'),
                                  title=data.get('title'),
                                  max_clicks=data.get('max_clicks'),
                                  tags=data.get('tags'))
                if 'error' in result:
                    self._send_json(result['status'], {'error': result['error']})
                    return
                _save_store(store)
                payload = self._shorten_payload(result['code'], result['rec'])
            self._send_json(result['status'], payload)
            return

        if path == '/api/shorten/bulk':
            data = self._read_json()
            if data is None or not isinstance(data, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            urls = data.get('urls')
            if not isinstance(urls, list) or not urls:
                self._send_json(400, {'error': 'urls must be a non-empty array'})
                return
            if len(urls) > 100:
                self._send_json(400, {'error': 'at most 100 urls per request'})
                return

            results = []
            with _lock:
                store = _load_store()
                for url in urls:
                    result = _shorten(store, url)
                    if 'error' in result:
                        results.append({'url': url, 'error': result['error']})
                    else:
                        payload = self._shorten_payload(result['code'],
                                                        result['rec'])
                        payload['created'] = not result['existed']
                        results.append(payload)
                _save_store(store)
            ok = sum(1 for r in results if 'error' not in r)
            self._send_json(200, {'results': results, 'ok': ok,
                                  'failed': len(results) - ok})
            return

        # Reset the click counter for a code back to zero.
        if path.startswith('/api/urls/') and path.endswith('/reset'):
            code = path[len('/api/urls/'):-len('/reset')]
            with _lock:
                store = _load_store()
                rec = store.get(code)
                if rec is None:
                    self._send_json(404, {'error': 'unknown code'})
                    return
                rec['clicks'] = 0
                rec['last_clicked'] = None
                store[code] = rec
                _save_store(store)
                item = _public_item(code, rec)
            self._send_json(200, item)
            return

        # Disable a link: it stops redirecting (403) but is kept for re-enabling.
        if path.startswith('/api/urls/') and path.endswith('/disable'):
            code = path[len('/api/urls/'):-len('/disable')]
            self._set_active(code, False)
            return

        # Re-enable a previously disabled link.
        if path.startswith('/api/urls/') and path.endswith('/enable'):
            code = path[len('/api/urls/'):-len('/enable')]
            self._set_active(code, True)
            return

        self._send_json(404, {'error': 'not found'})

    def _set_active(self, code, active):
        """Toggle a link's active flag and respond with its public item."""
        with _lock:
            store = _load_store()
            rec = store.get(code)
            if rec is None:
                self._send_json(404, {'error': 'unknown code'})
                return
            rec['active'] = bool(active)
            store[code] = rec
            _save_store(store)
            item = _public_item(code, rec)
        self._send_json(200, item)

    def do_DELETE(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/expired':
            with _lock:
                store = _load_store()
                expired_codes = [c for c, r in store.items() if _is_expired(r)]
                for c in expired_codes:
                    del store[c]
                if expired_codes:
                    _save_store(store)
            self._send_json(200, {'purged': len(expired_codes),
                                  'codes': expired_codes})
            return
        if path.startswith('/api/urls/'):
            code = path[len('/api/urls/'):]
            with _lock:
                store = _load_store()
                if code in store:
                    del store[code]
                    _save_store(store)
                    found = True
                else:
                    found = False
            if found:
                self._send_json(200, {'deleted': True, 'code': code})
            else:
                self._send_json(404, {'error': 'unknown code'})
            return
        self._send_json(404, {'error': 'not found'})

    def do_PATCH(self):
        path = self.path.split('?', 1)[0]
        if path.startswith('/api/urls/'):
            code = path[len('/api/urls/'):]
            data = self._read_json()
            if data is None or not isinstance(data, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return

            # Validate every supplied field up front so a bad value never
            # commits a partial update.
            has_url = 'url' in data
            if has_url:
                if not _valid_url(data.get('url')):
                    self._send_json(400, {'error': 'invalid url; must start with http:// or https://'})
                    return
                new_url = data['url'].strip()

            new_title = None
            if 'title' in data:
                new_title, terr = _clean_title(data.get('title'))
                if terr is not None:
                    self._send_json(400, {'error': terr})
                    return

            new_tags = None
            if 'tags' in data:
                new_tags, tagerr = _clean_tags(data.get('tags'))
                if tagerr is not None:
                    self._send_json(400, {'error': tagerr})
                    return

            set_max_clicks = 'max_clicks' in data
            new_max_clicks = None
            if set_max_clicks:
                new_max_clicks, mcerr = _parse_max_clicks(data.get('max_clicks'))
                if mcerr is not None:
                    self._send_json(400, {'error': mcerr})
                    return

            with _lock:
                store = _load_store()
                rec = store.get(code)
                if rec is None:
                    self._send_json(404, {'error': 'unknown code'})
                    return
                if has_url:
                    rec['url'] = new_url
                if new_title is not None:
                    rec['title'] = new_title
                if new_tags is not None:
                    rec['tags'] = new_tags
                if set_max_clicks:
                    rec['max_clicks'] = new_max_clicks
                if 'active' in data:
                    rec['active'] = bool(data.get('active'))
                store[code] = rec
                _save_store(store)
                item = _public_item(code, rec)
            self._send_json(200, item)
            return
        self._send_json(404, {'error': 'not found'})

    def _shorten_payload(self, code, rec):
        host = self.headers.get('Host', 'localhost')
        return {
            'code': code,
            'url': rec['url'],
            'short_url': 'http://{}/{}'.format(host, code),
            'custom': bool(rec.get('custom', False)),
            'expires': rec.get('expires'),
            'clicks': rec.get('clicks', 0),
            'title': rec.get('title', '') or '',
            'max_clicks': rec.get('max_clicks'),
            'tags': list(rec.get('tags', []) or []),
            'active': bool(rec.get('active', True)),
        }


def make_server(port=0):
    server = ThreadingHTTPServer(('0.0.0.0', port), RequestHandler)
    return server


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    httpd = make_server(port)
    actual = httpd.server_address[1]
    print('URL shortener server ready on http://0.0.0.0:{}'.format(actual))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()

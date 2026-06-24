import os
import io
import csv
import json
import uuid
import calendar
import datetime
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'expenses.json')
BUDGET_FILE = os.path.join(BASE_DIR, 'budget.json')
CAT_BUDGET_FILE = os.path.join(BASE_DIR, 'category_budgets.json')
INDEX_FILE = os.path.join(BASE_DIR, 'index.html')

CATEGORIES = {'Food', 'Transport', 'Bills', 'Fun', 'Other'}

_lock = threading.Lock()


def _load():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (ValueError, OSError):
        return []


def _save(expenses):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(expenses, f, indent=2)


def _valid_date(s):
    if not isinstance(s, str) or len(s) != 10:
        return False
    parts = s.split('-')
    if len(parts) != 3:
        return False
    y, m, d = parts
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return False
    if len(y) != 4 or len(m) != 2 or len(d) != 2:
        return False
    mi, di = int(m), int(d)
    return 1 <= mi <= 12 and 1 <= di <= 31


MAX_TAGS = 10
MAX_TAG_LEN = 30


def _normalize_tags(raw):
    """Validate/clean a list of tag labels.

    Returns (tags_list, None) on success or (None, error_message) on failure.
    None/absent -> []. Each tag is stripped; empties dropped; duplicates removed
    case-insensitively (first spelling wins) while preserving order. Enforces a
    max tag length and a max tag count so a single expense can't carry junk.
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, 'tags must be a list'
    out = []
    seen = set()
    for t in raw:
        if not isinstance(t, str):
            return None, 'tags must be strings'
        t = t.strip()
        if not t:
            continue
        if len(t) > MAX_TAG_LEN:
            return None, 'tag too long (max %d chars)' % MAX_TAG_LEN
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    if len(out) > MAX_TAGS:
        return None, 'too many tags (max %d)' % MAX_TAGS
    return out, None


def _validate_fields(amount, category, note, date, tags=None):
    """Validate a full set of expense fields.

    Returns (cleaned_dict, None) on success or (None, error_message) on failure.
    Shared by both create (POST) and edit (PUT) so validation never drifts.
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None, 'amount must be a number'
    if amount <= 0:
        return None, 'amount must be positive'
    if category not in CATEGORIES:
        return None, 'invalid category'
    if not _valid_date(date):
        return None, 'invalid date (expected YYYY-MM-DD)'
    if note is None:
        note = ''
    if not isinstance(note, str):
        return None, 'note must be a string'
    clean_tags, terr = _normalize_tags(tags)
    if terr is not None:
        return None, terr
    return {
        'amount': round(amount, 2),
        'category': category,
        'note': note.strip(),
        'date': date,
        'tags': clean_tags,
    }, None


def _filter_expenses(expenses, category=None, start=None, end=None, query=None,
                     tag=None):
    """Return the subset of expenses matching the optional filters.

    category: exact category match (None or 'All' means no category filter).
    start/end: inclusive ISO date bounds (YYYY-MM-DD lexical compare == chrono).
    query: case-insensitive substring matched against the note (empty/None skips).
    tag: case-insensitive exact match against any one of the expense's tags.
    """
    needle = query.strip().lower() if isinstance(query, str) else ''
    tagq = tag.strip().lower() if isinstance(tag, str) else ''
    out = []
    for e in expenses:
        if category and category != 'All' and e.get('category') != category:
            continue
        d = e.get('date', '')
        if start and d < start:
            continue
        if end and d > end:
            continue
        if needle and needle not in str(e.get('note', '')).lower():
            continue
        if tagq:
            etags = [str(t).lower() for t in (e.get('tags') or [])]
            if tagq not in etags:
                continue
        out.append(e)
    return out


def _tag_breakdown(expenses):
    """Total spend grouped by tag, sorted by spend desc then tag name.

    An expense with multiple tags contributes its full amount to each, so the
    sum across tags can exceed the overall total (tags are not partitions).
    """
    totals = {}
    for e in expenses:
        amt = float(e.get('amount', 0) or 0)
        for t in (e.get('tags') or []):
            t = str(t)
            totals[t] = round(totals.get(t, 0.0) + amt, 2)
    return dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))


def _forecast(expenses, asof):
    """Project month-end spend from the average daily spend so far this month.

    asof is the reference date (YYYY-MM-DD). Looks only at expenses dated within
    asof's calendar month, divides by the day-of-month to get an average daily
    rate, and scales that over the whole month. Returns None for a bad date.
    """
    if not _valid_date(asof):
        return None
    y, m, d = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    month = asof[:7]
    spent = 0.0
    for e in expenses:
        if str(e.get('date', ''))[:7] == month:
            spent += float(e.get('amount', 0) or 0)
    spent = round(spent, 2)
    days_in_month = calendar.monthrange(y, m)[1]
    days_elapsed = d
    avg_daily = round(spent / days_elapsed, 2) if days_elapsed else 0.0
    projected = round(avg_daily * days_in_month, 2)
    return {
        'month': month,
        'spent': spent,
        'days_elapsed': days_elapsed,
        'days_in_month': days_in_month,
        'avg_daily': avg_daily,
        'projected': projected,
    }


SORT_KEYS = {'date', 'amount', 'category', 'note'}


def _sort_expenses(expenses, sort=None, order='asc'):
    """Return expenses sorted by a field, preserving input order when unsorted.

    sort: one of SORT_KEYS (None leaves insertion order untouched).
    order: 'asc' (default) or 'desc'. 'amount' sorts numerically; the rest sort
    as case-insensitive strings.
    """
    if sort not in SORT_KEYS:
        return list(expenses)
    reverse = (order == 'desc')
    if sort == 'amount':
        keyfn = lambda e: float(e.get('amount', 0) or 0)
    else:
        keyfn = lambda e: str(e.get(sort, '')).lower()
    return sorted(expenses, key=keyfn, reverse=reverse)


def _top_category(breakdown):
    """Return the category with the highest spend, or None if nothing spent.

    Ties are broken alphabetically so the result is deterministic.
    """
    spent = {c: v for c, v in breakdown.items() if v > 0}
    if not spent:
        return None
    return sorted(spent.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _largest_expense(expenses):
    """Return the single highest-amount expense, or None for an empty list."""
    if not expenses:
        return None
    return max(expenses, key=lambda e: float(e.get('amount', 0) or 0))


def _summarize(expenses):
    """Compute total, per-category breakdown, count and average for a list."""
    total = round(sum(float(e['amount']) for e in expenses), 2)
    breakdown = {c: 0.0 for c in CATEGORIES}
    for e in expenses:
        breakdown[e['category']] = round(
            breakdown.get(e['category'], 0.0) + float(e['amount']), 2)
    count = len(expenses)
    average = round(total / count, 2) if count else 0.0
    return {
        'expenses': expenses,
        'total': total,
        'breakdown': breakdown,
        'count': count,
        'average': average,
        'top_category': _top_category(breakdown),
        'largest': _largest_expense(expenses),
    }


def _load_budget():
    """Return the saved monthly budget as a float, or None if unset."""
    if not os.path.exists(BUDGET_FILE):
        return None
    try:
        with open(BUDGET_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        b = data.get('budget')
        if b is None:
            return None
        return round(float(b), 2)
    except (ValueError, OSError, AttributeError, TypeError):
        return None


def _save_budget(amount):
    with open(BUDGET_FILE, 'w', encoding='utf-8') as f:
        json.dump({'budget': amount}, f, indent=2)


def _budget_status(total, budget):
    """Describe how a spent total sits against a budget.

    budget None -> no budget set; remaining/over_budget are inert.
    Otherwise remaining = budget - total (may be negative) and
    over_budget flags an overspend.
    """
    if budget is None:
        return {'budget': None, 'remaining': None, 'over_budget': False}
    remaining = round(budget - total, 2)
    return {
        'budget': round(budget, 2),
        'remaining': remaining,
        'over_budget': total > budget,
    }


def _monthly_breakdown(expenses):
    """Group spend totals by calendar month (YYYY-MM), sorted ascending."""
    months = {}
    for e in expenses:
        date = e.get('date', '')
        key = date[:7]
        if len(key) != 7:
            continue
        months[key] = round(months.get(key, 0.0) + float(e['amount']), 2)
    return dict(sorted(months.items()))


def _expenses_csv(expenses):
    """Render expenses as a CSV document (header + one row each)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['id', 'date', 'category', 'amount', 'note'])
    for e in expenses:
        writer.writerow([
            e.get('id', ''),
            e.get('date', ''),
            e.get('category', ''),
            e.get('amount', ''),
            e.get('note', ''),
        ])
    return buf.getvalue()


def _parse_import_csv(text):
    """Parse a CSV document into validated expense field dicts.

    The natural counterpart to _expenses_csv: it ingests the same shape the
    export produces. Returns (expenses, errors) where each expenses item is a
    cleaned field dict (no id yet) and each errors item is
    {'row': <1-based data row>, 'error': <message>}.

    The CSV must have a header row; column names are matched case-insensitively
    and only date/category/amount/note/tags are read. An 'id' column (as
    written by the export) is ignored so re-importing an export gives every row
    a fresh id rather than colliding. 'tags' may hold a semicolon-separated
    list. Every data row is validated with the very same _validate_fields rules
    as the create endpoint, so import can never smuggle in data the API would
    reject. A bad row is skipped and recorded — one malformed line never sinks
    the whole import.
    """
    expenses = []
    errors = []
    if not isinstance(text, str) or not text.strip():
        return expenses, errors
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return expenses, errors
    fieldmap = {}
    for name in reader.fieldnames:
        if isinstance(name, str):
            fieldmap[name.strip().lower()] = name

    def cell(row, col):
        key = fieldmap.get(col)
        return row.get(key) if key is not None else None

    for i, row in enumerate(reader, start=1):
        raw_tags = cell(row, 'tags')
        tags = None
        if isinstance(raw_tags, str) and raw_tags.strip():
            tags = [t.strip() for t in raw_tags.split(';') if t.strip()]
        cleaned, err = _validate_fields(
            cell(row, 'amount'),
            cell(row, 'category'),
            cell(row, 'note'),
            cell(row, 'date'),
            tags,
        )
        if err is not None:
            errors.append({'row': i, 'error': err})
            continue
        expenses.append(cleaned)
    return expenses, errors


def _load_cat_budgets():
    """Return the saved per-category budgets as {category: float}.

    Silently drops unknown categories, non-numeric, or negative values so a
    hand-edited / corrupt file can never crash a request.
    """
    if not os.path.exists(CAT_BUDGET_FILE):
        return {}
    try:
        with open(CAT_BUDGET_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for c, v in data.items():
        if c not in CATEGORIES:
            continue
        try:
            fv = round(float(v), 2)
        except (TypeError, ValueError):
            continue
        if fv >= 0:
            out[c] = fv
    return out


def _save_cat_budgets(budgets):
    with open(CAT_BUDGET_FILE, 'w', encoding='utf-8') as f:
        json.dump(budgets, f, indent=2)


def _category_budget_status(breakdown, cat_budgets):
    """Describe spend vs limit for every category that has a budget set.

    Returns {category: {budget, spent, remaining, over_budget}} keyed only by
    categories present in cat_budgets. spent is read from the supplied breakdown
    (so it honours whatever filtering produced that breakdown).
    """
    out = {}
    for c, limit in cat_budgets.items():
        spent = round(float(breakdown.get(c, 0.0) or 0.0), 2)
        limit = round(float(limit), 2)
        out[c] = {
            'budget': limit,
            'spent': spent,
            'remaining': round(limit - spent, 2),
            'over_budget': spent > limit,
        }
    return out


def _median(values):
    """Return the median of a list of numbers, or None when empty."""
    if not values:
        return None
    s = sorted(float(v) for v in values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return round(s[mid], 2)
    return round((s[mid - 1] + s[mid]) / 2.0, 2)


WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def _weekday_breakdown(expenses):
    """Group total spend by day-of-week name (Mon..Sun), skipping bad dates."""
    out = {d: 0.0 for d in WEEKDAYS}
    for e in expenses:
        date = e.get('date', '')
        parts = str(date).split('-')
        if len(parts) != 3:
            continue
        try:
            wd = datetime.date(int(parts[0]), int(parts[1]), int(parts[2])).weekday()
        except (ValueError, TypeError):
            continue
        name = WEEKDAYS[wd]
        out[name] = round(out[name] + float(e.get('amount', 0) or 0), 2)
    return out


def _stats(expenses):
    """Compute min / max / median expense amount plus a weekday breakdown."""
    amounts = [float(e['amount']) for e in expenses if e.get('amount') is not None]
    return {
        'min': round(min(amounts), 2) if amounts else None,
        'max': round(max(amounts), 2) if amounts else None,
        'median': _median(amounts),
        'weekday': _weekday_breakdown(expenses),
    }


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
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
        except ValueError:
            return None

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self._serve_index()
            return
        parsed = urlparse(self.path)
        if parsed.path == '/api/budget':
            with _lock:
                budget = _load_budget()
            self._send_json({'budget': budget})
            return
        if parsed.path == '/api/summary/monthly':
            with _lock:
                expenses = _load()
            self._send_json({'monthly': _monthly_breakdown(expenses)})
            return
        if parsed.path == '/api/summary/stats':
            with _lock:
                expenses = _load()
            self._send_json({'stats': _stats(expenses)})
            return
        if parsed.path == '/api/summary/tags':
            with _lock:
                expenses = _load()
            self._send_json({'tags': _tag_breakdown(expenses)})
            return
        if parsed.path == '/api/summary/forecast':
            qs = parse_qs(parsed.query)
            asof = qs.get('asof', [None])[0]
            if asof is None or not _valid_date(asof):
                self._send_json({'error': 'asof must be a valid date (YYYY-MM-DD)'}, 400)
                return
            with _lock:
                expenses = _load()
            self._send_json({'forecast': _forecast(expenses, asof)})
            return
        if parsed.path == '/api/budgets/categories':
            with _lock:
                cat_budgets = _load_cat_budgets()
            self._send_json({'categories': cat_budgets})
            return
        if parsed.path == '/api/expenses.csv':
            with _lock:
                expenses = _load()
            self._serve_csv(_expenses_csv(expenses))
            return
        if parsed.path == '/api/expenses':
            qs = parse_qs(parsed.query)
            category = qs.get('category', [None])[0]
            start = qs.get('start', [None])[0]
            end = qs.get('end', [None])[0]
            query = qs.get('q', [None])[0]
            tag = qs.get('tag', [None])[0]
            sort = qs.get('sort', [None])[0]
            order = qs.get('order', ['asc'])[0]

            if category and category != 'All' and category not in CATEGORIES:
                self._send_json({'error': 'invalid category filter'}, 400)
                return
            if start is not None and not _valid_date(start):
                self._send_json({'error': 'invalid start date (expected YYYY-MM-DD)'}, 400)
                return
            if end is not None and not _valid_date(end):
                self._send_json({'error': 'invalid end date (expected YYYY-MM-DD)'}, 400)
                return
            if sort is not None and sort not in SORT_KEYS:
                self._send_json({'error': 'invalid sort field'}, 400)
                return
            if order not in ('asc', 'desc'):
                self._send_json({'error': 'invalid sort order (expected asc or desc)'}, 400)
                return

            with _lock:
                expenses = _load()
                budget = _load_budget()
                cat_budgets = _load_cat_budgets()
            filtered = _filter_expenses(expenses, category, start, end, query, tag)
            filtered = _sort_expenses(filtered, sort, order)
            summary = _summarize(filtered)
            summary.update(_budget_status(summary['total'], budget))
            summary['category_budgets'] = _category_budget_status(
                summary['breakdown'], cat_budgets)
            self._send_json(summary)
            return
        self._send_json({'error': 'not found'}, 404)

    def _serve_csv(self, text):
        body = text.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="expenses.csv"')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self):
        try:
            with open(INDEX_FILE, 'rb') as f:
                body = f.read()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == '/api/expenses/import':
            self._handle_import()
            return
        if self.path != '/api/expenses':
            self._send_json({'error': 'not found'}, 404)
            return
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return

        cleaned, error = _validate_fields(
            data.get('amount'),
            data.get('category'),
            data.get('note', ''),
            data.get('date'),
            data.get('tags'),
        )
        if error is not None:
            self._send_json({'error': error}, 400)
            return

        expense = {'id': uuid.uuid4().hex}
        expense.update(cleaned)
        with _lock:
            expenses = _load()
            expenses.append(expense)
            _save(expenses)
        self._send_json(expense, 201)

    def _handle_import(self):
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        csv_text = data.get('csv')
        if not isinstance(csv_text, str):
            self._send_json({'error': 'csv must be a string'}, 400)
            return
        parsed, errors = _parse_import_csv(csv_text)
        imported = []
        with _lock:
            expenses = _load()
            for cleaned in parsed:
                expense = {'id': uuid.uuid4().hex}
                expense.update(cleaned)
                expenses.append(expense)
                imported.append(expense)
            if imported:
                _save(expenses)
        self._send_json({
            'imported': len(imported),
            'skipped': len(errors),
            'errors': errors,
            'expenses': imported,
        }, 200)

    def do_PUT(self):
        if urlparse(self.path).path == '/api/budget':
            self._handle_budget_put()
            return
        if urlparse(self.path).path == '/api/budgets/categories':
            self._handle_cat_budget_put()
            return
        prefix = '/api/expenses/'
        if not self.path.startswith(prefix):
            self._send_json({'error': 'not found'}, 404)
            return
        eid = urlparse(self.path).path[len(prefix):]
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return

        with _lock:
            expenses = _load()
            target = next((e for e in expenses if e['id'] == eid), None)
            if target is None:
                self._send_json({'error': 'expense not found'}, 404)
                return

            # Partial update: provided fields override, others keep current value.
            cleaned, error = _validate_fields(
                data.get('amount', target['amount']),
                data.get('category', target['category']),
                data.get('note', target.get('note', '')),
                data.get('date', target['date']),
                data.get('tags', target.get('tags', [])),
            )
            if error is not None:
                self._send_json({'error': error}, 400)
                return

            target.update(cleaned)
            updated = dict(target)
            _save(expenses)
        self._send_json(updated, 200)

    def _handle_budget_put(self):
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        raw = data.get('budget')
        if raw is None:
            # Clearing the budget.
            with _lock:
                _save_budget(None)
            self._send_json({'budget': None}, 200)
            return
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            self._send_json({'error': 'budget must be a number'}, 400)
            return
        if amount < 0:
            self._send_json({'error': 'budget must not be negative'}, 400)
            return
        amount = round(amount, 2)
        with _lock:
            _save_budget(amount)
        self._send_json({'budget': amount}, 200)

    def _handle_cat_budget_put(self):
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        cat = data.get('category')
        if cat not in CATEGORIES:
            self._send_json({'error': 'invalid category'}, 400)
            return
        raw = data.get('budget')
        with _lock:
            budgets = _load_cat_budgets()
            if raw is None:
                # Clearing this category's budget.
                budgets.pop(cat, None)
                _save_cat_budgets(budgets)
                self._send_json({'categories': budgets}, 200)
                return
            try:
                amount = float(raw)
            except (TypeError, ValueError):
                self._send_json({'error': 'budget must be a number'}, 400)
                return
            if amount < 0:
                self._send_json({'error': 'budget must not be negative'}, 400)
                return
            budgets[cat] = round(amount, 2)
            _save_cat_budgets(budgets)
        self._send_json({'categories': budgets}, 200)

    def do_DELETE(self):
        prefix = '/api/expenses/'
        if not self.path.startswith(prefix):
            self._send_json({'error': 'not found'}, 404)
            return
        eid = self.path[len(prefix):]
        with _lock:
            expenses = _load()
            new = [e for e in expenses if e['id'] != eid]
            if len(new) == len(expenses):
                self._send_json({'error': 'expense not found'}, 404)
                return
            _save(new)
        self._send_json({'deleted': eid})


def make_server(port=0):
    return ThreadingHTTPServer(('', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print('Expense tracker server ready on port %d' % server.server_address[1])
    server.serve_forever()

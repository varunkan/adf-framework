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
RECURRING_FILE = os.path.join(BASE_DIR, 'recurring.json')
INDEX_FILE = os.path.join(BASE_DIR, 'index.html')

CATEGORIES = {'Food', 'Transport', 'Bills', 'Fun', 'Other'}
RECUR_FREQS = {'daily', 'weekly', 'monthly'}

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


def _valid_month(s):
    """True for a well-formed YYYY-MM month string (01..12)."""
    if not isinstance(s, str) or len(s) != 7:
        return False
    parts = s.split('-')
    if len(parts) != 2:
        return False
    y, m = parts
    if not (y.isdigit() and m.isdigit()):
        return False
    if len(y) != 4 or len(m) != 2:
        return False
    return 1 <= int(m) <= 12


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
                     tag=None, min_amount=None, max_amount=None):
    """Return the subset of expenses matching the optional filters.

    category: exact category match (None or 'All' means no category filter).
    start/end: inclusive ISO date bounds (YYYY-MM-DD lexical compare == chrono).
    query: case-insensitive substring matched against the note (empty/None skips).
    tag: case-insensitive exact match against any one of the expense's tags.
    min_amount/max_amount: inclusive numeric bounds on the expense amount; None
    on either side leaves that side unbounded (mirrors the date-range filter).
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
        if min_amount is not None or max_amount is not None:
            amt = float(e.get('amount', 0) or 0)
            if min_amount is not None and amt < min_amount:
                continue
            if max_amount is not None and amt > max_amount:
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


def _budget_pace(expenses, budget, asof):
    """Pace month-end spend against a budget, building on _forecast.

    Takes the linear month-end projection from _forecast and measures it against
    the monthly budget so the UI can answer "at this rate, will I blow my
    budget, and how much can I still spend per remaining day to stay under?".

    Returns None for a bad asof date (mirrors _forecast). With no budget set the
    forecast fields are still computed, but the budget-relative fields
    (projected_remaining, percent_used, daily_budget_remaining) are inert/None
    and on_track is True (nothing to overshoot). daily_budget_remaining floors
    at 0 (an overspend never implies a "negative allowance") and is None on the
    last day of the month, where there are no remaining days to spread over.
    """
    fc = _forecast(expenses, asof)
    if fc is None:
        return None
    spent = fc['spent']
    projected = fc['projected']
    days_left = fc['days_in_month'] - fc['days_elapsed']
    if budget is None:
        return {
            'budget': None,
            'spent': spent,
            'projected': projected,
            'projected_remaining': None,
            'on_track': True,
            'already_over': False,
            'days_left': days_left,
            'daily_budget_remaining': None,
            'percent_used': None,
        }
    budget = round(float(budget), 2)
    if days_left <= 0:
        daily_budget_remaining = None
    else:
        daily_budget_remaining = round(max(0.0, (budget - spent) / days_left), 2)
    return {
        'budget': budget,
        'spent': spent,
        'projected': projected,
        'projected_remaining': round(budget - projected, 2),
        'on_track': projected <= budget,
        'already_over': spent > budget,
        'days_left': days_left,
        'daily_budget_remaining': daily_budget_remaining,
        'percent_used': round((spent / budget) * 100, 2) if budget else None,
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


def _category_monthly(expenses):
    """Pivot spend by category then calendar month (YYYY-MM).

    Returns {category: {month: total, ...}, ...} with months sorted ascending
    within each category and categories sorted by name. The natural complement
    to _monthly_breakdown (which collapses categories) and _summarize's
    per-category breakdown (which collapses months): this keeps both axes so the
    UI can chart how each category trends month over month. Only known
    categories and well-formed YYYY-MM dates are counted.
    """
    out = {}
    for e in expenses:
        cat = e.get('category')
        if cat not in CATEGORIES:
            continue
        month = str(e.get('date', ''))[:7]
        if len(month) != 7:
            continue
        cm = out.setdefault(cat, {})
        cm[month] = round(cm.get(month, 0.0) + float(e.get('amount', 0) or 0), 2)
    return {c: dict(sorted(out[c].items())) for c in sorted(out)}


def _daily_breakdown(expenses, month):
    """Total spend per day (YYYY-MM-DD) within a single calendar month.

    The day-resolution complement to _monthly_breakdown: where that collapses a
    month to one number, this expands one month into its days. Only well-formed
    dates whose YYYY-MM prefix equals `month` are counted; days with no spend are
    omitted. Result is sorted ascending by date.
    """
    out = {}
    for e in expenses:
        date = str(e.get('date', ''))
        if not _valid_date(date) or date[:7] != month:
            continue
        out[date] = round(out.get(date, 0.0) + float(e.get('amount', 0) or 0), 2)
    return dict(sorted(out.items()))


def _category_averages(expenses):
    """Per-category count, total, and average expense amount.

    Complements _summarize's per-category total breakdown by adding the count
    and mean spend within each category, so the UI can answer "which category
    has the biggest *typical* expense" rather than just the biggest sum. Every
    known category appears (count 0 / average 0.0 when unused); unknown
    categories are ignored. Keyed in category-name order.
    """
    agg = {c: {'count': 0, 'total': 0.0} for c in CATEGORIES}
    for e in expenses:
        c = e.get('category')
        if c not in CATEGORIES:
            continue
        agg[c]['count'] += 1
        agg[c]['total'] = round(agg[c]['total'] + float(e.get('amount', 0) or 0), 2)
    out = {}
    for c in sorted(agg):
        cnt = agg[c]['count']
        tot = round(agg[c]['total'], 2)
        out[c] = {
            'count': cnt,
            'total': tot,
            'average': round(tot / cnt, 2) if cnt else 0.0,
        }
    return out


def _compare_months(expenses, month_a, month_b):
    """Compare total and per-category spend between two calendar months.

    Returns each month's total, the absolute delta (b - a), the percent change
    relative to month_a (None when month_a spent nothing — percent off a zero
    base is undefined), and a per-category {a, b, delta} table covering every
    known category in name order. month_a is the baseline / earlier month by
    convention, but the maths hold whichever order the caller passes.
    """
    def agg(month):
        total = 0.0
        cats = {c: 0.0 for c in CATEGORIES}
        for e in expenses:
            if str(e.get('date', ''))[:7] != month:
                continue
            amt = float(e.get('amount', 0) or 0)
            total += amt
            c = e.get('category')
            if c in cats:
                cats[c] = round(cats[c] + amt, 2)
        return round(total, 2), cats

    total_a, cats_a = agg(month_a)
    total_b, cats_b = agg(month_b)
    delta = round(total_b - total_a, 2)
    pct = round((delta / total_a) * 100, 2) if total_a else None
    categories = {}
    for c in sorted(CATEGORIES):
        ca, cb = cats_a[c], cats_b[c]
        categories[c] = {'a': ca, 'b': cb, 'delta': round(cb - ca, 2)}
    return {
        'month_a': month_a,
        'month_b': month_b,
        'total_a': total_a,
        'total_b': total_b,
        'delta': delta,
        'percent_change': pct,
        'categories': categories,
    }


def _iso_week_breakdown(expenses):
    """Group total spend by ISO week label (YYYY-Www), sorted ascending.

    The week-resolution sibling of _monthly_breakdown and _daily_breakdown:
    where those bucket by calendar month and day, this buckets by ISO week so
    the UI can chart week-over-week spend regardless of month boundaries (an
    ISO week can straddle two months). Only well-formed dates are counted; the
    label uses ISO year (which can differ from the calendar year for the first
    or last days of a year) so weeks never collide.
    """
    out = {}
    for e in expenses:
        date = str(e.get('date', ''))
        if not _valid_date(date):
            continue
        try:
            iso_y, iso_w, _ = datetime.date(
                int(date[:4]), int(date[5:7]), int(date[8:10])).isocalendar()
        except (ValueError, TypeError):
            continue
        key = '%04d-W%02d' % (iso_y, iso_w)
        out[key] = round(out.get(key, 0.0) + float(e.get('amount', 0) or 0), 2)
    return dict(sorted(out.items()))


def _category_percentages(expenses):
    """Each category's share of total spend as a percent (0..100).

    Complements _summarize's absolute per-category breakdown by normalizing it
    to proportions, so the UI can answer "what fraction of my spend is Food"
    without recomputing. Every known category appears (0.0 when unused or when
    nothing is spent overall). Percentages are rounded to two decimals and may
    not sum to exactly 100 due to rounding. Keyed in category-name order.
    """
    breakdown = {c: 0.0 for c in CATEGORIES}
    total = 0.0
    for e in expenses:
        c = e.get('category')
        if c not in CATEGORIES:
            continue
        amt = float(e.get('amount', 0) or 0)
        breakdown[c] = round(breakdown[c] + amt, 2)
        total += amt
    total = round(total, 2)
    out = {}
    for c in sorted(CATEGORIES):
        pct = round((breakdown[c] / total) * 100, 2) if total else 0.0
        out[c] = {'spent': breakdown[c], 'percent': pct}
    return {'total': total, 'categories': out}


def _top_expenses(expenses, n):
    """Return the n highest-amount expenses, largest first.

    The list-level companion to _largest_expense (which returns only the single
    biggest): handy for a "top spends" panel. Ties on amount are broken by date
    descending then id, so the ordering is deterministic. n is clamped to the
    available count; a non-positive n yields an empty list.
    """
    if n <= 0:
        return []
    ordered = sorted(
        expenses,
        key=lambda e: (float(e.get('amount', 0) or 0),
                       str(e.get('date', '')),
                       str(e.get('id', ''))),
        reverse=True,
    )
    return ordered[:n]


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


def _add_months(d, n):
    """Return date d shifted forward by n calendar months, clamping the day.

    Anchoring to a too-large day (e.g. the 31st) is clamped down to the last
    valid day of the target month (Jan 31 + 1mo -> Feb 28/29).
    """
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _occurrence(start_date, freq, k):
    """Return the k-th (0-based) occurrence date of a schedule.

    Anchored to start_date so occurrences never drift: daily adds k days,
    weekly adds k weeks, monthly adds k calendar months (day clamped).
    """
    if freq == 'daily':
        return start_date + datetime.timedelta(days=k)
    if freq == 'weekly':
        return start_date + datetime.timedelta(days=7 * k)
    return _add_months(start_date, k)


_MAX_OCCURRENCES = 100000


def _due_occurrences(start, freq, asof, after=None):
    """List occurrence date strings from `start` through `asof` (inclusive).

    Occurrences with a date <= `after` are skipped (used to avoid regenerating
    dates a template has already materialized). Returns [] if start is later
    than asof or any date is invalid. Capped at _MAX_OCCURRENCES for safety.
    """
    if not (_valid_date(start) and _valid_date(asof)):
        return []
    if freq not in RECUR_FREQS:
        return []
    sd = datetime.date(int(start[:4]), int(start[5:7]), int(start[8:10]))
    asof_d = datetime.date(int(asof[:4]), int(asof[5:7]), int(asof[8:10]))
    out = []
    for k in range(_MAX_OCCURRENCES):
        occ = _occurrence(sd, freq, k)
        if occ > asof_d:
            break
        occ_s = occ.isoformat()
        if after is None or occ_s > after:
            out.append(occ_s)
    return out


def _validate_recurring(amount, category, note, date, freq, tags=None):
    """Validate a recurring-template payload.

    Reuses _validate_fields for the shared expense fields (so a recurring
    template can never carry data the expense API would reject) and adds the
    frequency check. `date` is the schedule's anchor / first occurrence.
    Returns (cleaned_dict, None) or (None, error_message).
    """
    cleaned, err = _validate_fields(amount, category, note, date, tags)
    if err is not None:
        return None, err
    if freq not in RECUR_FREQS:
        return None, 'invalid freq (expected daily, weekly, or monthly)'
    cleaned['freq'] = freq
    cleaned['start'] = cleaned.pop('date')
    cleaned['last_generated'] = None
    return cleaned, None


def _load_recurring():
    """Return the saved recurring templates as a list (empty on missing/bad)."""
    if not os.path.exists(RECURRING_FILE):
        return []
    try:
        with open(RECURRING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (ValueError, OSError):
        return []


def _save_recurring(templates):
    with open(RECURRING_FILE, 'w', encoding='utf-8') as f:
        json.dump(templates, f, indent=2)


def _materialize_recurring(templates, expenses, asof):
    """Generate due expenses from recurring templates up to `asof`.

    For each template, every occurrence date strictly after its
    `last_generated` and on/before `asof` becomes a fresh expense (with its own
    id and a `recurring_id` back-link). Templates are mutated in place so their
    `last_generated` advances to the newest date emitted, making the operation
    idempotent: running again with the same asof generates nothing.

    Returns the list of newly created expense dicts (also appended to
    `expenses`). Does not persist — the caller owns I/O.
    """
    generated = []
    for tmpl in templates:
        freq = tmpl.get('freq')
        start = tmpl.get('start')
        last = tmpl.get('last_generated')
        dates = _due_occurrences(start, freq, asof, after=last)
        if not dates:
            continue
        for d in dates:
            exp = {
                'id': uuid.uuid4().hex,
                'amount': tmpl.get('amount'),
                'category': tmpl.get('category'),
                'note': tmpl.get('note', ''),
                'date': d,
                'tags': list(tmpl.get('tags') or []),
                'recurring_id': tmpl.get('id'),
            }
            expenses.append(exp)
            generated.append(exp)
        tmpl['last_generated'] = dates[-1]
    return generated


def _outliers(expenses, threshold=2.0):
    """Flag expenses that are unusually large for their own category.

    Within each category, an expense is an outlier when its amount exceeds
    `threshold` times that category's median amount. Using the median (not the
    mean) as the yardstick means one giant expense can't inflate the baseline
    and hide itself — the very behaviour we want to surface. With `threshold`
    >= 1 a category of one can never flag itself (its amount equals its own
    median), so there are no false positives on sparse data. This complements
    _category_averages (typical spend) and _stats (overall min/max/median) by
    answering "which individual expenses don't fit their category's pattern".

    Returns a list of expense dicts (the originals, augmented with
    `category_median` and `ratio` = amount / median), largest ratio first then
    amount, so the most surprising spends sort to the top. Bad/non-positive
    medians (a category whose median is 0) are skipped — nothing to compare to.
    """
    by_cat = {}
    for e in expenses:
        cat = e.get('category')
        if cat not in CATEGORIES:
            continue
        by_cat.setdefault(cat, []).append(e)
    out = []
    for cat, items in by_cat.items():
        med = _median([e.get('amount', 0) or 0 for e in items])
        if not med or med <= 0:
            continue
        for e in items:
            amt = float(e.get('amount', 0) or 0)
            if amt > threshold * med:
                flagged = dict(e)
                flagged['category_median'] = med
                flagged['ratio'] = round(amt / med, 2)
                out.append(flagged)
    out.sort(key=lambda e: (-e['ratio'], -float(e.get('amount', 0) or 0)))
    return out


def _find_duplicates(expenses):
    """Group expenses that look like accidental double-entries.

    Two expenses are considered likely duplicates when they share the same
    amount, category, and date. Each returned group lists every member so the
    UI can offer "you may have entered this twice — delete the extras" (pairs
    nicely with the existing bulk-delete endpoint). Groups of one are not
    duplicates and are omitted.

    Returns a list of {amount, category, date, count, ids, expenses} groups
    sorted by count desc, then amount desc, then category/date, so the most
    duplicated and most expensive collisions surface first. Deterministic.
    """
    groups = {}
    for e in expenses:
        key = (round(float(e.get('amount', 0) or 0), 2),
               e.get('category', ''),
               e.get('date', ''))
        groups.setdefault(key, []).append(e)
    out = []
    for (amount, category, date), members in groups.items():
        if len(members) < 2:
            continue
        out.append({
            'amount': amount,
            'category': category,
            'date': date,
            'count': len(members),
            'ids': [m.get('id') for m in members],
            'expenses': members,
        })
    out.sort(key=lambda g: (-g['count'], -g['amount'], g['category'], g['date']))
    return out


def _recategorize(expenses, src, dst):
    """Move every expense in category `src` into category `dst` in place.

    The bulk-write companion to _find_duplicates' detection: a single O(n) pass
    that relabels a whole category (e.g. you decide all "Fun" should have been
    "Other"). Mutates the matched expenses' `category` field directly and
    returns the list of ids actually changed. When src == dst nothing changes
    and the list is empty, so a no-op move is reported honestly. The caller owns
    persistence.
    """
    changed = []
    if src == dst:
        return changed
    for e in expenses:
        if e.get('category') == src:
            e['category'] = dst
            changed.append(e.get('id'))
    return changed


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
        if parsed.path == '/api/summary/category-monthly':
            with _lock:
                expenses = _load()
            self._send_json({'category_monthly': _category_monthly(expenses)})
            return
        if parsed.path == '/api/summary/daily':
            qs = parse_qs(parsed.query)
            month = qs.get('month', [None])[0]
            if month is None or not _valid_month(month):
                self._send_json({'error': 'month must be a valid month (YYYY-MM)'}, 400)
                return
            with _lock:
                expenses = _load()
            self._send_json({'month': month, 'daily': _daily_breakdown(expenses, month)})
            return
        if parsed.path == '/api/summary/category-averages':
            with _lock:
                expenses = _load()
            self._send_json({'category_averages': _category_averages(expenses)})
            return
        if parsed.path == '/api/summary/weekly':
            with _lock:
                expenses = _load()
            self._send_json({'weekly': _iso_week_breakdown(expenses)})
            return
        if parsed.path == '/api/summary/percentages':
            with _lock:
                expenses = _load()
            self._send_json({'percentages': _category_percentages(expenses)})
            return
        if parsed.path == '/api/summary/outliers':
            qs = parse_qs(parsed.query)
            t_raw = qs.get('threshold', ['2.0'])[0]
            try:
                threshold = float(t_raw)
            except (TypeError, ValueError):
                self._send_json({'error': 'threshold must be a number'}, 400)
                return
            if threshold < 1:
                self._send_json({'error': 'threshold must be at least 1'}, 400)
                return
            with _lock:
                expenses = _load()
            self._send_json({
                'threshold': threshold,
                'outliers': _outliers(expenses, threshold),
            })
            return
        if parsed.path == '/api/summary/duplicates':
            with _lock:
                expenses = _load()
            self._send_json({'duplicates': _find_duplicates(expenses)})
            return
        if parsed.path == '/api/summary/top':
            qs = parse_qs(parsed.query)
            n_raw = qs.get('n', ['5'])[0]
            try:
                n = int(n_raw)
            except (TypeError, ValueError):
                self._send_json({'error': 'n must be an integer'}, 400)
                return
            if n < 1:
                self._send_json({'error': 'n must be at least 1'}, 400)
                return
            with _lock:
                expenses = _load()
            self._send_json({'top': _top_expenses(expenses, n)})
            return
        if parsed.path == '/api/summary/compare':
            qs = parse_qs(parsed.query)
            a = qs.get('a', [None])[0]
            b = qs.get('b', [None])[0]
            if a is None or not _valid_month(a):
                self._send_json({'error': 'a must be a valid month (YYYY-MM)'}, 400)
                return
            if b is None or not _valid_month(b):
                self._send_json({'error': 'b must be a valid month (YYYY-MM)'}, 400)
                return
            with _lock:
                expenses = _load()
            self._send_json({'compare': _compare_months(expenses, a, b)})
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
        if parsed.path == '/api/summary/pace':
            qs = parse_qs(parsed.query)
            asof = qs.get('asof', [None])[0]
            if asof is None or not _valid_date(asof):
                self._send_json({'error': 'asof must be a valid date (YYYY-MM-DD)'}, 400)
                return
            with _lock:
                expenses = _load()
                budget = _load_budget()
            self._send_json({'pace': _budget_pace(expenses, budget, asof)})
            return
        if parsed.path == '/api/budgets/categories':
            with _lock:
                cat_budgets = _load_cat_budgets()
            self._send_json({'categories': cat_budgets})
            return
        if parsed.path == '/api/recurring':
            with _lock:
                templates = _load_recurring()
            self._send_json({'recurring': templates})
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
            min_raw = qs.get('min_amount', [None])[0]
            max_raw = qs.get('max_amount', [None])[0]

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

            min_amount = None
            max_amount = None
            if min_raw is not None:
                try:
                    min_amount = float(min_raw)
                except (TypeError, ValueError):
                    self._send_json({'error': 'min_amount must be a number'}, 400)
                    return
                if min_amount < 0:
                    self._send_json({'error': 'min_amount must not be negative'}, 400)
                    return
            if max_raw is not None:
                try:
                    max_amount = float(max_raw)
                except (TypeError, ValueError):
                    self._send_json({'error': 'max_amount must be a number'}, 400)
                    return
                if max_amount < 0:
                    self._send_json({'error': 'max_amount must not be negative'}, 400)
                    return
            if (min_amount is not None and max_amount is not None
                    and min_amount > max_amount):
                self._send_json(
                    {'error': 'min_amount must not exceed max_amount'}, 400)
                return

            with _lock:
                expenses = _load()
                budget = _load_budget()
                cat_budgets = _load_cat_budgets()
            filtered = _filter_expenses(expenses, category, start, end, query, tag,
                                        min_amount, max_amount)
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
        if self.path == '/api/expenses/bulk-delete':
            self._handle_bulk_delete()
            return
        if self.path == '/api/expenses/recategorize':
            self._handle_recategorize()
            return
        if self.path == '/api/recurring':
            self._handle_recurring_create()
            return
        if self.path == '/api/recurring/run':
            self._handle_recurring_run()
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

    def _handle_bulk_delete(self):
        """Delete many expenses in one request.

        Body: {"ids": ["id1", "id2", ...]}. Returns
        {"deleted": [...], "not_found": [...], "count": N} where deleted holds
        the ids actually removed (in request order, de-duplicated) and
        not_found holds requested ids that didn't match any expense. A single
        pass over the store makes this O(n) rather than one DELETE per id. An
        empty or missing list deletes nothing and is not an error; a non-list
        ids field is a 400.
        """
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        ids = data.get('ids')
        if ids is None:
            ids = []
        if not isinstance(ids, list):
            self._send_json({'error': 'ids must be a list'}, 400)
            return
        # Preserve request order, drop duplicates and non-strings.
        wanted = []
        seen = set()
        for i in ids:
            if isinstance(i, str) and i not in seen:
                seen.add(i)
                wanted.append(i)
        with _lock:
            expenses = _load()
            present = {e['id'] for e in expenses}
            deleted = [i for i in wanted if i in present]
            not_found = [i for i in wanted if i not in present]
            if deleted:
                drop = set(deleted)
                _save([e for e in expenses if e['id'] not in drop])
        self._send_json({
            'deleted': deleted,
            'not_found': not_found,
            'count': len(deleted),
        }, 200)

    def _handle_recategorize(self):
        """Bulk-move every expense from one category to another.

        Body: {"from": "<category>", "to": "<category>"}. Both must be known
        categories. Returns {"moved": N, "from": src, "to": dst, "ids": [...]}
        listing the ids relabelled. A src==dst request is valid and a no-op
        (moved 0). One pass over the store, persisted only when something
        actually changed.
        """
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        src = data.get('from')
        dst = data.get('to')
        if src not in CATEGORIES:
            self._send_json({'error': 'invalid from category'}, 400)
            return
        if dst not in CATEGORIES:
            self._send_json({'error': 'invalid to category'}, 400)
            return
        with _lock:
            expenses = _load()
            changed = _recategorize(expenses, src, dst)
            if changed:
                _save(expenses)
        self._send_json({
            'moved': len(changed),
            'from': src,
            'to': dst,
            'ids': changed,
        }, 200)

    def _handle_recurring_create(self):
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        cleaned, error = _validate_recurring(
            data.get('amount'),
            data.get('category'),
            data.get('note', ''),
            data.get('date'),
            data.get('freq'),
            data.get('tags'),
        )
        if error is not None:
            self._send_json({'error': error}, 400)
            return
        template = {'id': uuid.uuid4().hex}
        template.update(cleaned)
        with _lock:
            templates = _load_recurring()
            templates.append(template)
            _save_recurring(templates)
        self._send_json(template, 201)

    def _handle_recurring_run(self):
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        asof = data.get('asof')
        if not _valid_date(asof):
            self._send_json({'error': 'asof must be a valid date (YYYY-MM-DD)'}, 400)
            return
        with _lock:
            templates = _load_recurring()
            expenses = _load()
            generated = _materialize_recurring(templates, expenses, asof)
            if generated:
                _save(expenses)
                _save_recurring(templates)
        self._send_json({
            'generated': len(generated),
            'expenses': generated,
            'recurring': templates,
        }, 200)

    def _handle_recurring_put(self, rid):
        """Partial update of a recurring template.

        Provided fields override; omitted ones keep their current value (the
        `date` field maps to the schedule's `start` anchor). Re-validated with
        the same _validate_recurring rules as create so an edit can never make a
        template the create endpoint would have rejected. The template's id and
        its `last_generated` watermark are preserved across the edit, so editing
        (e.g.) the amount never re-materializes already-generated occurrences.
        """
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return
        with _lock:
            templates = _load_recurring()
            target = next((t for t in templates if t.get('id') == rid), None)
            if target is None:
                self._send_json({'error': 'recurring template not found'}, 404)
                return
            cleaned, error = _validate_recurring(
                data.get('amount', target.get('amount')),
                data.get('category', target.get('category')),
                data.get('note', target.get('note', '')),
                data.get('date', target.get('start')),
                data.get('freq', target.get('freq')),
                data.get('tags', target.get('tags', [])),
            )
            if error is not None:
                self._send_json({'error': error}, 400)
                return
            # _validate_recurring resets last_generated to None; keep the
            # template's real watermark so edits don't regenerate history.
            cleaned['last_generated'] = target.get('last_generated')
            target.update(cleaned)
            updated = dict(target)
            _save_recurring(templates)
        self._send_json(updated, 200)

    def do_PUT(self):
        if urlparse(self.path).path == '/api/budget':
            self._handle_budget_put()
            return
        if urlparse(self.path).path == '/api/budgets/categories':
            self._handle_cat_budget_put()
            return
        rec_prefix = '/api/recurring/'
        if urlparse(self.path).path.startswith(rec_prefix):
            rid = urlparse(self.path).path[len(rec_prefix):]
            self._handle_recurring_put(rid)
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
        amount = self._parse_budget_amount(raw)
        if amount is None:
            return
        with _lock:
            _save_budget(amount)
        self._send_json({'budget': amount}, 200)

    def _parse_budget_amount(self, raw):
        """Validate a budget value (numeric, non-negative) and return it rounded
        to cents. On failure, send the 400 and return None. Shared by the global
        and per-category budget endpoints so the validation lives in one place."""
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            self._send_json({'error': 'budget must be a number'}, 400)
            return None
        if amount < 0:
            self._send_json({'error': 'budget must not be negative'}, 400)
            return None
        return round(amount, 2)

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
            amount = self._parse_budget_amount(raw)
            if amount is None:
                return
            budgets[cat] = amount
            _save_cat_budgets(budgets)
        self._send_json({'categories': budgets}, 200)

    def do_DELETE(self):
        rec_prefix = '/api/recurring/'
        if self.path.startswith(rec_prefix):
            rid = self.path[len(rec_prefix):]
            with _lock:
                templates = _load_recurring()
                new = [t for t in templates if t.get('id') != rid]
                if len(new) == len(templates):
                    self._send_json({'error': 'recurring template not found'}, 404)
                    return
                _save_recurring(new)
            self._send_json({'deleted': rid})
            return
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

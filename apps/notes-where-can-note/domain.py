"""Pure domain logic for the Notes app.

No I/O, no HTTP, no globals — every function operates on plain lists/dicts so it
can be unit-tested in isolation and reused by any transport (the std-lib HTTP
server here, a CLI, a future API, etc.). server.py owns persistence and wiring.

A note is a dict with this shape:

    {
        "id": int,
        "text": str,
        "tags": [str, ...],     # normalized: lowercased, stripped, unique, sorted
        "pinned": bool,
        "archived": bool,
        "created_at": int,      # epoch seconds
        "updated_at": int,      # epoch seconds
    }

Older notes persisted before tags/pinned/archived existed simply lack those keys;
every accessor below reads them with a safe default so old data keeps working.
"""

MAX_TEXT_LEN = 10000
MAX_TAG_LEN = 40
MAX_TAGS = 25

# Allowed note colors. 'default' is the neutral card; the rest are accent
# labels a user can apply for quick visual grouping. Kept as a closed set so
# the UI palette and the validator can never drift apart.
NOTE_COLORS = (
    'default', 'red', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink',
)


class ValidationError(ValueError):
    """Raised when an input fails a domain rule. Carries a human-readable message."""


# --- field accessors (tolerate notes missing the newer keys) -----------------

def note_tags(note):
    tags = note.get('tags')
    return list(tags) if isinstance(tags, list) else []


def is_pinned(note):
    return bool(note.get('pinned', False))


def is_archived(note):
    return bool(note.get('archived', False))


def note_color(note):
    """The note's color label, falling back to 'default' for old/invalid data."""
    c = note.get('color')
    return c if c in NOTE_COLORS else 'default'


def note_due(note):
    """The note's due timestamp (epoch seconds) or None if unset/legacy/invalid."""
    d = note.get('due_at')
    return d if isinstance(d, int) and d >= 0 else None


# --- validation / normalization ----------------------------------------------

def clean_text(text):
    """Validate and normalize note text. Raises ValidationError on bad input."""
    if not isinstance(text, str):
        raise ValidationError('note text is required')
    stripped = text.strip()
    if not stripped:
        raise ValidationError('note text is required')
    if len(stripped) > MAX_TEXT_LEN:
        raise ValidationError('note text is too long (max %d chars)' % MAX_TEXT_LEN)
    return stripped


def normalize_tags(tags):
    """Lowercase, strip, drop empties, de-duplicate and sort a list of tags.

    Accepts a list of strings. Returns a sorted list of unique normalized tags.
    Raises ValidationError if the input isn't a list of strings or limits are hit.
    """
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise ValidationError('tags must be a list of strings')
    seen = set()
    for t in tags:
        if not isinstance(t, str):
            raise ValidationError('tags must be a list of strings')
        norm = t.strip().lower()
        if not norm:
            continue
        if len(norm) > MAX_TAG_LEN:
            raise ValidationError('tag is too long (max %d chars)' % MAX_TAG_LEN)
        seen.add(norm)
    if len(seen) > MAX_TAGS:
        raise ValidationError('too many tags (max %d)' % MAX_TAGS)
    return sorted(seen)


def clean_color(color):
    """Validate/normalize a color label. None or '' -> 'default'.

    Raises ValidationError for a non-string or an unknown color.
    """
    if color is None:
        return 'default'
    if not isinstance(color, str):
        raise ValidationError('color must be a string')
    norm = color.strip().lower()
    if not norm:
        return 'default'
    if norm not in NOTE_COLORS:
        raise ValidationError('unknown color (allowed: %s)' % ', '.join(NOTE_COLORS))
    return norm


def clean_due(value):
    """Validate/normalize a due timestamp. None/'' -> None (no due date).

    Accepts an int (epoch seconds) or a numeric string. Raises ValidationError
    for a negative value or anything that isn't a whole number of seconds.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        raise ValidationError('due date must be an epoch timestamp')
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = int(stripped)
        except ValueError:
            raise ValidationError('due date must be an epoch timestamp')
    if not isinstance(value, int):
        raise ValidationError('due date must be an epoch timestamp')
    if value < 0:
        raise ValidationError('due date must not be negative')
    return value


# --- construction / mutation --------------------------------------------------

def make_note(note_id, text, tags, ts, color=None, due=None):
    """Build a fully-formed note dict. text/tags/color/due validated here."""
    return {
        'id': note_id,
        'text': clean_text(text),
        'tags': normalize_tags(tags),
        'color': clean_color(color),
        'due_at': clean_due(due),
        'pinned': False,
        'archived': False,
        'created_at': ts,
        'updated_at': ts,
    }


def apply_update(note, fields, ts):
    """Partially update a note in place from a dict of incoming fields.

    Supported fields: text (non-empty str), tags (list), pinned (bool),
    archived (bool). Unknown keys are ignored. Returns True if anything changed
    (and bumps updated_at when it does). Raises ValidationError on bad values.
    """
    if not isinstance(fields, dict):
        raise ValidationError('invalid update body')

    changed = False

    if 'text' in fields:
        new_text = clean_text(fields['text'])
        if new_text != note.get('text'):
            note['text'] = new_text
            changed = True

    if 'tags' in fields:
        new_tags = normalize_tags(fields['tags'])
        if new_tags != note_tags(note):
            note['tags'] = new_tags
            changed = True

    if 'color' in fields:
        new_color = clean_color(fields['color'])
        if new_color != note_color(note):
            note['color'] = new_color
            changed = True

    for flag in ('pinned', 'archived'):
        if flag in fields:
            val = fields[flag]
            if not isinstance(val, bool):
                raise ValidationError('%s must be a boolean' % flag)
            if val != bool(note.get(flag, False)):
                note[flag] = val
                changed = True

    if changed:
        note['updated_at'] = ts
    return changed


# --- querying / projection ----------------------------------------------------

def matches_search(note, query):
    """Case-insensitive substring match over text AND tags."""
    if not query:
        return True
    q = query.strip().lower()
    if not q:
        return True
    if q in str(note.get('text', '')).lower():
        return True
    return any(q in t for t in note_tags(note))


def filter_notes(notes, query=None, tag=None, archived='active'):
    """Filter notes by search query, exact tag, and archived state.

    archived: 'active' (exclude archived, the default), 'only' (archived only),
    or 'all' (both).
    """
    tag_norm = tag.strip().lower() if isinstance(tag, str) and tag.strip() else None
    out = []
    for n in notes:
        if archived == 'active' and is_archived(n):
            continue
        if archived == 'only' and not is_archived(n):
            continue
        if tag_norm is not None and tag_norm not in note_tags(n):
            continue
        if not matches_search(n, query):
            continue
        out.append(n)
    return out


def sort_notes(notes):
    """Pinned notes first, then most-recently-updated first, then highest id.

    Returns a new list; does not mutate the input order.
    """
    return sorted(
        notes,
        key=lambda n: (
            0 if is_pinned(n) else 1,
            -int(n.get('updated_at', n.get('created_at', 0)) or 0),
            -int(n.get('id', 0) or 0),
        ),
    )


def collect_tags(notes):
    """Distinct tags across all notes with their usage counts, sorted by tag."""
    counts = {}
    for n in notes:
        for t in note_tags(n):
            counts[t] = counts.get(t, 0) + 1
    return [{'tag': t, 'count': counts[t]} for t in sorted(counts)]


def compute_stats(notes):
    """Aggregate counts for the collection."""
    total = len(notes)
    pinned = sum(1 for n in notes if is_pinned(n))
    archived = sum(1 for n in notes if is_archived(n))
    words = sum(count_words(n.get('text', '')) for n in notes)
    chars = sum(len(str(n.get('text', ''))) for n in notes)
    return {
        'total': total,
        'active': total - archived,
        'pinned': pinned,
        'archived': archived,
        'tags': len(collect_tags(notes)),
        'words': words,
        'chars': chars,
    }


# --- counting / duplication / export -----------------------------------------

def count_words(text):
    """Number of whitespace-separated words in a piece of text."""
    if not isinstance(text, str):
        return 0
    return len(text.split())


def duplicate_note(note, new_id, ts):
    """Build a fresh copy of an existing note.

    The copy keeps the source text, tags and color but starts life unpinned and
    unarchived with brand-new timestamps, exactly like a hand-created note.
    Raises ValidationError if the source text is missing/empty.
    """
    return make_note(new_id, note.get('text', ''), note_tags(note), ts,
                     color=note_color(note))


def export_bundle(notes, ts):
    """Build a portable, self-describing export of every note.

    Returns a dict carrying the full note list, a count, and an export
    timestamp so an importer can verify it round-tripped intact.
    """
    return {
        'version': 1,
        'exported_at': ts,
        'count': len(notes),
        'notes': list(notes),
    }


def import_notes(existing, bundle, start_id, ts):
    """Merge the notes from an export bundle into ``existing``.

    Every imported note is given a fresh sequential id starting at ``start_id``
    so it can never collide with a note already present. Text/tags/color are
    re-validated; the pinned/archived flags and original timestamps are carried
    over when present and well-formed (falling back to ``ts`` otherwise).

    Returns ``(merged_notes, next_id, imported_count)``. Raises ValidationError
    if the bundle isn't shaped like an export (a dict carrying a notes list) or
    any note inside it is invalid.
    """
    if not isinstance(bundle, dict):
        raise ValidationError('invalid import bundle')
    incoming = bundle.get('notes')
    if not isinstance(incoming, list):
        raise ValidationError('import bundle has no notes list')

    merged = list(existing)
    next_id = start_id
    imported = 0
    for raw in incoming:
        if not isinstance(raw, dict):
            raise ValidationError('each imported note must be an object')
        note = make_note(next_id, raw.get('text', ''), note_tags(raw), ts,
                         color=raw.get('color'))
        note['pinned'] = bool(raw.get('pinned', False))
        note['archived'] = bool(raw.get('archived', False))
        created = raw.get('created_at')
        updated = raw.get('updated_at')
        if isinstance(created, int):
            note['created_at'] = created
        if isinstance(updated, int):
            note['updated_at'] = updated
        merged.append(note)
        next_id += 1
        imported += 1
    return merged, next_id, imported


def rename_tag(notes, old, new, ts):
    """Rename (or, with an empty ``new``, remove) a tag across every note.

    Matching is done on the normalized form of ``old``. A note that carries the
    tag has it swapped for the normalized ``new`` (deduped/sorted with its other
    tags) and its ``updated_at`` bumped. Returns the number of notes changed.
    Raises ValidationError on a missing original tag or an invalid new tag.
    """
    if not isinstance(old, str) or not old.strip():
        raise ValidationError('original tag is required')
    old_norm = old.strip().lower()
    if new is not None and not isinstance(new, str):
        raise ValidationError('new tag must be a string')
    new_norm = new.strip().lower() if isinstance(new, str) else ''
    if len(new_norm) > MAX_TAG_LEN:
        raise ValidationError('tag is too long (max %d chars)' % MAX_TAG_LEN)

    changed = 0
    for n in notes:
        tags = note_tags(n)
        if old_norm not in tags:
            continue
        kept = {t for t in tags if t != old_norm}
        if new_norm:
            kept.add(new_norm)
        n['tags'] = sorted(kept)
        n['updated_at'] = ts
        changed += 1
    return changed

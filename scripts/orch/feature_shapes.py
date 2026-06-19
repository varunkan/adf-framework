#!/usr/bin/env python3
"""DET-2: deterministic feature-shape classifier + skeleton contract.

The highest-variance surface when generating an app is the schema + REST routes +
data-hook wiring: two runs of the same prompt can pick different table shapes,
route verbs, and hook signatures. This module removes that variance DETERMINISTICALLY.

`classify()` reads the spec/requirement text and picks one of a small set of
*shapes* (crud-list / form / dashboard / single-record / generic) using a fixed,
keyword-scored rule with a stable tie-break — same text always yields the same
shape. `skeleton_contract()` then emits a precise per-shape contract (exact files,
route signatures, hook shape) that is injected into the build prompt, so the model
fills DOMAIN logic into a fixed skeleton instead of re-deciding boilerplate. The
result: less variance, fewer tokens, and apps that compose the shipped `ui/`
primitives the same way every time.

No model call, no network — pure string analysis, so it is fully testable.
"""
import re
import sys

# Priority order is also the tie-break order: when two shapes score equally, the
# earlier one wins. crud-list is first because it is the most common app shape and
# the safest default skeleton.
SHAPES = ("crud-list", "auth", "form", "dashboard", "single-record")

# Per-shape keyword signals: (keyword, weight). Distinctive nouns weigh more than
# generic CRUD verbs (which can appear in any feature). Matched case-insensitively
# on word boundaries; multi-word keywords match across a single space.
_KEYWORDS = {
    "crud-list": [
        ("crud", 3), ("to-do", 3), ("todo", 3), ("to do list", 3),
        ("inventory", 3), ("catalog", 3), ("manage", 2), ("list of", 2),
        ("items", 2), ("entries", 2), ("records", 2), ("tasks", 2),
        ("notes", 2), ("contacts", 2), ("collection", 2),
        ("add", 1), ("edit", 1), ("update", 1), ("delete", 1), ("remove", 1),
        ("create", 1), ("list", 1),
    ],
    "form": [
        ("contact form", 3), ("sign up", 3), ("signup", 3), ("registration", 3),
        ("survey", 3), ("feedback", 3), ("questionnaire", 3), ("rsvp", 3),
        ("subscribe", 3), ("booking", 3), ("application form", 3), ("poll", 2),
        ("submit", 2), ("submission", 2), ("register", 2), ("apply", 2),
        ("enroll", 2), ("form", 2),
    ],
    "dashboard": [
        ("dashboard", 3), ("analytics", 3), ("metrics", 3), ("kpi", 3),
        ("leaderboard", 3), ("visualize", 3), ("visualization", 3),
        ("statistics", 2), ("stats", 2), ("chart", 2), ("charts", 2),
        ("report", 2), ("reports", 2), ("summary", 2), ("overview", 2),
        ("trend", 2), ("trends", 2), ("insights", 2), ("graph", 2),
    ],
    "single-record": [
        ("settings", 3), ("preferences", 3), ("configuration", 3),
        ("profile", 3), ("single record", 3), ("counter", 3), ("toggle", 2),
        ("config", 2), ("account", 2), ("the current value", 2),
    ],
    "auth": [
        ("authentication", 3), ("authenticate", 3), ("login", 3), ("log in", 3),
        ("sign in", 3), ("sign-in", 3), ("signin", 3), ("logout", 2),
        ("log out", 2), ("sign out", 2), ("session", 2), ("sessions", 2),
        ("credentials", 2), ("logged in", 2), ("jwt", 2), ("oauth", 2),
    ],
}

_DEFAULT = "generic"


def _compiled():
    out = {}
    for shape, kws in _KEYWORDS.items():
        out[shape] = [(re.compile(r"\b" + re.escape(kw).replace(r"\ ", r"\s+") +
                                  r"\b", re.I), w) for kw, w in kws]
    return out


_PATTERNS = _compiled()


def score(text):
    """Per-shape match score for `text` (deterministic). Higher = stronger fit."""
    text = text or ""
    scores = {s: 0 for s in SHAPES}
    for shape, pats in _PATTERNS.items():
        for pat, weight in pats:
            scores[shape] += weight * len(pat.findall(text))
    return scores


def classify(text):
    """The single best-fitting shape for `text`, or 'generic' if nothing matches.
    Ties break by SHAPES order, so the result is fully deterministic."""
    scores = score(text)
    best = max(SHAPES, key=lambda s: (scores[s], -SHAPES.index(s)))
    return best if scores[best] > 0 else _DEFAULT


def _ctx_text(ctx):
    """The combined spec/requirement text the classifier reads."""
    if not ctx:
        return ""
    return "\n".join(
        str(ctx.get(k) or "")
        for k in ("requirement", "problem", "spec", "plan", "tasks"))


# --- per-shape skeleton contracts ------------------------------------------
# Each is a prompt fragment pinning the EXACT files/routes/hook for the shape.
# `<entities>` / `<Feature>` are placeholders the model fills with the domain noun.
_CONTRACTS = {
    "crud-list": (
        "DETECTED FEATURE SHAPE: crud-list — a collection the user lists, adds "
        "to, edits, and removes. Implement this EXACT skeleton (fill the domain "
        "fields/noun; do not invent a different structure):\n"
        "- schema.sql: one table for the entity with `id INTEGER PRIMARY KEY "
        "AUTOINCREMENT`, the spec's columns, and `created_at TEXT`.\n"
        "- server/api/<feature>.mjs routes (relative to /api):\n"
        "    GET    '/<entities>'      -> 200 all rows (newest first)\n"
        "    POST   '/<entities>'      -> 201 created row (400 on missing/invalid)\n"
        "    PUT    '/<entities>/:id'  -> 200 updated row (404 if id absent)\n"
        "    DELETE '/<entities>/:id'  -> 200 { ok: true } (404 if id absent)\n"
        "- src/hooks/use<Feature>.ts: returns "
        "`{ items, loading, error, create, update, remove, reload }`, each calling "
        "fetch('/api/<entities>').\n"
        "- src/components: a `<Feature>List` (renders items, a Card per row with "
        "edit/delete) and a `<Feature>Form` (controlled Inputs + a Button to add); "
        "App.tsx composes them.\n"
        "- test: GET empty -> [], POST valid -> 201 and appears in GET, POST "
        "invalid -> 400, DELETE missing id -> 404."
    ),
    "form": (
        "DETECTED FEATURE SHAPE: form — the user submits entries that are recorded "
        "(typically not edited). Implement this EXACT skeleton:\n"
        "- schema.sql: one table for the submission with `id INTEGER PRIMARY KEY "
        "AUTOINCREMENT`, the form fields, and `created_at TEXT`.\n"
        "- server/api/<feature>.mjs routes (relative to /api):\n"
        "    POST '/<submissions>' -> 201 created (400 when a required field is "
        "missing/invalid)\n"
        "    GET  '/<submissions>' -> 200 list (for confirmation/admin)\n"
        "  Add PUT/DELETE ONLY if the spec explicitly asks.\n"
        "- src/hooks/use<Feature>.ts: returns "
        "`{ submit, submitting, error, success }`.\n"
        "- src/components: a `<Feature>Form` (controlled fields with required "
        "validation + a Button) and a `<Feature>Success` confirmation; App.tsx "
        "shows the form, then the confirmation after a successful submit.\n"
        "- test: POST valid -> 201, POST missing required field -> 400, GET "
        "returns the stored row."
    ),
    "dashboard": (
        "DETECTED FEATURE SHAPE: dashboard — read-mostly metrics/aggregates over "
        "stored data. Implement this EXACT skeleton:\n"
        "- schema.sql: the source table(s) the metrics aggregate (plus an insert "
        "path only if the spec records data).\n"
        "- server/api/<feature>.mjs routes (relative to /api):\n"
        "    GET '/<feature>/summary' -> 200 aggregated metrics computed IN SQL "
        "(COUNT/SUM/AVG/GROUP BY), zeros (not an error) on an empty DB\n"
        "    GET '/<entities>'        -> 200 raw rows (if the UI shows a list)\n"
        "- src/hooks/use<Feature>.ts: returns `{ summary, loading, error, reload }`.\n"
        "- src/components: one stat `Card` per metric and a simple list/table. Do "
        "NOT add a chart library — draw bars with Tailwind-sized divs.\n"
        "- test: seed rows then GET summary asserts the computed aggregate; empty "
        "DB returns zeros."
    ),
    "auth": (
        "DETECTED FEATURE SHAPE: auth — users sign up and log in; sessions gate "
        "protected actions. Use the SHIPPED auth primitives — do NOT roll your own "
        "crypto. Implement this EXACT skeleton:\n"
        "- schema.sql: a `users` table with `id INTEGER PRIMARY KEY AUTOINCREMENT`, "
        "a UNIQUE email (or username), a `password_hash` column (NEVER store a "
        "plaintext password — the policy gate fails the build if you do), and "
        "`created_at TEXT`.\n"
        "- server/api/<feature>.mjs (routes relative to /api), importing "
        "`{ hashPassword, verifyPassword, signToken, verifyToken } from '../auth.mjs'`:\n"
        "    POST '/signup' -> 201 { token } (400 missing/invalid; 409 if the email "
        "exists); store hashPassword(password).\n"
        "    POST '/login'  -> 200 { token } when verifyPassword passes, else 401.\n"
        "    GET  '/me'     -> 200 the current user when the Bearer token "
        "verifyToken()s, else 401.\n"
        "- src/hooks/use<Feature>.ts: returns "
        "`{ user, loading, error, signup, login, logout }`; persists the token and "
        "sends it as an `Authorization: Bearer` header.\n"
        "- src/components: a `<LoginForm>` and a `<SignupForm>` (controlled email + "
        "password Inputs + a Button); App.tsx shows the authed view once `user` is set.\n"
        "- test: signup -> 201, duplicate signup -> 409, login wrong password -> 401, "
        "login correct -> 200 with a token, and GET /me with no token -> 401. NEVER "
        "assert a plaintext password is stored."
    ),
    "single-record": (
        "DETECTED FEATURE SHAPE: single-record — ONE persistent record the user "
        "views and updates in place (settings/profile/counter). Implement this "
        "EXACT skeleton:\n"
        "- schema.sql: a table holding a single fixed row (id = 1); seed the "
        "default row with `INSERT OR IGNORE`.\n"
        "- server/api/<feature>.mjs routes (relative to /api):\n"
        "    GET '/<feature>' -> 200 the record (create the default if absent)\n"
        "    PUT '/<feature>' -> 200 the updated record (400 on invalid)\n"
        "  No list/create/delete.\n"
        "- src/hooks/use<Feature>.ts: returns `{ record, loading, error, save }`.\n"
        "- src/components: a `<Feature>Panel` showing the current values as "
        "editable Inputs with a Button to save.\n"
        "- test: GET returns the default, PUT updates and persists, PUT invalid "
        "-> 400."
    ),
}


# Mobile (no-server) overrides: a contract that references server routes / shipped
# server primitives is INCOHERENT on the Expo stack (there is no server, no auth.mjs).
# These replace such contracts with an on-device, expo-sqlite version.
_MOBILE_CONTRACTS = {
    "auth": (
        "DETECTED FEATURE SHAPE: auth (MOBILE, no server) — users sign up and log in; "
        "the users table lives in expo-sqlite and the session is kept ON-DEVICE. There "
        "is NO server and NO `auth.mjs` — do NOT import server crypto. Implement:\n"
        "- src/db.ts: a `users` table — id INTEGER PRIMARY KEY AUTOINCREMENT, a UNIQUE "
        "`email`, a `password_hash` column (NEVER a plaintext password — the policy "
        "gate fails the build), `created_at TEXT`.\n"
        "- CRYPTO: IMPORT the SHIPPED, TESTED primitive — "
        "`import { hashPassword, verifyPassword, generateToken } from '../auth'` (it "
        "lives at src/auth.ts). It uses REAL crypto (expo-crypto CSPRNG salts + SHA-256). "
        "Do NOT hand-roll hashing or randomness — Math.random() and homemade digests "
        "FAIL the no_weak_crypto policy gate (the build is BLOCKED). Store ONLY "
        "`await hashPassword(password)`; verify with `await verifyPassword(input, stored)`; "
        "mint sessions with `await generateToken()`.\n"
        "- src/hooks/useAuth.ts: returns `{ user, loading, error, signup, login, "
        "logout }`; calls src/db.ts + the auth primitive; persists the session locally.\n"
        "- app/ screens (Expo Router): a login screen + a signup screen, and a "
        "protected screen shown only when `user` is set (redirect to login otherwise); "
        "compose <LoginForm>/<SignupForm> from the themed kit (email + password Inputs "
        "+ a Button).\n"
        "- __tests__ (jest, mock 'expo-router'): signup stores a HASHED password "
        "(assert the stored value is NOT the plaintext), login with the wrong password "
        "fails, login with the correct password succeeds. NEVER assert a plaintext "
        "password is stored. (The crypto primitive is already tested — don't retest it.)"
    ),
}


def skeleton_contract(shape, mobile=False):
    """The prompt fragment for `shape`, or '' for the generic fallback (which keeps
    the base deliverables rather than forcing a wrong skeleton). `mobile=True` swaps
    in the no-server (Expo) variant for shapes whose web contract references a server
    (e.g. auth → an expo-sqlite + on-device-session version, never auth.mjs)."""
    if mobile and shape in _MOBILE_CONTRACTS:
        return _MOBILE_CONTRACTS[shape]
    return _CONTRACTS.get(shape, "")


# Minimal ALWAYS-PRESENT interactive controls each shape must render regardless of
# DATA — a crud-list/form/single-record always shows an input + a button even with
# zero rows, so a render that lacks them is a blank/broken UI. Empty for
# dashboard/generic (read-mostly / unconstrained) so the render audit never
# false-flags them. (SOLID-2.)
_EXPECTED_DOM = {
    "crud-list": {"inputs": 1, "buttons": 1},
    "form": {"inputs": 1, "buttons": 1},
    "single-record": {"inputs": 1, "buttons": 1},
    "auth": {"inputs": 1, "buttons": 1},
}


def expected_dom(shape):
    """The minimal core controls `shape` must render (control-group → min count),
    for the shape-aware render audit. Empty dict for shapes with no fixed control."""
    return dict(_EXPECTED_DOM.get(shape, {}))


def contract_for(ctx, fid="", mobile=False):
    """(shape, contract_text) for a feature context. The text is '' when the shape
    is generic, so callers can inject unconditionally. `mobile=True` selects the
    no-server (Expo) contract variant where one exists."""
    shape = classify(_ctx_text(ctx) + "\n" + (fid or "").replace("-", " "))
    return shape, skeleton_contract(shape, mobile=mobile)


def _main(argv=None):
    text = " ".join(argv or sys.argv[1:]) or sys.stdin.read()
    shape = classify(text)
    print(f"shape: {shape}")
    print(f"scores: {score(text)}")
    c = skeleton_contract(shape)
    if c:
        print("\n" + c)
    return 0


if __name__ == "__main__":
    sys.exit(_main())

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
import os
import secrets
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import auth
import backbone
import bioequivalence
import content_model
import cv
import domain
import dr
import ectd
import entitlements as entitlements_mod
import esign
import fees
import hc_calendar
import lifecycle
import privacy
import qos
import rbac
import rep
import rep_stylesheet
import report_ingest
import xmlsafe
import response_builder
import retention
import stf
import tenancy
import transmission
import validation

DB_PATH = "submissions.db"

# Multi-tenant control plane (REQ-077..084). Platform data (tenants, plans,
# entitlements, owner accounts, control-plane audit) lives in its OWN database,
# physically separate from any tenant's workspace DB; each tenant gets its own
# DB file under CONTROL_PLANE_TENANTS_ROOT/<tenant-id>/ands.db.
CONTROL_PLANE_DB = os.environ.get("ADF_CONTROL_PLANE_DB") or "control_plane.db"
CONTROL_PLANE_TENANTS_ROOT = (
    os.environ.get("ADF_TENANTS_ROOT") or os.path.join("data", "tenants"))
# Bootstrap platform-owner credentials (overridable via env for a real deploy).
OWNER_EMAIL = (os.environ.get("ADF_OWNER_EMAIL") or "owner@platform").lower()
OWNER_PASSWORD = os.environ.get("ADF_OWNER_PASSWORD") or "owner-change-me"

# Hard ceiling on an inbound JSON request body. Every API payload here is small
# structured metadata (identifiers, a few KB of leaf "content" at most), so a
# generous 16 MiB cap can never reject a legitimate request while it defends the
# threaded server against a memory-exhaustion DoS from a hostile (or buggy)
# oversized Content-Length — we refuse to allocate/read the giant body at all.
MAX_REQUEST_BODY_BYTES = 16 * 1024 * 1024

RECORD_COLUMNS = (
    "id", "applicant", "drug_product", "dossier_id",
    "submission_type", "sequence", "contact_email", "created_at",
)


# ---------------------------------------------------------------------------
# Persistence (sqlite, stdlib)
# ---------------------------------------------------------------------------

class _SqliteStore:
    """Shared SQLite plumbing for every store in this module.

    Holds a single thread-guarded connection (the server is threaded) with a
    row factory, and tears it down on ``close``. Subclasses implement
    ``_init_db`` to create their own tables — the connection, lock and teardown
    live here so there is exactly one correct implementation."""

    def __init__(self, db_path: str = DB_PATH):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    # -- shared, thread-guarded query plumbing --------------------------------
    # Every store used to repeat the same ``with self._lock: execute(...)``
    # dance for each read/write. That plumbing lives here exactly once; callers
    # pass a literal, parameterized SQL string (``?`` placeholders only — never
    # string-built) plus its params, so there is one correct, injection-safe
    # implementation of locking + execution.
    def _exec(self, sql: str, params: tuple = ()):
        """Run a write/DDL statement under the lock, commit, return the cursor."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _fetchone(self, sql: str, params: tuple = ()):
        """Run a read under the lock and return the first row (or ``None``)."""
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple = ()) -> list:
        """Run a read under the lock and return all rows."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __del__(self):  # best-effort safety net so a dropped store never leaks
        try:
            self._conn.close()
        except Exception:
            pass


class SubmissionStore(_SqliteStore):
    """Stores accepted submissions and answers the lifecycle's prior-sequence
    question. Thread-safe (the server is threaded) via a single guarded
    connection."""

    def _init_db(self) -> None:
        self._exec(
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

    def prior_sequences(self, dossier_id: str) -> list:
        """Already-accepted sequences for a dossier (for the lifecycle check)."""
        rows = self._fetchall(
            "SELECT sequence FROM submissions WHERE dossier_id = ? "
            "ORDER BY sequence",
            (str(dossier_id or "").strip(),),
        )
        return [r["sequence"] for r in rows]

    def add(self, data: dict) -> dict:
        """Insert an accepted submission and return the stored record."""
        created_at = datetime.now(timezone.utc).isoformat()
        cur = self._exec(
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
        return self.get(cur.lastrowid)

    def list(self) -> list:
        rows = self._fetchall("SELECT * FROM submissions ORDER BY id")
        return [dict(r) for r in rows]

    def get(self, submission_id: int):
        row = self._fetchone(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,))
        return dict(row) if row else None


class CompanyStore(_SqliteStore):
    """REQ-001: records the HC-assigned Company ID and the machine-generated,
    immutable REP CO filename against the sponsor org, plus saved contacts.
    Thread-safe via a single guarded connection."""

    def _init_db(self) -> None:
        self._exec(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id   TEXT NOT NULL,
                company_name TEXT NOT NULL,
                co_filename  TEXT NOT NULL,
                co_xml       TEXT NOT NULL,
                contacts     TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
            """
        )

    def add(self, data: dict, co_filename: str, co_xml: str) -> dict:
        created_at = datetime.now(timezone.utc).isoformat()
        contacts = json.dumps(data.get("contacts") or [])
        cur = self._exec(
            """
            INSERT INTO companies
                (company_id, company_name, co_filename, co_xml, contacts,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(data.get("company_id", "")).strip(),
                str(data.get("applicant", "")).strip(),
                co_filename,
                co_xml,
                contacts,
                created_at,
            ),
        )
        return self.get(cur.lastrowid)

    def get(self, company_id: int):
        row = self._fetchone(
            "SELECT * FROM companies WHERE id = ?", (company_id,))
        if not row:
            return None
        rec = dict(row)
        rec["contacts"] = json.loads(rec["contacts"])
        return rec

    def list(self) -> list:
        rows = self._fetchall("SELECT * FROM companies ORDER BY id")
        out = []
        for r in rows:
            rec = dict(r)
            rec["contacts"] = json.loads(rec["contacts"])
            out.append(rec)
        return out


class DossierStore(_SqliteStore):
    """REQ-014/015/017/018/019: persists multi-sequence eCTD dossiers as JSON.

    A dossier aggregate (``ectd.Dossier``) carries nested sequences, leaves,
    per-leaf content, checksums and reuse pointers, so it is stored whole as a
    JSON blob keyed by Dossier ID. Thread-safe via a single guarded connection.
    """

    def _init_db(self) -> None:
        self._exec(
            """
            CREATE TABLE IF NOT EXISTS dossiers (
                dossier_id TEXT PRIMARY KEY,
                payload    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def create(self, dossier_id: str) -> "ectd.Dossier":
        """Create an empty dossier; raises if the Dossier ID already exists."""
        dossier_id = str(dossier_id or "").strip()
        now = datetime.now(timezone.utc).isoformat()
        dossier = ectd.Dossier(dossier_id)
        if self._fetchone(
                "SELECT 1 FROM dossiers WHERE dossier_id = ?", (dossier_id,)):
            raise ectd.LeafOperationError(
                f"dossier {dossier_id} already exists")
        self._exec(
            "INSERT INTO dossiers (dossier_id, payload, created_at, "
            "updated_at) VALUES (?, ?, ?, ?)",
            (dossier_id, json.dumps(dossier.to_dict()), now, now),
        )
        return dossier

    def get(self, dossier_id: str):
        row = self._fetchone(
            "SELECT payload FROM dossiers WHERE dossier_id = ?",
            (str(dossier_id or "").strip(),),
        )
        if not row:
            return None
        return ectd.Dossier.from_dict(json.loads(row["payload"]))

    def save(self, dossier: "ectd.Dossier") -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._exec(
            "UPDATE dossiers SET payload = ?, updated_at = ? "
            "WHERE dossier_id = ?",
            (json.dumps(dossier.to_dict()), now, dossier.dossier_id),
        )

    def list(self) -> list:
        rows = self._fetchall(
            "SELECT dossier_id, payload FROM dossiers ORDER BY dossier_id")
        out = []
        for r in rows:
            d = ectd.Dossier.from_dict(json.loads(r["payload"]))
            out.append({"dossier_id": d.dossier_id,
                        "sequences": d.sequence_numbers(),
                        "live_leaves": len(d.live_leaf_ids())})
        return out


class TransmissionStore(_SqliteStore):
    """REQ-003/025/026/027/046/058: persists the per-dossier transmission ledger
    (ESG config + transactions + queue + audit) as a JSON blob keyed by Dossier
    ID. Thread-safe via a single guarded connection."""

    def _init_db(self) -> None:
        self._exec(
            """
            CREATE TABLE IF NOT EXISTS transmissions (
                dossier_id TEXT PRIMARY KEY,
                payload    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def get_or_create(self, dossier_id: str) -> "transmission.TransmissionLedger":
        dossier_id = str(dossier_id or "").strip()
        led = self.get(dossier_id)
        if led is not None:
            return led
        now = datetime.now(timezone.utc).isoformat()
        led = transmission.TransmissionLedger(dossier_id)
        self._exec(
            "INSERT OR IGNORE INTO transmissions (dossier_id, payload, "
            "created_at, updated_at) VALUES (?, ?, ?, ?)",
            (dossier_id, json.dumps(led.to_dict()), now, now),
        )
        return led

    def get(self, dossier_id: str):
        row = self._fetchone(
            "SELECT payload FROM transmissions WHERE dossier_id = ?",
            (str(dossier_id or "").strip(),),
        )
        if not row:
            return None
        return transmission.TransmissionLedger.from_dict(
            json.loads(row["payload"]))

    def save(self, led: "transmission.TransmissionLedger") -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._exec(
            "INSERT INTO transmissions (dossier_id, payload, created_at, "
            "updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(dossier_id) DO UPDATE SET payload = excluded.payload, "
            "updated_at = excluded.updated_at",
            (led.dossier_id, json.dumps(led.to_dict()), now, now),
        )

    def list(self) -> list:
        rows = self._fetchall(
            "SELECT payload FROM transmissions ORDER BY dossier_id")
        out = []
        for r in rows:
            led = transmission.TransmissionLedger.from_dict(
                json.loads(r["payload"]))
            out.append({"dossier_id": led.dossier_id,
                        "configured": bool(led.config),
                        "transactions": len(led.transactions)})
        return out


class LifecycleStore(_SqliteStore):
    """REQ-030/031/052/062: persists the per-dossier post-receipt DSTS lifecycle
    (phase/status state machine, deadline timers, clock-stops and the fee-credit
    entitlement) as a JSON blob keyed by Dossier ID."""

    def _init_db(self) -> None:
        self._exec(
            """
            CREATE TABLE IF NOT EXISTS lifecycles (
                dossier_id TEXT PRIMARY KEY,
                payload    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def get(self, dossier_id: str):
        row = self._fetchone(
            "SELECT payload FROM lifecycles WHERE dossier_id = ?",
            (str(dossier_id or "").strip(),),
        )
        if not row:
            return None
        return lifecycle.Lifecycle.from_dict(json.loads(row["payload"]))

    def get_or_create(self, dossier_id: str,
                      submission_type: str = lifecycle.DEFAULT_CLASS,
                      core_id: str = "", fee_paid=None) -> "lifecycle.Lifecycle":
        dossier_id = str(dossier_id or "").strip()
        lc = self.get(dossier_id)
        if lc is not None:
            return lc
        lc = lifecycle.Lifecycle(dossier_id, submission_type, core_id, fee_paid)
        self.save(lc)
        return lc

    def save(self, lc: "lifecycle.Lifecycle") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO lifecycles (dossier_id, payload, created_at, "
                "updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(dossier_id) DO UPDATE SET payload = excluded.payload, "
                "updated_at = excluded.updated_at",
                (lc.dossier_id, json.dumps(lc.to_dict()), now, now),
            )
            self._conn.commit()

    def list(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM lifecycles ORDER BY dossier_id"
            ).fetchall()
        out = []
        for r in rows:
            lc = lifecycle.Lifecycle.from_dict(json.loads(r["payload"]))
            out.append({"dossier_id": lc.dossier_id,
                        "submission_type": lc.submission_type,
                        "phase": lc.phase, "status": lc.status,
                        "fee_credit": bool(lc.fee_credit)})
        return out


class RejectionStore(_SqliteStore):
    """REQ-029: persists ingested eCTD Validation Reports (rejections),
    correlated by Core ID, as JSON blobs so a rejection can be re-fetched and
    its remediation worked into the next sequence."""

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rejections (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    core_id    TEXT,
                    dossier_id TEXT,
                    payload    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def add(self, core_id: str, dossier_id: str, result: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO rejections (core_id, dossier_id, payload, "
                "created_at) VALUES (?, ?, ?, ?)",
                (str(core_id or ""), str(dossier_id or ""),
                 json.dumps(result), now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get(self, rejection_id: int):
        with self._lock:
            row = self._conn.execute(
                "SELECT id, core_id, dossier_id, payload, created_at "
                "FROM rejections WHERE id = ?", (rejection_id,),
            ).fetchone()
        if not row:
            return None
        rec = json.loads(row["payload"])
        rec["id"] = row["id"]
        rec["created_at"] = row["created_at"]
        return rec

    def list(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, core_id, dossier_id, created_at FROM rejections "
                "ORDER BY id DESC"
            ).fetchall()
        return [{"id": r["id"], "core_id": r["core_id"],
                 "dossier_id": r["dossier_id"], "created_at": r["created_at"]}
                for r in rows]


class AuditStore(_SqliteStore):
    """REQ-038/054/060/NFR-002: an append-only audit trail.

    Records every access decision (RBAC), disposition attempt (retention) and
    any other state-changing event as an immutable, time-ordered row. There is
    NO update or delete path — the trail cannot be redacted (REQ-060) — and an
    inspection export reads it back complete and human-readable. Thread-safe via
    a single guarded connection."""

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    at         TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    action     TEXT NOT NULL,
                    actor      TEXT NOT NULL,
                    org_id     TEXT NOT NULL,
                    dossier_id TEXT NOT NULL,
                    allowed    INTEGER NOT NULL,
                    rule       TEXT NOT NULL,
                    detail     TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def append(self, category: str, action: str, *, actor: str = "",
               org_id: str = "", dossier_id: str = "", allowed: bool = True,
               rule: str = "", detail: dict = None, at: str = "") -> dict:
        at = str(at or "").strip() or datetime.now(timezone.utc).isoformat()
        row = (
            at, str(category or ""), str(action or ""), str(actor or ""),
            str(org_id or ""), str(dossier_id or ""), 1 if allowed else 0,
            str(rule or ""), json.dumps(detail or {}),
        )
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit_events (at, category, action, actor, "
                "org_id, dossier_id, allowed, rule, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            self._conn.commit()
            new_id = int(cur.lastrowid)
        return self._row(new_id)

    def _row(self, event_id: int):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM audit_events WHERE id = ?", (event_id,)
            ).fetchone()
        if not row:
            return None
        rec = dict(row)
        rec["allowed"] = bool(rec["allowed"])
        rec["detail"] = json.loads(rec["detail"])
        return rec

    def list(self, dossier_id: str = "", category: str = "") -> list:
        clauses, params = [], []
        if str(dossier_id or "").strip():
            clauses.append("dossier_id = ?")
            params.append(str(dossier_id).strip())
        if str(category or "").strip():
            clauses.append("category = ?")
            params.append(str(category).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # Parameterized: ``where`` is built only from hardcoded clause fragments
        # ("dossier_id = ?", "category = ?"); every user value flows through the
        # ``params`` placeholders, never the SQL text.
        sql = "SELECT * FROM audit_events" + where + " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            rec = dict(r)
            rec["allowed"] = bool(rec["allowed"])
            rec["detail"] = json.loads(rec["detail"])
            out.append(rec)
        return out

    def export_text(self, dossier_id: str = "") -> str:
        """REQ-060: a complete, time-ordered, human-readable inspection report."""
        events = self.list(dossier_id)
        scope = (f"dossier {dossier_id}" if str(dossier_id or "").strip()
                 else "all dossiers")
        lines = [
            "ANDS PORTAL — AUDIT TRAIL (regulatory inspection export)",
            f"Scope: {scope}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Events: {len(events)}",
            "=" * 72,
        ]
        for e in events:
            verdict = "ALLOWED" if e["allowed"] else f"DENIED ({e['rule']})"
            lines.append(
                f"[{e['at']}] #{e['id']:05d} {e['category']}/{e['action']} "
                f"by {e['actor'] or '(system)'} "
                f"org={e['org_id'] or '-'} dossier={e['dossier_id'] or '-'} "
                f"-> {verdict}")
            if e["detail"]:
                lines.append("    detail: " + json.dumps(e["detail"],
                                                          sort_keys=True))
        return "\n".join(lines) + "\n"


class PortfolioStore(_SqliteStore):
    """REQ-047: persists a sponsor org's multi-dossier / multi-product portfolio
    (an ``rbac.Portfolio`` aggregate) as a JSON blob keyed by org id."""

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolios (
                    org_id     TEXT PRIMARY KEY,
                    payload    TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def get_or_create(self, org_id: str) -> "rbac.Portfolio":
        org_id = str(org_id or "").strip()
        pf = self.get(org_id)
        return pf if pf is not None else rbac.Portfolio(org_id)

    def get(self, org_id: str):
        org_id = str(org_id or "").strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM portfolios WHERE org_id = ?", (org_id,)
            ).fetchone()
        return _portfolio_from_dict(json.loads(row["payload"])) if row else None

    def save(self, portfolio: "rbac.Portfolio") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO portfolios (org_id, payload, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(org_id) DO UPDATE SET "
                "payload = excluded.payload, updated_at = excluded.updated_at",
                (portfolio.org_id, json.dumps(portfolio.to_dict()), now))
            self._conn.commit()


def _portfolio_from_dict(data: dict) -> "rbac.Portfolio":
    """Rehydrate an ``rbac.Portfolio`` from its ``to_dict`` form."""
    pf = rbac.Portfolio(data.get("org_id", ""))
    for d in data.get("dossiers", []):
        pf.add_dossier(d.get("dossier_id", ""), d.get("product_family", ""),
                       d.get("din", ""), d.get("strength", ""))
    return pf


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

def make_handler(store: SubmissionStore, companies: "CompanyStore" = None,
                 dossiers: "DossierStore" = None,
                 transmissions: "TransmissionStore" = None,
                 lifecycles: "LifecycleStore" = None,
                 rejections: "RejectionStore" = None,
                 audits: "AuditStore" = None,
                 portfolios: "PortfolioStore" = None,
                 auth_store: "auth.AuthStore" = None,
                 tenancy_store: "tenancy.TenancyStore" = None,
                 entitlement_store: "entitlements_mod.EntitlementStore" = None):
    """Build a request handler bound to a given store (keeps it testable).

    ``companies`` backs the REP CO endpoints, ``dossiers`` backs the eCTD
    assembly endpoints, ``transmissions`` backs the ESG ack/transport console,
    ``lifecycles`` backs the post-receipt DSTS lifecycle (REQ-030/031/052/062)
    and ``rejections`` backs validation-report ingestion (REQ-029); when omitted
    a fresh in-memory store is created so existing callers keep working
    unchanged.

    ``auth_store``/``tenancy_store``/``entitlement_store`` back the multi-tenant
    control plane (REQ-077..084). When omitted, an in-memory control plane is
    created with a bootstrap owner so existing callers keep working unchanged.
    """
    if companies is None:
        companies = CompanyStore(":memory:")
    if dossiers is None:
        dossiers = DossierStore(":memory:")
    if transmissions is None:
        transmissions = TransmissionStore(":memory:")
    if lifecycles is None:
        lifecycles = LifecycleStore(":memory:")
    if rejections is None:
        rejections = RejectionStore(":memory:")
    if audits is None:
        audits = AuditStore(":memory:")
    if portfolios is None:
        portfolios = PortfolioStore(":memory:")
    if auth_store is None:
        auth_store = auth.AuthStore(":memory:")
        auth_store.ensure_owner(OWNER_EMAIL, OWNER_PASSWORD)
    if entitlement_store is None:
        entitlement_store = entitlements_mod.EntitlementStore(":memory:")
    if tenancy_store is None:
        tenancy_store = tenancy.TenancyStore(
            ":memory:", tenants_root=tempfile.mkdtemp(prefix="ands-tenants-"))

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

        def _send_text(self, text: str, status: int = 200,
                       filename: str = ""):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            if filename:
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                return {}
            if length <= 0:
                return {}
            if length > MAX_REQUEST_BODY_BYTES:
                # Refuse to allocate/read an oversized body (memory-exhaustion
                # DoS guard). Treated as an empty body so the handler answers
                # with its normal missing-field validation rather than hanging.
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _bool_qs(self, key: str) -> bool:
            """Parse a truthy query-string flag (1/true/yes/on)."""
            qs = parse_qs(urlparse(self.path).query)
            return str((qs.get(key) or ["0"])[0]).strip().lower() in (
                "1", "true", "yes", "on")

        def log_message(self, *args):  # keep test output quiet
            pass

        # -- control-plane auth/tenancy helpers (REQ-077..084) --------------
        def _bearer_token(self) -> str:
            """Token from ``Authorization: Bearer`` or a ``session`` cookie."""
            header = self.headers.get("Authorization") or ""
            if header.startswith("Bearer "):
                return header[len("Bearer "):].strip()
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("session="):
                    return part[len("session="):].strip()
            return ""

        def _session(self):
            return auth_store.resolve_session(self._bearer_token())

        def _require_owner(self):
            """Return the owner session, or send 403 (audited) — REQ-079."""
            sess = self._session()
            if sess and sess["role"] == auth.OWNER_ROLE:
                return sess
            actor = sess["email"] if sess else "anonymous"
            tenancy_store.audit(
                actor, "control_plane.access_denied",
                sess["tenant_id"] if sess else "",
                None, {"path": urlparse(self.path).path})
            self._send_json(
                {"error": "forbidden",
                 "detail": "the owner control plane is restricted to the "
                           "platform owner"}, 403)
            return None

        def _tenant_session(self):
            """Return an active-tenant user session, or send 401/403.

            A suspended tenant's users are blocked at the door (REQ-084); a
            request with no resolvable tenant context is denied (REQ-078)."""
            sess = self._session()
            if not sess or sess["role"] not in (
                    auth.TENANT_ADMIN_ROLE, auth.USER_ROLE):
                self._send_json({"error": "unauthorized"}, 401)
                return None
            tenant = tenancy_store.get_tenant(sess["tenant_id"])
            if tenant is None or tenant["status"] == tenancy.STATUS_DELETED:
                self._send_json(
                    {"error": "forbidden", "detail": "no tenant context"}, 403)
                return None
            if tenant["status"] == tenancy.STATUS_SUSPENDED:
                self._send_json(
                    {"error": "suspended",
                     "detail": "This workspace is suspended. Contact the "
                               "platform owner."}, 403)
                return None
            return sess

        def _require_feature(self, sess, feature: str) -> bool:
            """Server-side entitlement gate (REQ-082) — 403 + audit if denied."""
            tenant = tenancy_store.get_tenant(sess["tenant_id"])
            if tenant is None:
                self._send_json(
                    {"error": "forbidden", "detail": "no tenant context"}, 403)
                return False
            if not entitlement_store.is_entitled(
                    tenant["id"], tenant["plan_id"], feature):
                tenancy_store.audit(
                    sess["email"], "entitlement.denied", tenant["id"],
                    None, {"feature": feature})
                self._send_json(
                    {"error": "forbidden", "feature": feature,
                     "detail": f"the '{feature}' feature is not enabled for "
                               f"this tenant"}, 403)
                return False
            return True

        def _tenant_data(self, tenant_id: str) -> "tenancy.TenantData":
            return tenancy.TenantData(tenancy_store.tenant_db_path(tenant_id))

        # -- control-plane request handlers ---------------------------------
        def _handle_signup(self):
            """Self-serve company sign-up (REQ-077): atomically create a tenant
            + its first tenant-admin + the default all-features plan; auto-login
            the admin. A duplicate registration email routes to the existing
            tenant rather than silently duplicating."""
            body = self._read_json()
            company = str(body.get("company") or "").strip()
            email = str(body.get("email") or "").strip().lower()
            password = str(body.get("password") or "")
            name = str(body.get("name") or "").strip()
            if not company or not email or not password:
                self._send_json(
                    {"error": "company, email and password are required"}, 400)
                return
            try:
                tenant = tenancy_store.create_tenant(
                    company, email, actor="self-serve",
                    plan_id=entitlements_mod.DEFAULT_PLAN_ID)
            except tenancy.DuplicateTenant as dup:
                self._send_json(
                    {"error": "tenant_exists",
                     "detail": "a company is already registered with this "
                               "email; please sign in instead",
                     "tenant_id": dup.existing["id"]}, 409)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            # Create the first tenant-admin; roll back the tenant if it fails
            # so we never leave an orphaned tenant (atomicity, REQ-077).
            try:
                user = auth_store.create_user(
                    tenant["id"], email, password,
                    role=auth.TENANT_ADMIN_ROLE, name=name)
            except ValueError as exc:
                tenancy_store.delete(tenant["id"], "self-serve", archive=False)
                self._send_json({"error": str(exc)}, 400)
                return
            token = auth_store.start_session(user)
            self._send_json(
                {"tenant": tenant, "user": user, "token": token}, 201)

        def _handle_login(self):
            body = self._read_json()
            email = str(body.get("email") or "").strip().lower()
            password = str(body.get("password") or "")
            tenant_id = str(body.get("tenant_id") or "").strip()
            # Owner sign-in first (platform scope, no tenant).
            owner = auth_store.authenticate_owner(email, password)
            if owner is not None:
                token = auth_store.start_session(owner)
                self._send_json({"token": token, "role": owner["role"],
                                 "tenant_id": "", "redirect": "/owner"})
                return
            # Tenant user sign-in. Resolve the tenant from an explicit id or by
            # finding the (single) tenant whose user matches — credentials are
            # tenant-scoped, so we look up by the tenant's registration too.
            user = None
            if tenant_id:
                user = auth_store.authenticate(tenant_id, email, password)
            else:
                for tenant in tenancy_store.list_tenants(include_deleted=True):
                    candidate = auth_store.authenticate(
                        tenant["id"], email, password)
                    if candidate is not None:
                        user = candidate
                        tenant_id = tenant["id"]
                        break
            if user is None:
                self._send_json({"error": "invalid credentials"}, 401)
                return
            tenant = tenancy_store.get_tenant(tenant_id)
            if tenant is None or tenant["status"] == tenancy.STATUS_DELETED:
                self._send_json({"error": "invalid credentials"}, 401)
                return
            if tenant["status"] == tenancy.STATUS_SUSPENDED:
                # Suspended tenants are blocked at sign-in (REQ-084).
                self._send_json(
                    {"error": "suspended",
                     "detail": "This workspace is suspended. Contact the "
                               "platform owner."}, 403)
                return
            token = auth_store.start_session(user)
            self._send_json({"token": token, "role": user["role"],
                             "tenant_id": tenant_id, "redirect": "/"})

        def _handle_logout(self):
            token = self._bearer_token()
            if token:
                auth_store.end_session(token)
            self._send_json({"ok": True})

        def _handle_tenant_submission(self):
            """Write a record into the CURRENT tenant's OWN database — gated by
            the 'dossiers' entitlement (REQ-082) and physically isolated per
            tenant (REQ-078)."""
            sess = self._tenant_session()
            if sess is None:
                return
            if not self._require_feature(sess, "dossiers"):
                return
            body = self._read_json()
            data = self._tenant_data(sess["tenant_id"])
            try:
                rec = data.add("submission", {
                    "drug_product": (body.get("drug_product") or "").strip(),
                    "dossier_id": (body.get("dossier_id") or "").strip(),
                    "by": sess["email"]})
            finally:
                data.close()
            self._send_json({"saved": rec}, 201)

        def _handle_owner_provision(self):
            """Owner-initiated tenant provisioning (REQ-077). Returns an invite
            password for the new tenant-admin when none is supplied."""
            sess = self._require_owner()
            if sess is None:
                return
            body = self._read_json()
            company = (body.get("company") or "").strip()
            email = (body.get("email") or "").strip().lower()
            password = body.get("password") or secrets.token_urlsafe(12)
            if not company or not email:
                self._send_json(
                    {"error": "company and admin email are required"}, 400)
                return
            try:
                tenant = tenancy_store.create_tenant(
                    company, email, actor=sess["email"],
                    plan_id=entitlements_mod.DEFAULT_PLAN_ID)
            except tenancy.DuplicateTenant as dup:
                self._send_json(
                    {"error": "tenant_exists",
                     "tenant_id": dup.existing["id"]}, 409)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            try:
                user = auth_store.create_user(
                    tenant["id"], email, password,
                    role=auth.TENANT_ADMIN_ROLE)
            except ValueError as exc:
                tenancy_store.delete(tenant["id"], sess["email"], archive=False)
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json(
                {"tenant": tenant, "admin": user,
                 "invite_password": password}, 201)

        def _handle_owner_create_plan(self):
            sess = self._require_owner()
            if sess is None:
                return
            body = self._read_json()
            try:
                plan = entitlement_store.create_plan(
                    body.get("name") or "", body.get("features") or [])
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            tenancy_store.audit(sess["email"], "plan.create", "", None, plan)
            self._send_json({"plan": plan}, 201)

        def _handle_owner_update_plan(self, plan_id: str):
            sess = self._require_owner()
            if sess is None:
                return
            body = self._read_json()
            try:
                plan = entitlement_store.update_plan(
                    plan_id, body.get("features") or [])
            except KeyError:
                self._send_json({"error": "plan not found"}, 404)
                return
            tenancy_store.audit(sess["email"], "plan.update", "", None, plan)
            self._send_json({"plan": plan})

        def _handle_owner_tenant_action(self, rest: str):
            """Dispatch ``/api/owner/tenants/<id>/<action>`` (REQ-080/081/084)."""
            sess = self._require_owner()
            if sess is None:
                return
            if "/" not in rest:
                self._send_json({"error": "not found"}, 404)
                return
            tenant_id, action = rest.split("/", 1)
            if tenancy_store.get_tenant(tenant_id) is None:
                self._send_json({"error": "tenant not found"}, 404)
                return
            body = self._read_json()
            try:
                if action == "suspend":
                    result = tenancy_store.suspend(tenant_id, sess["email"])
                    auth_store.end_sessions_for_tenant(tenant_id)
                elif action == "resume":
                    result = tenancy_store.resume(tenant_id, sess["email"])
                elif action == "delete":
                    auth_store.end_sessions_for_tenant(tenant_id)
                    result = tenancy_store.delete(tenant_id, sess["email"])
                elif action == "plan":
                    plan_id = (body.get("plan_id") or "").strip()
                    if entitlement_store.get_plan(plan_id) is None:
                        self._send_json({"error": "plan not found"}, 404)
                        return
                    result = tenancy_store.set_plan(
                        tenant_id, plan_id, sess["email"])
                elif action == "overrides":
                    feature = (body.get("feature") or "").strip()
                    if feature not in entitlements_mod.FEATURES:
                        self._send_json({"error": "unknown feature"}, 400)
                        return
                    if body.get("enabled") is None:
                        entitlement_store.remove_override(tenant_id, feature)
                        change = {"feature": feature, "override": "removed"}
                    else:
                        entitlement_store.set_override(
                            tenant_id, feature, bool(body.get("enabled")))
                        change = {"feature": feature,
                                  "enabled": bool(body.get("enabled"))}
                    tenancy_store.audit(
                        sess["email"], "entitlement.override",
                        tenant_id, None, change)
                    tenant = tenancy_store.get_tenant(tenant_id)
                    self._send_json({"effective": entitlement_store.effective(
                        tenant_id, tenant["plan_id"])})
                    return
                else:
                    self._send_json({"error": "unknown action"}, 404)
                    return
            except KeyError:
                self._send_json({"error": "tenant not found"}, 404)
                return
            self._send_json({"tenant": result})

        # -- routing --------------------------------------------------------
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send_html(INDEX_HTML)
                return
            if path == "/favicon.ico":
                # Serve an inline SVG icon so the browser's automatic favicon
                # request never 404s / dirties the console.
                body = (
                    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
                    "<rect width='16' height='16' rx='3' fill='#1a4a7a'/>"
                    "<text x='8' y='12' font-size='11' text-anchor='middle' "
                    "fill='white' font-family='sans-serif'>A</text></svg>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path in ("/api/health", "/healthz"):
                # Readiness probe (client req 2026-06-26): the UI polls this and
                # presents only once both servers are up. A 200 means the web
                # listener answered AND the API/DB tier is genuinely live — we
                # touch the store so a not-yet-ready (or stale orphaned) process
                # reports 503 rather than a socket-accept-only false ready.
                try:
                    store.list()
                    api_ready = True
                except Exception:
                    api_ready = False
                self._send_json(
                    {"status": "ok" if api_ready else "starting",
                     "web": True, "api": api_ready},
                    status=200 if api_ready else 503)
                return
            if path == "/api/submissions":
                self._send_json({"submissions": store.list()})
                return
            if path == "/api/activity-types":
                self._send_json({"activity_types": [
                    {"code": code, "label": label}
                    for code, label in rep.ACTIVITY_TYPES.items()
                ]})
                return
            if path == "/api/companies":
                self._send_json({"companies": companies.list()})
                return
            if path == "/api/ectd/placement":
                # REQ-009: the versioned Module 1 placement table as data.
                self._send_json(ectd.module1_placement_table())
                return
            if path == "/api/ectd/dossiers":
                self._send_json({"dossiers": dossiers.list()})
                return
            if path.startswith("/api/ectd/dossiers/"):
                self._handle_dossier_get(path)
                return
            if path == "/api/validation/rulesets":
                # REQ-022: every published ruleset version, active flagged.
                self._send_json(
                    {"rulesets": validation.list_ruleset_versions(),
                     "active": validation.ACTIVE_RULESET_VERSION})
                return
            if path == "/api/validation/ruleset":
                # REQ-022: the rule catalog effective at ?version= (default active).
                qs = parse_qs(urlparse(self.path).query)
                version = (qs.get("version") or
                           [validation.ACTIVE_RULESET_VERSION])[0]
                try:
                    self._send_json(validation.ruleset_catalog(version))
                except validation.UnknownRulesetError as exc:
                    self._send_json({"error": str(exc)}, 422)
                return
            if path == "/api/validation/services":
                # REQ-045: the external HC/FDA services a packaging attempt needs.
                self._send_json({"services": [
                    {"key": k, "label": v}
                    for k, v in validation.EXTERNAL_SERVICES.items()]})
                return
            if path == "/api/backbone/versions":
                # REQ-041: every registered backbone generator + adoption
                # roadmap (v4.0 dates flagged as industry estimates, not HC).
                self._send_json({
                    "versions": backbone.list_backbone_versions(),
                    "active": backbone.ACTIVE_BACKBONE_VERSION,
                    "adoption_roadmap": backbone.ADOPTION_ROADMAP,
                })
                return
            if path == "/api/dr/policy":
                # REQ-055: the published DR/BCP policy (RPO/RTO, protected
                # content classes, residency basis) for a tenant config.
                qs = parse_qs(urlparse(self.path).query)
                region = (qs.get("region") or [dr.DEFAULT_REGION])[0]
                require = (qs.get("require_in_canada") or ["0"])[0]
                self._send_json(dr.dr_policy(
                    require_in_canada=str(require).strip().lower()
                    in ("1", "true", "yes"),
                    region=region))
                return
            if path == "/api/privacy/policy":
                # NFR-005: PIPEDA baseline + configurable provincial overlay
                # (AB/BC/QC PIPA, ON PHIPA) with REQ-067 basis tags.
                qs = parse_qs(urlparse(self.path).query)
                province = (qs.get("province") or [""])[0]
                self._send_json(privacy.privacy_policy(
                    province=province,
                    intra_provincial=self._bool_qs("intra_provincial"),
                    phi=self._bool_qs("phi")))
                return
            if path == "/api/rep/dossier-id/branches":
                # REQ-002: product-type/activity request branches + the 8-week
                # MAXIMUM lead-time guidance (warn-only; never gates).
                self._send_json({
                    "branches": [
                        {"key": k, "label": b["label"], "prefix": b["prefix"],
                         "digits": list(b["digits"]), "form": b["form"],
                         "fields": b["fields"]}
                        for k, b in rep.DOSSIER_REQUEST_BRANCHES.items()],
                    "max_lead_weeks": rep.DOSSIER_ID_MAX_LEAD_WEEKS,
                    "lead_time_basis":
                        "HC 8-week MAXIMUM (warn-only; never gates)",
                    "dsts_ia_lookup": rep.DSTS_IA_LOOKUP_CONTACT,
                })
                return
            if path == "/api/rep/stylesheet":
                # REQ-065: the bundled, version-tracked HC REP XML stylesheet
                # package (pharmabio_stylesheets) + per-version template coverage.
                self._send_json(rep_stylesheet.package_manifest())
                return
            if path == "/api/cv":
                # REQ-066: the ingested HC Module-1 controlled vocabularies,
                # keyed to the CA Module 1 schema version.
                qs = parse_qs(urlparse(self.path).query)
                version = (qs.get("schema_version")
                           or [cv.DEFAULT_SCHEMA_VERSION])[0]
                try:
                    vocabs = cv.load_cv(version)
                except cv.ControlledVocabularyError as exc:
                    self._send_json({"error": str(exc)}, 404)
                    return
                self._send_json({"schema_version": version,
                                 "vocabularies": vocabs})
                return
            if path == "/api/crp/fields":
                # REQ-007: the structured CRP fields the form requires.
                self._send_json({"fields": [
                    {"key": k, "label": v}
                    for k, v in bioequivalence.CRP_FIELDS.items()]})
                return
            if path == "/api/be/rulesets":
                # REQ-063: every published BE acceptance ruleset + dosage classes.
                self._send_json({
                    "rulesets": bioequivalence.list_be_rulesets(),
                    "dosage_form_classes": [
                        {"key": k, "label": v}
                        for k, v in bioequivalence.DOSAGE_FORM_CLASSES.items()],
                    "m13a_effective": bioequivalence.M13A_EFFECTIVE_DATE,
                })
                return
            if path == "/api/qos/template":
                # REQ-061: the QOS-CE template structure as data.
                self._send_json(qos.qos_ce_template())
                return
            if path == "/api/transmission/account-types":
                # REQ-003: the ESG account types + pinned environment.
                self._send_json({
                    "account_types": [{"key": k, "label": v}
                                      for k, v in transmission.ACCOUNT_TYPES.items()],
                    "esg_environment": transmission.ESG_ENVIRONMENT,
                    "esg_environment_deployed": transmission.ESG_ENVIRONMENT_DEPLOYED,
                    "recipient_center": transmission.RECIPIENT_CENTER,
                    "gateway_ceiling_gb": transmission.GATEWAY_CEILING_GB,
                    "congestion_lower_gb": transmission.CONGESTION_LOWER_GB,
                    "congestion_cutoff": transmission.CONGESTION_CUTOFF,
                })
                return
            if path == "/api/transmission/dossiers":
                # REQ-027: the per-dossier transmission ledgers.
                self._send_json({"dossiers": transmissions.list()})
                return
            if path.startswith("/api/transmission/dossiers/"):
                ident = path[len("/api/transmission/dossiers/"):].strip("/")
                led = transmissions.get(ident)
                if led is None:
                    self._send_json(
                        {"error": f"no transmission ledger for '{ident}'"}, 404)
                else:
                    self._send_json(led.status())
                return
            if path == "/api/calendar/holidays":
                # REQ-052: the computed Canadian federal statutory holiday table.
                qs = parse_qs(urlparse(self.path).query)
                try:
                    start = int((qs.get("start") or ["2025"])[0])
                    end = int((qs.get("end") or [str(start + 1)])[0])
                except (TypeError, ValueError):
                    self._send_json({"error": "start/end must be years"}, 422)
                    return
                if end < start or end - start > 50:
                    self._send_json({"error": "invalid year range"}, 422)
                    return
                if start < 1 or end > 9999:
                    self._send_json({"error": "year out of range (1-9999)"}, 422)
                    return
                table = hc_calendar.holiday_table(start, end)
                self._send_json({
                    "timezone": hc_calendar.DEFAULT_TIMEZONE,
                    "start_year": start, "end_year": end,
                    "count": len(table),
                    "holidays": [{"date": d, "name": n}
                                 for d, n in sorted(table.items())],
                    "notice_bases": hc_calendar.NOTICE_BASIS,
                })
                return
            if path == "/api/lifecycle/dossiers":
                # REQ-030: every tracked post-receipt DSTS lifecycle.
                self._send_json({"lifecycles": lifecycles.list()})
                return
            if path.startswith("/api/lifecycle/dossiers/"):
                ident = path[len("/api/lifecycle/dossiers/"):].strip("/")
                lc = lifecycles.get(ident)
                if lc is None:
                    self._send_json(
                        {"error": f"no lifecycle for '{ident}'"}, 404)
                else:
                    self._send_json(lc.status_view())
                return
            if path == "/api/rejections":
                # REQ-029: every ingested eCTD Validation Report (rejection).
                self._send_json({"rejections": rejections.list()})
                return
            if path.startswith("/api/rejections/"):
                ident = path[len("/api/rejections/"):].strip("/")
                try:
                    rec = rejections.get(int(ident))
                except ValueError:
                    rec = None
                if rec is None:
                    self._send_json({"error": "rejection not found"}, 404)
                else:
                    self._send_json(rec)
                return
            if path == "/api/rbac/roles":
                # REQ-038: the least-privilege roles + capabilities, as data.
                self._send_json({"roles": rbac.roles_catalog(),
                                 "capabilities": list(rbac.ALL_CAPABILITIES)})
                return
            if path.startswith("/api/rbac/portfolio/"):
                ident = path[len("/api/rbac/portfolio/"):].strip("/")
                pf = portfolios.get(ident)
                if pf is None:
                    self._send_json(
                        {"error": f"no portfolio for org '{ident}'"}, 404)
                else:
                    self._send_json(pf.to_dict())
                return
            if path == "/api/audit":
                # REQ-060: the time-ordered audit trail (optionally scoped).
                qs = parse_qs(urlparse(self.path).query)
                dossier_id = (qs.get("dossier_id") or [""])[0]
                category = (qs.get("category") or [""])[0]
                self._send_json({"events": audits.list(dossier_id, category)})
                return
            if path.startswith("/api/audit/export/"):
                ident = path[len("/api/audit/export/"):].strip("/")
                as_text = ident.endswith(".txt")
                if as_text:
                    ident = ident[:-len(".txt")]
                text = audits.export_text(ident)
                # REQ-060: the export action is itself audit-logged.
                audits.append("audit", "export", dossier_id=ident,
                              detail={"events": len(audits.list(ident))})
                if as_text:
                    self._send_text(text, filename="audit-trail.txt")
                else:
                    self._send_json({"dossier_id": ident, "text": text,
                                     "events": audits.list(ident)})
                return
            if path == "/api/retention/policy":
                # REQ-054/067: the effective retention policy (months per class).
                self._send_json(retention.retention_policy())
                return
            if path == "/api/retention/dispositions":
                # REQ-054: every logged disposition event (blocked or executed).
                self._send_json(
                    {"dispositions": audits.list(category="disposition")})
                return
            if path == "/api/content-model/submission-types":
                # REQ-004: the submission-type router options as data.
                self._send_json(
                    {"submission_types": content_model.submission_type_options()})
                return
            if path == "/api/content-model/ands":
                # REQ-004: the configured ANDS content model (module gating).
                self._send_json(content_model.ands_content_model(
                    cs_be_only=self._bool_qs("cs_be_only")))
                return
            if path == "/api/content-model/checklist":
                # REQ-044: the required-document checklist for the ANDS model.
                cs_be_only = self._bool_qs("cs_be_only")
                self._send_json({
                    "cs_be_only": cs_be_only,
                    "required_documents":
                        content_model.required_documents(cs_be_only)})
                return
            if path == "/api/esign/policy":
                # REQ-039/068: the governing HPFB Electronic Signatures Policy.
                self._send_json({"policy": esign.policy()})
                return
            if path == "/api/fees/reference":
                # REQ-035/036/037: the fee groupings, ANDS grouping, escalation
                # bases, right-to-sell drug types and remission rates as data
                # (updatable without code changes — REQ-040).
                self._send_json({
                    "ands_grouping": fees.ANDS_FEE_GROUPING,
                    "anchor_seed_excluded": fees.COMPARATIVE_STUDIES_ANCHOR_SEED,
                    "groupings": [
                        {"key": k, "label": g["label"], "basis": g["basis"],
                         "rationale": g["rationale"],
                         "fiscal_years": sorted(g["amounts"])}
                        for k, g in fees.FEE_GROUPINGS.items()],
                    "drug_types": [{"key": k, "label": v}
                                   for k, v in fees.DRUG_TYPES.items()],
                    "remission": {
                        "first_submission": fees.REMISSION_FIRST_SUBMISSION,
                        "subsequent_ands": fees.REMISSION_SUBSEQUENT_ANDS,
                    },
                    "right_to_sell_due": {
                        "month": fees.RIGHT_TO_SELL_DUE_MONTH,
                        "day": fees.RIGHT_TO_SELL_DUE_DAY,
                    },
                })
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

            # ----- multi-tenant control plane: GET routes (REQ-077..084) ----
            if path in ("/owner", "/owner/"):
                # Owner control-plane console — a SEPARATE shell from the tenant
                # workspace (REQ-079). The page renders for anyone; every data
                # call it makes requires an owner session (enforced server-side).
                self._send_html(OWNER_CONSOLE_HTML)
                return
            if path in ("/login", "/signup"):
                self._send_html(AUTH_HTML)
                return
            if path == "/api/auth/me":
                sess = self._session()
                if not sess:
                    self._send_json({"authenticated": False}, 401)
                    return
                payload = {"authenticated": True, "email": sess["email"],
                           "role": sess["role"], "tenant_id": sess["tenant_id"]}
                if sess["tenant_id"]:
                    tenant = tenancy_store.get_tenant(sess["tenant_id"])
                    if tenant:
                        payload["tenant"] = {
                            "id": tenant["id"], "name": tenant["name"],
                            "status": tenant["status"],
                            "plan_id": tenant["plan_id"]}
                self._send_json(payload)
                return
            if path == "/api/tenant/entitlements":
                sess = self._tenant_session()
                if sess is None:
                    return
                tenant = tenancy_store.get_tenant(sess["tenant_id"])
                self._send_json({
                    "tenant_id": tenant["id"], "plan_id": tenant["plan_id"],
                    "features": entitlement_store.effective(
                        tenant["id"], tenant["plan_id"]),
                    "entitled": entitlement_store.entitled_features(
                        tenant["id"], tenant["plan_id"])})
                return
            if path == "/api/tenant/submissions":
                sess = self._tenant_session()
                if sess is None:
                    return
                if not self._require_feature(sess, "dossiers"):
                    return
                data = self._tenant_data(sess["tenant_id"])
                try:
                    self._send_json(
                        {"submissions": data.list("submission")})
                finally:
                    data.close()
                return
            if path == "/api/owner/tenants":
                if self._require_owner() is None:
                    return
                out = []
                for tenant in tenancy_store.list_tenants(include_deleted=True):
                    data = self._tenant_data(tenant["id"])
                    try:
                        usage = data.count()
                    finally:
                        data.close()
                    out.append(dict(tenant, usage={"records": usage}))
                self._send_json({"tenants": out})
                return
            if path == "/api/owner/plans":
                if self._require_owner() is None:
                    return
                self._send_json({"plans": entitlement_store.list_plans(),
                                 "features": [
                                     {"key": k,
                                      "label": entitlements_mod.FEATURE_LABELS[k]}
                                     for k in entitlements_mod.FEATURES]})
                return
            if path == "/api/owner/audit":
                if self._require_owner() is None:
                    return
                self._send_json({"audit": tenancy_store.list_audit()})
                return
            if path.startswith("/api/owner/tenants/") and \
                    path.endswith("/entitlements"):
                if self._require_owner() is None:
                    return
                tid = path[len("/api/owner/tenants/"):-len("/entitlements")]
                tenant = tenancy_store.get_tenant(tid)
                if tenant is None:
                    self._send_json({"error": "tenant not found"}, 404)
                    return
                self._send_json({
                    "tenant_id": tid, "plan_id": tenant["plan_id"],
                    "features": entitlement_store.effective(
                        tid, tenant["plan_id"])})
                return

            self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path

            # ----- multi-tenant control plane: POST routes (REQ-077..084) ---
            if path == "/api/auth/signup":
                self._handle_signup()
                return
            if path == "/api/auth/login":
                self._handle_login()
                return
            if path == "/api/auth/logout":
                self._handle_logout()
                return
            if path == "/api/tenant/submissions":
                self._handle_tenant_submission()
                return
            if path == "/api/owner/tenants":
                self._handle_owner_provision()
                return
            if path == "/api/owner/plans":
                self._handle_owner_create_plan()
                return
            if path.startswith("/api/owner/plans/"):
                self._handle_owner_update_plan(path[len("/api/owner/plans/"):])
                return
            if path.startswith("/api/owner/tenants/"):
                self._handle_owner_tenant_action(
                    path[len("/api/owner/tenants/"):])
                return

            if path == "/api/validate":
                self._handle_validate(store_record=False)
                return
            if path == "/api/submissions":
                self._handle_validate(store_record=True)
                return
            if path == "/api/identifiers/validate":
                self._handle_identifiers()
                return
            if path == "/api/companies":
                self._handle_company()
                return
            if path == "/api/companies/rename":
                self._handle_rename()
                return
            if path == "/api/transactions/assemble":
                self._handle_assemble()
                return
            if path == "/api/rep/dossier-id/request":
                self._handle_dossier_id_request()
                return
            if path == "/api/rep/dossier-id/assign":
                self._handle_dossier_id_assign()
                return
            if path == "/api/rep/stylesheet/render":
                self._handle_rep_stylesheet_render()
                return
            if path == "/api/privacy/consent":
                self._handle_privacy_consent()
                return
            if path == "/api/privacy/data-subject-request":
                self._handle_privacy_dsr()
                return
            if path == "/api/cv/validate":
                self._handle_cv_validate()
                return
            if path == "/api/validation/run":
                self._handle_validation_run()
                return
            if path == "/api/validation/inline":
                self._handle_validation_inline()
                return
            if path == "/api/validation/fix":
                self._handle_validation_fix()
                return
            if path == "/api/validation/report":
                self._handle_validation_report()
                return
            if path == "/api/validation/report.txt":
                self._handle_validation_report_download()
                return
            if path == "/api/validation/consistency":
                self._handle_validation_consistency()
                return
            if path == "/api/validation/package":
                self._handle_validation_package()
                return
            if path == "/api/validation/package-attempt":
                self._handle_validation_package_attempt()
                return
            if path == "/api/ectd/dossiers":
                self._handle_dossier_create()
                return
            if path.startswith("/api/ectd/dossiers/"):
                self._handle_dossier_post(path)
                return
            if path == "/api/response/file":
                self._handle_response_file()
                return
            if path == "/api/backbone/generate":
                self._handle_backbone_generate()
                return
            if path == "/api/dr/backup":
                self._handle_dr_backup()
                return
            if path == "/api/dr/test":
                self._handle_dr_test()
                return
            if path == "/api/crp/validate":
                self._handle_crp_validate()
                return
            if path == "/api/be/resolve":
                self._handle_be_resolve()
                return
            if path == "/api/be/evaluate":
                self._handle_be_evaluate()
                return
            if path == "/api/cs-be/build":
                self._handle_cs_be_build()
                return
            if path == "/api/qos/build":
                self._handle_qos_build()
                return
            if path == "/api/qos/gate":
                self._handle_qos_gate()
                return
            if path == "/api/stf/generate":
                self._handle_stf_generate()
                return
            if path == "/api/stf/validate":
                self._handle_stf_validate()
                return
            if path == "/api/transmission/configure":
                self._handle_transmission_configure()
                return
            if path == "/api/transmission/test-round-trip":
                self._handle_transmission_test_round_trip()
                return
            if path == "/api/transmission/route":
                self._handle_transmission_route()
                return
            if path == "/api/transmission/submit":
                self._handle_transmission_submit()
                return
            if path == "/api/transmission/ack":
                self._handle_transmission_ack()
                return
            if path == "/api/transmission/monitor":
                self._handle_transmission_monitor()
                return
            if path == "/api/transmission/resend":
                self._handle_transmission_resend()
                return
            if path == "/api/transmission/media/build":
                self._handle_transmission_media_build()
                return
            if path == "/api/transmission/media/ship":
                self._handle_transmission_media_ship()
                return
            if path == "/api/transmission/media/receive":
                self._handle_transmission_media_receive()
                return
            if path == "/api/calendar/deadline":
                self._handle_calendar_deadline()
                return
            if path == "/api/lifecycle/start":
                self._handle_lifecycle_start()
                return
            if path == "/api/lifecycle/transition":
                self._handle_lifecycle_transition()
                return
            if path == "/api/lifecycle/service-standard":
                self._handle_lifecycle_service_standard()
                return
            if path == "/api/rejections/ingest":
                self._handle_rejection_ingest()
                return
            if path == "/api/content-model/route":
                self._handle_content_model_route()
                return
            if path == "/api/content-model/checklist-gate":
                self._handle_content_model_checklist_gate()
                return
            if path == "/api/esign/request-acceptance":
                self._handle_esign_request_acceptance()
                return
            if path == "/api/esign/record-acceptance":
                self._handle_esign_record_acceptance()
                return
            if path == "/api/esign/qa-review":
                self._handle_esign_qa_review()
                return
            if path == "/api/esign/sign":
                self._handle_esign_sign()
                return
            if path == "/api/esign/verify":
                self._handle_esign_verify()
                return
            if path == "/api/esign/gate":
                self._handle_esign_gate()
                return
            if path == "/api/fees/ands":
                self._handle_fees_ands()
                return
            if path == "/api/fees/mitigation":
                self._handle_fees_mitigation()
                return
            if path == "/api/fees/right-to-sell":
                self._handle_fees_right_to_sell()
                return
            if path == "/api/rbac/access":
                self._handle_rbac_access()
                return
            if path == "/api/rbac/portfolio":
                self._handle_rbac_portfolio()
                return
            if path == "/api/retention/disposition":
                self._handle_retention_disposition()
                return
            self._send_json({"error": "not found"}, 404)

        # -- REP / identifier handlers (REQ-001/005/006/042/043) ------------
        def _handle_identifiers(self):
            """REQ-042: validate identifier formats at input."""
            data = self._read_json()
            errors = rep.validate_identifiers(data)
            self._send_json({"valid": not errors, "errors": errors})

        def _handle_company(self):
            """REQ-001: emit a REP CO XML with an immutable machine-generated
            filename and record the HC-assigned Company ID against the org."""
            data = self._read_json()
            errors = []
            if not str(data.get("applicant", "") or "").strip():
                errors.append({"rule": "applicant_required",
                               "message": "Applicant / company name is required"})
            if not str(data.get("company_id", "") or "").strip():
                errors.append({"rule": "company_id_required",
                               "message": "HC-assigned Company ID is required"})
            errors.extend(rep.validate_identifiers(
                {"company_id": data.get("company_id", "")}))
            if errors:
                self._send_json({"valid": False, "errors": errors}, 422)
                return
            fname = rep.co_filename(data.get("company_id", ""))
            xml = rep.build_co_xml(data)
            record = companies.add(data, fname, xml)
            self._send_json({"valid": True, "record": record,
                             "co": {"filename": fname, "xml": xml,
                                    "immutable": True}}, 201)

        def _handle_rename(self):
            """REQ-001: REP filenames are immutable — block any rename."""
            data = self._read_json()
            try:
                rep.assert_rep_filename_immutable(
                    data.get("original", ""), data.get("proposed", ""))
            except rep.ImmutableFilenameError as exc:
                self._send_json({"allowed": False, "error": str(exc)}, 409)
                return
            self._send_json({"allowed": True})

        def _handle_assemble(self):
            """REQ-043: single-entry assembly of CO/RT/PI + ca-regional +
            cover letter from one set of identifiers."""
            data = self._read_json()
            result = rep.assemble_transaction(data)
            status = 200 if result["valid"] else 422
            self._send_json(result, status)

        def _handle_dossier_id_request(self):
            """REQ-002: reuse an existing Dossier ID for a continuing sequence
            or open a new branched request. The 8-week MAX lead time is
            warn-only — a too-early request is flagged, never gated (still 200)."""
            data = self._read_json()
            result = rep.resolve_dossier_id(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_dossier_id_assign(self):
            """REQ-002: record an HC-assigned Dossier ID against a pending
            request, transitioning it to 'assigned' (or 422 on a format
            mismatch)."""
            data = self._read_json()
            result = rep.record_dossier_id_assignment(
                data.get("request") or {}, data.get("assigned_dossier_id", ""))
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_rep_stylesheet_render(self):
            """REQ-065: render generated REP XML through the version-matched HC
            stylesheet for human review BEFORE filing.

            Accepts either ``{"transaction": <assemble output>}`` to render every
            artifact, or ``{"xml": ..., "kind"?, "template_version"?}`` to render a
            single REP XML blob. Returns the human-review HTML (what HC displays).
            """
            data = self._read_json()
            txn = data.get("transaction")
            try:
                if txn:
                    result = rep_stylesheet.render_transaction(txn)
                else:
                    result = rep_stylesheet.render_rep_xml(
                        data.get("xml", ""),
                        kind=data.get("kind") or None,
                        template_version=data.get("template_version") or None)
            except rep_stylesheet.StylesheetVersionError as exc:
                self._send_json({"error": str(exc), "matched": False}, 422)
                return
            except (rep_stylesheet.StylesheetRenderError,
                    xmlsafe.UnsafeXmlError) as exc:
                self._send_json({"error": str(exc)}, 422)
                return
            self._send_json(result)

        # -- validation engine handlers (REQ-022/023/024/045/059/070) -------
        def _validation_version(self, data: dict) -> str:
            """The selected ruleset version from a request body (REQ-022)."""
            return (str(data.get("version", "") or "").strip()
                    or validation.ACTIVE_RULESET_VERSION)

        def _handle_validation_run(self):
            """REQ-022: run the versioned ruleset over a transaction context."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            try:
                result = validation.run_validation(
                    ctx, self._validation_version(data))
            except validation.UnknownRulesetError as exc:
                self._send_json({"error": str(exc)}, 422)
                return
            self._send_json(result)

        def _handle_validation_inline(self):
            """REQ-023: inline gutter defects mapped to file/node with fix_ids."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            try:
                result = validation.inline_findings(
                    ctx, self._validation_version(data))
            except validation.UnknownRulesetError as exc:
                self._send_json({"error": str(exc)}, 422)
                return
            self._send_json(result)

        def _handle_validation_fix(self):
            """REQ-023: apply a one-click fix, then re-run the inline gutter."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            version = self._validation_version(data)
            try:
                new_ctx = validation.apply_fix(
                    ctx, data.get("fix_id", ""), data.get("file", ""))
            except ValueError as exc:
                self._send_json({"applied": False, "error": str(exc)}, 422)
                return
            self._send_json({
                "applied": True,
                "context": new_ctx,
                "inline": validation.inline_findings(new_ctx, version),
            })

        def _build_validation_report_or_422(self):
            """REQ-024 (shared): parse the request, build the validation report,
            and send a 422 on an unknown ruleset. Returns the report dict, or
            ``None`` if a 422 was already sent (caller must then return)."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            try:
                return validation.build_validation_report(
                    ctx, self._validation_version(data))
            except validation.UnknownRulesetError as exc:
                self._send_json({"error": str(exc)}, 422)
                return None

        def _handle_validation_report(self):
            """REQ-024: the downloadable pre-submission validation report (JSON)."""
            report = self._build_validation_report_or_422()
            if report is None:
                return
            report["text"] = validation.render_report_text(report)
            self._send_json(report)

        def _handle_validation_report_download(self):
            """REQ-024: the report as a downloadable plain-text attachment."""
            report = self._build_validation_report_or_422()
            if report is None:
                return
            self._send_text(
                validation.render_report_text(report),
                filename="hc-validation-report.txt")

        def _handle_validation_consistency(self):
            """REQ-059: cross-document / metadata-consistency findings only."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            findings = validation.check_cross_document_consistency(ctx)
            self._send_json({"consistent": not findings, "findings": findings})

        def _handle_validation_package(self):
            """REQ-059: block packaging on any Error / cross-doc inconsistency."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            try:
                result = validation.validate_for_packaging(
                    ctx, self._validation_version(data))
            except validation.UnknownRulesetError as exc:
                self._send_json({"error": str(exc)}, 422)
                return
            self._send_json(result)

        def _handle_validation_package_attempt(self):
            """REQ-045: a state-retaining packaging attempt with guided resume."""
            data = self._read_json()
            ctx = validation.context_from_request(data.get("context", data))
            services = data.get("services") or {}
            result = validation.attempt_package(ctx, services)
            # A schema/service failure is surfaced (not silent) but the request
            # itself succeeds — the state is retained for a later retry.
            self._send_json(result, 200 if result["ok"] else 409)

        # -- version-pluggable backbone generator (REQ-041) -----------------
        def _handle_backbone_generate(self):
            """REQ-041: emit a backbone from a neutral content model through the
            selected (default active) generator — same content, any version.

            Persistent document UUIDs are assigned deterministically and a
            schema/DTD failure (or an unknown version) is surfaced, never
            silently swallowed."""
            data = self._read_json()
            try:
                result = backbone.generate_backbone(data)
            except backbone.UnknownBackboneVersionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            except (ectd.SchemaValidationError,
                    ectd.ChecksumMismatchError) as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            result["valid"] = True
            self._send_json(result, 201)

        # -- disaster recovery / business continuity (REQ-055) --------------
        def _dr_args(self, data: dict):
            """Shared region/residency parsing for the DR endpoints."""
            return {
                "region": str(data.get("region", dr.DEFAULT_REGION)
                              or dr.DEFAULT_REGION).strip(),
                "require_in_canada": bool(data.get("require_in_canada")),
            }

        def _handle_dr_backup(self):
            """REQ-055: create an encrypted, checksummed, residency-pinned backup
            covering every protected content class."""
            data = self._read_json()
            at = str(data.get("at", "")
                     or datetime.now(timezone.utc).isoformat())
            try:
                backup = dr.make_backup(
                    data.get("snapshot") or {}, at=at, **self._dr_args(data))
            except dr.ResidencyError as exc:
                self._send_json({"valid": False, "rule": "residency",
                                 "error": str(exc)}, 422)
                return
            except ValueError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            self._send_json({"valid": True, "backup": backup}, 201)

        def _handle_dr_test(self):
            """REQ-055: run a documented, tested restoration (DR drill) and
            return its PASS/FAIL artifact with per-content-class verification."""
            data = self._read_json()
            at = str(data.get("at", "")
                     or datetime.now(timezone.utc).isoformat())
            try:
                result = dr.run_dr_test(
                    data.get("snapshot") or {}, at=at, **self._dr_args(data))
            except dr.ResidencyError as exc:
                self._send_json({"valid": False, "rule": "residency",
                                 "error": str(exc)}, 422)
                return
            except (ValueError, dr.IntegrityError) as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            self._send_json({"valid": True, "result": result},
                            200 if result["verified"] else 409)

        # -- privacy handlers (NFR-005) -------------------------------------
        def _handle_privacy_consent(self):
            """NFR-005: capture and retain EXPRESS consent (PIPEDA baseline +
            provincial overlay); implied consent is rejected (422)."""
            data = self._read_json()
            at = str(data.get("at", "")
                     or datetime.now(timezone.utc).isoformat())
            result = privacy.capture_consent(data, at=at)
            self._send_json(result, 201 if result["valid"] else 422)

        def _handle_privacy_dsr(self):
            """NFR-005: open a data-subject access/correction request."""
            data = self._read_json()
            at = str(data.get("at", "")
                     or datetime.now(timezone.utc).isoformat())
            result = privacy.handle_data_subject_request(data, at=at)
            self._send_json(result, 201 if result["valid"] else 422)

        def _handle_cv_validate(self):
            """REQ-066: reject out-of-vocabulary Module-1 metadata (I08/H08)."""
            data = self._read_json()
            version = str(data.get("schema_version", "")
                          or cv.DEFAULT_SCHEMA_VERSION)
            try:
                errors = cv.validate_metadata(data.get("metadata") or {}, version)
            except cv.ControlledVocabularyError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            self._send_json({"valid": not errors, "errors": errors},
                            200 if not errors else 422)

        # -- CRP / bioequivalence / CS-BE handlers (REQ-007/008/063) --------
        def _handle_crp_validate(self):
            """REQ-007: validate a CRP entry + pharmaceutical equivalence."""
            data = self._read_json()
            result = bioequivalence.assemble_crp(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_be_resolve(self):
            """REQ-063: resolve the versioned BE acceptance ruleset."""
            data = self._read_json()
            self._send_json(bioequivalence.resolve_be_ruleset(
                data.get("submission_date", ""),
                data.get("dosage_form_class", "")))

        def _handle_be_evaluate(self):
            """REQ-063/008: evaluate AUC + Cmax against the resolved ruleset."""
            data = self._read_json()
            result = bioequivalence.evaluate_bioequivalence(
                {"auc": data.get("auc"), "cmax": data.get("cmax")},
                data.get("submission_date", ""),
                data.get("dosage_form_class", ""))
            self._send_json(result, 200 if result["bioequivalent"] else 422)

        def _handle_cs_be_build(self):
            """REQ-008: build the CS-BE evidence for a BE-only ANDS."""
            data = self._read_json()
            result = bioequivalence.build_cs_be(data)
            result["leaf_xml"] = bioequivalence.build_cs_be_leaf_xml(
                result["cs_be"])
            self._send_json(result, 200 if result["valid"] else 422)

        # -- QOS-CE handlers (REQ-061) --------------------------------------
        def _handle_qos_build(self):
            """REQ-061: generate + fill + validate the Module 2.3 QOS-CE."""
            data = self._read_json()
            result = qos.build_qos_ce(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_qos_gate(self):
            """REQ-061: the screening-deficiency-risk gate for the QOS-CE."""
            data = self._read_json()
            result = qos.qos_ce_gate(data)
            self._send_json(result, 200 if result["can_pass"] else 422)

        # -- STF handlers (REQ-064) -----------------------------------------
        def _handle_stf_generate(self):
            """REQ-064: generate conformant STF leaves for Module 5 study data."""
            data = self._read_json()
            studies = data.get("module5_studies", data.get("studies", []))
            self._send_json({"stfs": stf.generate_stfs(studies)})

        def _handle_stf_validate(self):
            """REQ-064: validate the STF category across the transaction."""
            data = self._read_json()
            studies = data.get("module5_studies", data.get("studies", []))
            result = stf.validate_stf_category(studies)
            self._send_json(result, 200 if result["valid"] else 422)

        # -- fee / mitigation / right-to-sell handlers (REQ-035/036/037) ----
        def _handle_fees_ands(self):
            """REQ-035: resolve the ANDS 'Comparative studies' fee for the fiscal
            year of the submission date (never the historical anchor seed)."""
            data = self._read_json()
            try:
                result = fees.resolve_ands_fee(data.get("submission_date", ""))
            except ValueError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            result["valid"] = True
            self._send_json(result)

        def _handle_fees_mitigation(self):
            """REQ-036: evaluate small-business remission / deferral for a fee."""
            data = self._read_json()
            try:
                result = fees.evaluate_fee_mitigation(data)
            except (ValueError, TypeError) as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            result["valid"] = True
            self._send_json(result)

        def _handle_fees_right_to_sell(self):
            """REQ-037: the per-DIN annual Right-to-Sell fee + outstanding /
            reminder / overdue flags for a drug type as of a given date."""
            data = self._read_json()
            try:
                result = fees.right_to_sell_status(
                    data.get("drug_type", ""),
                    data.get("as_of", "") or data.get("submission_date", ""),
                    bool(data.get("paid")))
            except ValueError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            result["valid"] = True
            self._send_json(result)

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

        # -- eCTD dossier handlers (REQ-009/014/015/017/018/019) ------------
        def _dossier_payload(self, dossier) -> dict:
            return {
                "dossier_id": dossier.dossier_id,
                "sequences": dossier.sequence_numbers(),
                "current_view": dossier.current_view(),
            }

        def _dossier_or_404(self, dossier_id):
            dossier = dossiers.get(dossier_id)
            if dossier is None:
                self._send_json(
                    {"error": f"dossier '{dossier_id}' not found"}, 404)
                return None
            return dossier

        def _ectd_parts(self, path) -> list:
            rest = path[len("/api/ectd/dossiers/"):]
            return [p for p in rest.split("/") if p != ""]

        def _export_sequence(self, dossier, sequence):
            """Build + schema-validate + re-verify checksums for one sequence,
            translating any blocking domain error into a 422 (REQ-014/015)."""
            try:
                return self._send_json(dossier.export_sequence(sequence))
            except (ectd.LeafOperationError, ectd.SchemaValidationError,
                    ectd.ChecksumMismatchError) as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)

        def _handle_dossier_get(self, path):
            parts = self._ectd_parts(path)
            dossier = self._dossier_or_404(parts[0] if parts else "")
            if dossier is None:
                return
            # /api/ectd/dossiers/<id>/export/<seq> — REQ-014/015
            if len(parts) >= 3 and parts[1] == "export":
                self._export_sequence(dossier, parts[2])
                return
            # /api/ectd/dossiers/<id>/current-view — REQ-018
            if len(parts) >= 2 and parts[1] == "current-view":
                self._send_json(dossier.current_view())
                return
            self._send_json(self._dossier_payload(dossier))

        def _handle_dossier_create(self):
            data = self._read_json()
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            if not domain.is_valid_dossier_id(dossier_id):
                self._send_json({"valid": False, "errors": [{
                    "rule": "dossier_id_format",
                    "message": "Dossier ID must be a lowercase 'e' followed by "
                               "6 or 7 digits (e.g. e123456)"}]}, 422)
                return
            try:
                dossier = dossiers.create(dossier_id)
            except ectd.LeafOperationError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 409)
                return
            self._send_json(
                {"valid": True, "dossier": self._dossier_payload(dossier)}, 201)

        def _handle_dossier_post(self, path):
            parts = self._ectd_parts(path)
            dossier = self._dossier_or_404(parts[0] if parts else "")
            if dossier is None:
                return
            action = parts[1] if len(parts) >= 2 else ""
            data = self._read_json()
            sequence = str(data.get("sequence", "") or "").strip()

            if action == "sequences":
                try:
                    dossier.add_sequence(sequence)
                except ectd.LeafOperationError as exc:
                    self._send_json({"valid": False, "error": str(exc)}, 422)
                    return
                dossiers.save(dossier)
                self._send_json(
                    {"valid": True, "dossier": self._dossier_payload(dossier)},
                    201)
                return

            if action == "leaves":
                # REQ-017/019: add a leaf op (validates prior-leaf refs + reuse).
                try:
                    record = dossier.add_leaf(sequence, data)
                except ectd.LeafOperationError as exc:
                    self._send_json({"valid": False, "error": str(exc)}, 422)
                    return
                dossiers.save(dossier)
                self._send_json({"valid": True, "leaf": record,
                                 "current_view": dossier.current_view()}, 201)
                return

            if action == "export":
                self._export_sequence(dossier, sequence)
                return

            self._send_json({"error": "not found"}, 404)

        # -- Q&A response-sequence builder (REQ-032) ------------------------
        def _handle_response_file(self):
            """REQ-032: file a Q&A response to a deficiency notice as the next
            eCTD sequence of an existing dossier.

            404 when the dossier is unknown; 422 when the notice/answers fail
            validation (no mutation in that case); 201 with the filed sequence
            on success."""
            data = self._read_json()
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            dossier = self._dossier_or_404(dossier_id)
            if dossier is None:
                return
            try:
                result = response_builder.file_response_sequence(
                    dossier,
                    data.get("notice") or {},
                    data.get("answers") or [],
                    sequence=str(data.get("sequence", "") or "").strip() or None)
            except response_builder.ResponseBuilderError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            dossiers.save(dossier)
            self._send_json({"valid": True, "response": result}, 201)

        # -- transmission / ESG console handlers ----------------------------
        #    (REQ-003/025/026/027/046/058)
        def _transmission_or_404(self, dossier_id):
            """Fetch an existing ledger or emit a 404 (returns None on miss)."""
            led = transmissions.get(str(dossier_id or "").strip())
            if led is None:
                self._send_json({"valid": False, "error":
                                 f"no transmission ledger for '{dossier_id}'"},
                                404)
            return led

        def _handle_transmission_configure(self):
            """REQ-003: validate + persist the ESG transmission configuration
            (account type, X.509 cert, recipient Center 'HC', pinned NextGen
            environment). Production stays disabled until the test round-trip."""
            data = self._read_json()
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            if not dossier_id:
                self._send_json({"valid": False, "errors": [{
                    "rule": "dossier_id_required",
                    "message": "A Dossier ID is required to configure "
                               "transmission"}]}, 422)
                return
            result = transmission.configure_transmission(data)
            if not result["valid"]:
                self._send_json(result, 422)
                return
            led = transmissions.get_or_create(dossier_id)
            led.set_config(result["config"])
            transmissions.save(led)
            self._send_json({"valid": True, "config": result["config"],
                             "status": led.status()}, 201)

        def _handle_transmission_test_round_trip(self):
            """REQ-003: record a Test-gateway round-trip; Production is unlocked
            only when MDN + FDA Ack + HC Ack are all received."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            if not led.config:
                self._send_json({"valid": False, "error":
                                 "configure ESG transmission before the test "
                                 "round-trip"}, 422)
                return
            led.set_config(transmission.complete_test_round_trip(
                led.config, data.get("acks")))
            transmissions.save(led)
            allowed, reason = transmission.can_transmit_production(led.config)
            self._send_json({"valid": True, "production_enabled": allowed,
                             "reason": reason, "config": led.config,
                             "status": led.status()})

        def _handle_transmission_route(self):
            """REQ-025/026: stateless pre-flight size routing + congestion offer."""
            data = self._read_json()
            self._send_json({"valid": True,
                             "routing": transmission.evaluate_size_routing(
                                 data.get("size_gb", 0))})

        def _handle_transmission_submit(self):
            """REQ-025/026/027: submit a sequence. Routes by size, folds in the
            congestion offer, and enforces the one-at-a-time per-dossier queue;
            ``production`` gates on the test round-trip (REQ-003)."""
            data = self._read_json()
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            if not dossier_id:
                self._send_json({"valid": False, "error":
                                 "a Dossier ID is required to transmit"}, 422)
                return
            led = transmissions.get_or_create(dossier_id)
            try:
                record = led.submit(data, now=data.get("now"),
                                    production=bool(data.get("production")))
            except transmission.ProductionBlockedError as exc:
                self._send_json({"valid": False, "error": str(exc),
                                 "rule": "production_blocked"}, 409)
                return
            except transmission.TransmissionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            transmissions.save(led)
            self._send_json({"valid": True, "transaction": record,
                             "status": led.status()}, 201)

        def _handle_transmission_ack(self):
            """REQ-028/046: advance the acknowledgement state machine — ``type``
            is 'mdn' (transport receipt), 'fda' (FDA Acknowledgement w/ Core ID),
            or 'hc' (Health Canada Acknowledgement Receipt = true delivery)."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            ack_type = str(data.get("type", "") or "").strip().lower()
            now = data.get("now")
            try:
                if ack_type == "mdn":
                    led.receive_mdn(data.get("sequence", ""), now=now)
                elif ack_type == "fda":
                    led.receive_fda_ack(
                        data.get("sequence", ""), data.get("core_id", ""),
                        now=now,
                        transport_rejected=bool(data.get("transport_rejected")))
                elif ack_type == "hc":
                    led.receive_hc_ack(
                        data.get("core_id", ""), now=now,
                        sequence=str(data.get("sequence", "") or ""))
                else:
                    self._send_json({"valid": False, "error":
                                     "ack type must be 'mdn', 'fda', or 'hc'"},
                                    422)
                    return
            except transmission.TransmissionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            transmissions.save(led)
            self._send_json({"valid": True, "status": led.status()})

        def _handle_transmission_monitor(self):
            """REQ-046: run the stall/timeout monitors and raise operator alerts
            (no MDN in window -> TRANSPORT_UNCONFIRMED; MDN-without-FDA-ack ->
            INVESTIGATE; never auto-marked received)."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            kwargs = {}
            try:
                if data.get("mdn_timeout_s") is not None:
                    kwargs["mdn_timeout_s"] = int(data["mdn_timeout_s"])
                if data.get("fda_timeout_s") is not None:
                    kwargs["fda_timeout_s"] = int(data["fda_timeout_s"])
            except (TypeError, ValueError):
                self._send_json(
                    {"error": "mdn_timeout_s and fda_timeout_s must be integers"}, 422)
                return
            alerts = led.check_monitors(now=data.get("now"), **kwargs)
            transmissions.save(led)
            self._send_json({"valid": True, "alerts": alerts,
                             "status": led.status()})

        def _handle_transmission_resend(self):
            """REQ-046: guarded resend — an unresolved delivery requires explicit
            confirmation + a recorded rationale to prevent an unverified
            duplicate transmission of the same sequence."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            try:
                record = led.resend(
                    data.get("sequence", ""),
                    confirm=bool(data.get("confirm")),
                    rationale=str(data.get("rationale", "") or ""),
                    now=data.get("now"))
            except transmission.DuplicateSendError as exc:
                self._send_json({"valid": False, "error": str(exc),
                                 "rule": "duplicate_send_blocked"}, 409)
                return
            except transmission.TransmissionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            transmissions.save(led)
            self._send_json({"valid": True, "transaction": record,
                             "status": led.status()})

        def _handle_transmission_media_build(self):
            """REQ-058: build the >10 GB physical-media package (validated tree,
            backbones, checksums, media-manifest + cover documentation)."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            try:
                package = led.build_media(
                    data.get("sequence", ""), data.get("tree"),
                    now=data.get("now"))
            except transmission.TransmissionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            transmissions.save(led)
            self._send_json({"valid": True, "package": package,
                             "status": led.status()}, 201)

        def _handle_transmission_media_ship(self):
            """REQ-058: record the physical-media shipment (carrier + tracking)."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            try:
                shipment = led.ship_media(
                    data.get("sequence", ""), data.get("carrier", ""),
                    data.get("tracking", ""), now=data.get("now"))
            except transmission.TransmissionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            transmissions.save(led)
            self._send_json({"valid": True, "shipment": shipment,
                             "status": led.status()})

        def _handle_transmission_media_receive(self):
            """REQ-058: record physical-media receipt by the HC records office,
            ready for Core-ID reconciliation back to the same transaction."""
            data = self._read_json()
            led = self._transmission_or_404(data.get("dossier_id"))
            if led is None:
                return
            try:
                shipment = led.receive_media(
                    data.get("sequence", ""), now=data.get("now"))
            except transmission.TransmissionError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            transmissions.save(led)
            self._send_json({"valid": True, "shipment": shipment,
                             "status": led.status()})

        # -- REQ-052: HC deadline calendar ----------------------------------
        def _handle_calendar_deadline(self):
            """REQ-052: compute a regulatory deadline under HC calendar
            conventions — calendar vs business basis per notice type, Canadian
            statutory holidays, the configured review timezone — surfacing (never
            silently rolling) any weekend/holiday adjustment."""
            data = self._read_json()
            start = str(data.get("start", "") or "").strip()
            if not start:
                self._send_json({"valid": False,
                                 "error": "a start date is required"}, 422)
                return
            try:
                days = int(data.get("days"))
            except (TypeError, ValueError):
                self._send_json({"valid": False,
                                 "error": "days must be an integer"}, 422)
                return
            basis = data.get("basis") or None
            try:
                result = hc_calendar.compute_deadline(
                    start, days, basis=basis,
                    notice_type=str(data.get("notice_type", "") or ""),
                    timezone=str(data.get("timezone", "")
                                 or hc_calendar.DEFAULT_TIMEZONE))
            except (ValueError, TypeError) as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            self._send_json({"valid": True, "deadline": result})

        # -- REQ-030/031/062: post-receipt DSTS lifecycle -------------------
        def _handle_lifecycle_start(self):
            """REQ-030: begin tracking the post-receipt DSTS lifecycle for a
            dossier — status starts at Processing on receipt by Health Canada."""
            data = self._read_json()
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            if not dossier_id:
                self._send_json({"valid": False,
                                 "error": "a dossier_id is required"}, 422)
                return
            if lifecycles.get(dossier_id) is not None:
                self._send_json({"valid": False,
                                 "error": f"lifecycle for '{dossier_id}' "
                                          "already started"}, 409)
                return
            lc = lifecycle.Lifecycle(
                dossier_id, str(data.get("submission_type", "") or
                                lifecycle.DEFAULT_CLASS),
                str(data.get("core_id", "") or ""), data.get("fee_paid"))
            lc.start(now=data.get("now"))
            lifecycles.save(lc)
            self._send_json({"valid": True, "status": lc.status_view(
                now=data.get("now"))}, 201)

        def _lifecycle_or_404(self, data):
            """REQ-030/062 (shared): resolve the lifecycle for the request's
            ``dossier_id``; send a 404 and return ``None`` if there is none.
            On success returns the lifecycle aggregate."""
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            lc = lifecycles.get(dossier_id)
            if lc is None:
                self._send_json(
                    {"valid": False,
                     "error": f"no lifecycle for '{dossier_id}'"}, 404)
            return lc

        def _handle_lifecycle_transition(self):
            """REQ-030/031: drive the DSTS state machine — ``action`` is one of
            'to_screening', 'screening_outcome', 'clarifax', 'resume_clock' or
            'decision'."""
            data = self._read_json()
            lc = self._lifecycle_or_404(data)
            if lc is None:
                return
            action = str(data.get("action", "") or "").strip()
            now = data.get("now")
            result = None
            try:
                if action == "to_screening":
                    lc.to_screening(now=now)
                elif action == "screening_outcome":
                    lc.record_screening_outcome(
                        data.get("outcome", ""), now=now)
                elif action == "clarifax":
                    result = lc.issue_clarifax(
                        tier=str(data.get("tier", "")
                                 or lifecycle.DEFAULT_CLARIFAX_TIER),
                        response_days=data.get("response_days"), now=now)
                elif action == "resume_clock":
                    lc.resume_clock(now=now)
                elif action == "decision":
                    lc.record_decision(data.get("decision", ""), now=now)
                else:
                    self._send_json(
                        {"valid": False,
                         "error": "action must be 'to_screening', "
                                  "'screening_outcome', 'clarifax', "
                                  "'resume_clock' or 'decision'"}, 422)
                    return
            except lifecycle.LifecycleError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            lifecycles.save(lc)
            payload = {"valid": True, "status": lc.status_view(now=now)}
            if result is not None:
                payload["timer"] = result
            self._send_json(payload)

        def _handle_lifecycle_service_standard(self):
            """REQ-062: evaluate days-elapsed-vs-target and surface/record the
            statutory 25% fee-credit entitlement (SOR/2019-124) when Health
            Canada has missed the applicable service standard."""
            data = self._read_json()
            lc = self._lifecycle_or_404(data)
            if lc is None:
                return
            assessment = lc.check_service_standard(now=data.get("now"))
            lifecycles.save(lc)
            self._send_json({"valid": True, "assessment": assessment})

        # -- REQ-029: rejection / validation-report ingestion ---------------
        def _handle_rejection_ingest(self):
            """REQ-029: ingest the emailed eCTD Validation Report, correlate it to
            the originating transaction by Core ID, and map each reported error
            back to the exact file/node in the dossier tree for the next
            sequence."""
            data = self._read_json()
            report_text = data.get("report_text", "") or data.get("report", "")
            if not str(report_text or "").strip():
                self._send_json({"valid": False,
                                 "error": "report_text is required"}, 422)
                return
            dossier_id = str(data.get("dossier_id", "") or "").strip()
            # Pull the live correlation context from the ledger + dossier tree.
            transactions = []
            led = transmissions.get(dossier_id) if dossier_id else None
            if led is not None:
                transactions = led.transactions
            leaves, existing_sequences = [], []
            dossier = dossiers.get(dossier_id) if dossier_id else None
            if dossier is not None:
                leaves = dossier.current_view()["live"]
                existing_sequences = dossier.sequence_numbers()
            try:
                result = report_ingest.correlate_rejection(
                    report_text, transactions=transactions, leaves=leaves,
                    existing_sequences=existing_sequences)
            except report_ingest.ReportParseError as exc:
                self._send_json({"valid": False, "error": str(exc)}, 422)
                return
            rejection_id = rejections.add(
                result["core_id"],
                result["report_dossier_id"] or dossier_id, result)
            result["id"] = rejection_id
            self._send_json({"valid": True, "rejection": result}, 201)

        # -- content model / type router / checklist (REQ-004/044) ----------
        def _handle_content_model_route(self):
            """REQ-004: route a submission type and return decision support +
            (for ANDS) the configured content model."""
            data = self._read_json()
            result = content_model.route_submission_type(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_content_model_checklist_gate(self):
            """REQ-044: block the validation gate while mandatory documents are
            missing for the configured ANDS content model."""
            data = self._read_json()
            result = content_model.checklist_gate(data)
            self._send_json(result, 200 if result["can_pass"] else 422)

        # -- e-signature approval gate (REQ-039/053/068) --------------------
        def _handle_esign_request_acceptance(self):
            """REQ-068: build a request for HC's case-by-case acceptance of an
            e-signature approach under the HPFB Electronic Signatures Policy."""
            data = self._read_json()
            result = esign.request_hc_acceptance(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_esign_record_acceptance(self):
            """REQ-068: record HC's decision on a requested approach."""
            data = self._read_json()
            result = esign.record_hc_acceptance(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_esign_qa_review(self):
            """REQ-039: record a QA reviewer's documented audit-trail review."""
            data = self._read_json()
            result = esign.qa_review(data)
            self._send_json(result, 200 if result["valid"] else 422)

        def _handle_esign_sign(self):
            """REQ-039/053: apply an authorized e-signature, emitting an
            immutable, tamper-evident signature manifest."""
            data = self._read_json()
            result = esign.sign(data)
            self._send_json(result, 201 if result["valid"] else 422)

        def _handle_esign_verify(self):
            """REQ-053: detect any post-signature modification of signed
            content."""
            data = self._read_json()
            result = esign.verify_manifest(
                data.get("manifest") or {}, data.get("current"))
            self._send_json(result, 200 if result["valid"] else 409)

        def _handle_esign_gate(self):
            """REQ-039/053: transmission becomes available only after a documented
            QA review AND a valid, untampered authorized signature."""
            data = self._read_json()
            result = esign.transmission_gate(data)
            self._send_json(result, 200 if result["can_transmit"] else 409)

        # -- RBAC access decisions + portfolio (REQ-038/047) ----------------
        def _principal_from(self, data: dict) -> "rbac.Principal":
            """Build an ``rbac.Principal`` from a request body (tolerant of a
            nested ``principal`` object or top-level fields)."""
            p = data.get("principal") if isinstance(
                data.get("principal"), dict) else data
            return rbac.Principal(
                p.get("user_id", ""), p.get("org_id", ""),
                p.get("roles") or [], p.get("dossier_scope"))

        def _handle_rbac_access(self):
            """REQ-038: evaluate an access decision (hard tenant isolation,
            per-dossier scope, least-privilege capability) and audit-log EVERY
            decision — a cross-tenant/denied attempt is recorded per REQ-038."""
            data = self._read_json()
            principal = self._principal_from(data)
            capability = str(data.get("capability", "") or "").strip()
            resource = data.get("resource") or {}
            decision = rbac.authorize(principal, capability, resource)
            # Persist the decision to the append-only audit trail (REQ-038/060).
            audits.append(
                "access", capability or "(none)",
                actor=principal.user_id, org_id=principal.org_id,
                dossier_id=str((resource or {}).get("dossier_id", "") or ""),
                allowed=decision["allowed"], rule=decision["rule"],
                detail=decision["audit"])
            self._send_json(decision, 200 if decision["allowed"] else 403)

        def _handle_rbac_portfolio(self):
            """REQ-047: create/replace a sponsor org's multi-dossier portfolio so
            its dossiers/product-families are isolated and queryable."""
            data = self._read_json()
            org_id = str(data.get("org_id", "") or "").strip()
            if not org_id:
                self._send_json({"valid": False, "errors": [
                    {"rule": "org_id_required",
                     "message": "org_id is required"}]}, 422)
                return
            pf = rbac.Portfolio(org_id)
            try:
                for d in data.get("dossiers") or []:
                    pf.add_dossier(d.get("dossier_id", ""),
                                   d.get("product_family", ""),
                                   d.get("din", ""), d.get("strength", ""))
            except ValueError as exc:
                self._send_json({"valid": False, "errors": [
                    {"rule": "dossier_invalid", "message": str(exc)}]}, 422)
                return
            portfolios.save(pf)
            self._send_json({"valid": True, "portfolio": pf.to_dict()}, 201)

        # -- retention disposition (REQ-054) --------------------------------
        def _handle_retention_disposition(self):
            """REQ-054: attempt a disposition. Legal-hold / within-window records
            are blocked; EVERY attempt (blocked or executed) is logged to the
            append-only disposition trail."""
            data = self._read_json()
            record = data.get("record") or {}
            now = str(data.get("now", "") or "").strip()
            actor = str(data.get("actor", "") or "").strip()
            config = data.get("config") or {}
            try:
                event = retention.disposition_event(record, actor, now, config)
            except ValueError as exc:
                self._send_json({"valid": False, "errors": [
                    {"rule": "invalid_request", "message": str(exc)}]}, 422)
                return
            blockers = event["blockers"]
            audits.append(
                "disposition", "dispose", actor=actor,
                dossier_id=str(record.get("dossier_id", "") or ""),
                allowed=event["executed"],
                rule=(blockers[0]["rule"] if blockers else ""),
                detail=event, at=now)
            self._send_json(
                {"valid": True, "event": event},
                200 if event["executed"] else 409)

    return Handler


# ---------------------------------------------------------------------------
# Control-plane + auth UI (REQ-079/085/086) — self-contained, vendored CSS/JS,
# offline, WCAG 2.1 AA (every control labelled; lang set; visible focus). The
# "Prism" design language (depth/glass/gradient) is shared with the tenant shell.
# ---------------------------------------------------------------------------

_PRISM_CSS = """
:root{--bg:#0b1220;--panel:rgba(255,255,255,.06);--line:rgba(255,255,255,.14);
--ink:#eef3fb;--mut:#9fb0c9;--brand:#5b8cff;--ok:#37d39b;--warn:#ffd166;
--bad:#ff6b6b;--radius:14px}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
color:var(--ink);background:
radial-gradient(1200px 600px at 10% -10%,#1a2c52 0,transparent 60%),
radial-gradient(900px 500px at 110% 10%,#3a1f57 0,transparent 55%),var(--bg)}
a{color:var(--brand)} .mut{color:var(--mut)}
header.topbar{display:flex;align-items:center;gap:14px;padding:14px 22px;
border-bottom:1px solid var(--line);
background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.02));
backdrop-filter:blur(8px)}
.brand{font-weight:700;letter-spacing:.3px}
.badge-owner{margin-left:auto;font-size:12px;padding:4px 10px;border-radius:999px;
background:rgba(91,140,255,.18);border:1px solid var(--line)}
main{max-width:1080px;margin:0 auto;padding:24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
padding:20px;margin:0 0 20px;box-shadow:0 10px 30px rgba(0,0,0,.25)}
h1{font-size:22px;margin:.2em 0} h2{font-size:17px;margin:.2em 0 .6em}
label{display:block;font-size:13px;color:var(--mut);margin:10px 0 4px}
input,select{width:100%;padding:10px 12px;border-radius:10px;color:var(--ink);
background:rgba(0,0,0,.25);border:1px solid var(--line)}
input:focus,select:focus,button:focus{outline:3px solid var(--brand);outline-offset:1px}
button{cursor:pointer;border:1px solid var(--line);border-radius:10px;
padding:9px 14px;color:var(--ink);font-weight:600;
background:linear-gradient(180deg,rgba(91,140,255,.35),rgba(91,140,255,.18))}
button.ghost{background:rgba(255,255,255,.06)}
button.danger{background:linear-gradient(180deg,rgba(255,107,107,.35),rgba(255,107,107,.15))}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);font-size:14px}
th{color:var(--mut);font-weight:600}
.pill{font-size:12px;padding:2px 9px;border-radius:999px;border:1px solid var(--line)}
.pill.active{color:var(--ok)} .pill.suspended{color:var(--warn)}
.pill.deleted{color:var(--bad)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
.row>div{flex:1;min-width:160px}
.notice{padding:10px 14px;border-radius:10px;border:1px solid var(--line);
background:rgba(91,140,255,.12);margin:10px 0}
.notice.err{background:rgba(255,107,107,.14)}
.feat{display:inline-flex;gap:6px;align-items:center;margin:4px 10px 4px 0;font-size:13px}
.feat input{width:auto}
"""

OWNER_CONSOLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ANDS Platform — Owner Control Plane</title>
<style>""" + _PRISM_CSS + """</style>
</head>
<body>
<header class="topbar">
  <span class="brand">ANDS Platform</span>
  <span class="mut">Owner Control Plane</span>
  <span class="badge-owner" id="who">not signed in</span>
</header>
<main>
  <div id="msg" role="status" aria-live="polite"></div>

  <section class="card" id="loginCard">
    <h1>Owner sign-in</h1>
    <p class="mut">Restricted to the platform owner. Tenant users cannot reach
    this console.</p>
    <form id="loginForm">
      <label for="oe">Owner email</label>
      <input id="oe" name="email" type="email" autocomplete="username" required>
      <label for="op">Password</label>
      <input id="op" name="password" type="password"
             autocomplete="current-password" required>
      <p><button type="submit">Sign in</button></p>
    </form>
  </section>

  <div id="console" hidden>
    <section class="card">
      <h2>Provision a tenant</h2>
      <form id="provForm">
        <div class="row">
          <div><label for="pc">Company</label>
            <input id="pc" name="company" required></div>
          <div><label for="pe">Admin email</label>
            <input id="pe" name="email" type="email" required></div>
          <div style="flex:0"><label aria-hidden="true">&nbsp;</label>
            <button type="submit">Create tenant</button></div>
        </div>
      </form>
    </section>

    <section class="card">
      <h2>Tenants</h2>
      <table>
        <caption class="mut" style="text-align:left">All tenant workspaces,
        their plan, status and usage.</caption>
        <thead><tr><th>Company</th><th>Status</th><th>Plan</th>
        <th>Records</th><th>Actions</th></tr></thead>
        <tbody id="tenantRows"></tbody>
      </table>
    </section>

    <section class="card">
      <h2>Plans</h2>
      <div id="planList"></div>
      <h2 style="margin-top:18px">New plan</h2>
      <form id="planForm">
        <label for="pn">Plan name</label>
        <input id="pn" name="name" required>
        <label>Features</label>
        <div id="featBoxes"></div>
        <p><button type="submit">Create plan</button></p>
      </form>
    </section>

    <section class="card">
      <h2>Control-plane audit</h2>
      <table>
        <thead><tr><th>When</th><th>Actor</th><th>Action</th>
        <th>Tenant</th></tr></thead>
        <tbody id="auditRows"></tbody>
      </table>
    </section>
  </div>
</main>
<script>
var TOKEN = localStorage.getItem('ands_owner_token') || '';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function msg(t,err){var m=document.getElementById('msg');
  m.className='notice'+(err?' err':'');m.textContent=t;}
function api(method,path,body){
  var h={'Content-Type':'application/json'};
  if(TOKEN) h['Authorization']='Bearer '+TOKEN;
  return fetch(path,{method:method,headers:h,
    body:body?JSON.stringify(body):undefined}).then(function(r){
    return r.json().then(function(j){return {ok:r.ok,status:r.status,data:j};});});}
var FEATURES=[];
function showConsole(){
  document.getElementById('loginCard').hidden=true;
  document.getElementById('console').hidden=false;
  document.getElementById('who').textContent='owner';
  loadPlans();loadTenants();loadAudit();}
document.getElementById('loginForm').addEventListener('submit',function(e){
  e.preventDefault();
  api('POST','/api/auth/login',{email:oe.value,password:op.value})
   .then(function(r){
     if(!r.ok||r.data.role!=='owner'){msg('Sign-in failed: '+
        (r.data.detail||r.data.error||'not an owner'),true);return;}
     TOKEN=r.data.token;localStorage.setItem('ands_owner_token',TOKEN);
     msg('Signed in.');showConsole();});});
function loadTenants(){api('GET','/api/owner/tenants').then(function(r){
  if(!r.ok){return;}
  var tb=document.getElementById('tenantRows');tb.innerHTML='';
  r.data.tenants.forEach(function(t){
    var tr=document.createElement('tr');
    tr.innerHTML='<td>'+esc(t.name)+'<br><span class="mut">'+esc(t.id.slice(0,8))+
      '</span></td><td><span class="pill '+esc(t.status)+'">'+esc(t.status)+
      '</span></td><td>'+esc(t.plan_id)+'</td><td>'+esc((t.usage||{}).records)+
      '</td><td></td>';
    var act=tr.lastChild;
    if(t.status!=='deleted'){
      act.appendChild(btn(t.status==='suspended'?'Resume':'Suspend','ghost',
        function(){tenantAction(t.id,t.status==='suspended'?'resume':'suspend');}));
      act.appendChild(btn('Delete','danger',function(){
        tenantAction(t.id,'delete');}));
      act.appendChild(btn('Entitlements','ghost',function(){
        editEntitlements(t);}));}
    tb.appendChild(tr);});});}
function btn(label,cls,fn){var b=document.createElement('button');
  b.type='button';b.className=cls;b.textContent=label;b.style.marginRight='6px';
  b.addEventListener('click',fn);return b;}
function tenantAction(id,action){
  api('POST','/api/owner/tenants/'+id+'/'+action,{}).then(function(r){
    msg(r.ok?('Tenant '+action+'d.'):(r.data.error||'failed'),!r.ok);
    loadTenants();loadAudit();});}
function editEntitlements(t){
  api('GET','/api/owner/tenants/'+t.id+'/entitlements').then(function(r){
    if(!r.ok)return;var feats=r.data.features;var lines=FEATURES.map(function(f){
      var e=feats[f.key];return f.label+': '+(e.enabled?'on':'off')+
        ' ('+e.source+')';}).join('\\n');
    var pick=prompt('Toggle a feature for '+t.name+
      '.\\nType: <feature> on|off|clear\\n\\n'+lines+
      '\\n\\nFeatures: '+FEATURES.map(function(f){return f.key;}).join(', '));
    if(!pick)return;var parts=pick.trim().split(/\\s+/);
    var body={feature:parts[0]};
    if(parts[1]==='clear'){body.enabled=null;}
    else{body.enabled=(parts[1]==='on');}
    api('POST','/api/owner/tenants/'+t.id+'/overrides',body).then(function(r2){
      msg(r2.ok?'Entitlement updated.':(r2.data.error||'failed'),!r2.ok);
      loadTenants();loadAudit();});});}
function loadPlans(){api('GET','/api/owner/plans').then(function(r){
  if(!r.ok)return;FEATURES=r.data.features;
  var fb=document.getElementById('featBoxes');fb.innerHTML='';
  FEATURES.forEach(function(f){var id='f_'+f.key;
    var s=document.createElement('span');s.className='feat';
    s.innerHTML='<input type="checkbox" id="'+id+'" value="'+f.key+'" checked>'+
      '<label for="'+id+'" style="display:inline;margin:0">'+esc(f.label)+'</label>';
    fb.appendChild(s);});
  var pl=document.getElementById('planList');pl.innerHTML='';
  r.data.plans.forEach(function(p){var d=document.createElement('div');
    d.className='notice';d.textContent=p.name+' — '+p.features.length+
      ' features';pl.appendChild(d);});});}
document.getElementById('provForm').addEventListener('submit',function(e){
  e.preventDefault();
  api('POST','/api/owner/tenants',{company:pc.value,email:pe.value})
   .then(function(r){
     if(!r.ok){msg(r.data.detail||r.data.error||'failed',true);return;}
     msg('Tenant created. Invite password: '+r.data.invite_password);
     pc.value='';pe.value='';loadTenants();loadAudit();});});
document.getElementById('planForm').addEventListener('submit',function(e){
  e.preventDefault();var feats=[];
  document.querySelectorAll('#featBoxes input:checked').forEach(function(c){
    feats.push(c.value);});
  api('POST','/api/owner/plans',{name:pn.value,features:feats}).then(function(r){
    msg(r.ok?'Plan created.':(r.data.error||'failed'),!r.ok);
    if(r.ok){pn.value='';loadPlans();}});});
function loadAudit(){api('GET','/api/owner/audit').then(function(r){
  if(!r.ok)return;var tb=document.getElementById('auditRows');tb.innerHTML='';
  r.data.audit.forEach(function(a){var tr=document.createElement('tr');
    tr.innerHTML='<td class="mut">'+esc((a.ts||'').slice(0,19))+'</td><td>'+
      esc(a.actor)+'</td><td>'+esc(a.action)+'</td><td>'+
      esc((a.tenant_id||'').slice(0,8))+'</td>';tb.appendChild(tr);});});}
if(TOKEN){api('GET','/api/auth/me').then(function(r){
  if(r.ok&&r.data.role==='owner'){showConsole();}
  else{localStorage.removeItem('ands_owner_token');TOKEN='';}});}
</script>
</body>
</html>"""

AUTH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ANDS Portal — Sign in or register your company</title>
<style>""" + _PRISM_CSS + """</style>
</head>
<body>
<header class="topbar"><span class="brand">ANDS Portal</span>
<span class="mut">Health Canada drug submissions</span></header>
<main>
  <div id="msg" role="status" aria-live="polite"></div>
  <section class="card">
    <h1>Register your company</h1>
    <p class="mut">Self-serve sign-up creates your isolated workspace with every
    feature enabled.</p>
    <form id="signupForm">
      <label for="sc">Company name</label>
      <input id="sc" name="company" required>
      <label for="se">Your email (becomes the tenant admin)</label>
      <input id="se" name="email" type="email" autocomplete="username" required>
      <label for="sp">Choose a password</label>
      <input id="sp" name="password" type="password"
             autocomplete="new-password" required>
      <p><button type="submit">Create workspace</button></p>
    </form>
  </section>
  <section class="card">
    <h1>Sign in</h1>
    <form id="loginForm">
      <label for="le">Email</label>
      <input id="le" name="email" type="email" autocomplete="username" required>
      <label for="lp">Password</label>
      <input id="lp" name="password" type="password"
             autocomplete="current-password" required>
      <p><button type="submit">Sign in</button></p>
    </form>
  </section>
</main>
<script>
function esc(s){return String(s==null?'':s);}
function msg(t,err){var m=document.getElementById('msg');
  m.className='notice'+(err?' err':'');m.textContent=t;}
function post(path,body){return fetch(path,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  .then(function(r){return r.json().then(function(j){
    return {ok:r.ok,data:j};});});}
document.getElementById('signupForm').addEventListener('submit',function(e){
  e.preventDefault();
  post('/api/auth/signup',{company:sc.value,email:se.value,password:sp.value})
   .then(function(r){
     if(!r.ok){msg(r.data.detail||r.data.error||'sign-up failed',true);return;}
     localStorage.setItem('ands_token',r.data.token);
     msg('Workspace created. Redirecting…');location.href='/';});});
document.getElementById('loginForm').addEventListener('submit',function(e){
  e.preventDefault();
  post('/api/auth/login',{email:le.value,password:lp.value}).then(function(r){
    if(!r.ok){msg(r.data.detail||r.data.error||'sign-in failed',true);return;}
    localStorage.setItem('ands_token',r.data.token);
    location.href=r.data.redirect||'/';});});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Single-page UI
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ANDS Submission Portal</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%231a4a7a'/%3E%3Ctext x='8' y='12' font-size='11' text-anchor='middle' fill='white' font-family='sans-serif'%3EA%3C/text%3E%3C/svg%3E">
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
  #boot-overlay { position:fixed; inset:0; z-index:9999; background:var(--bg);
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:14px; color:#4a5b6d; font-size:14px; }
  #boot-overlay .spinner { width:30px; height:30px; border:3px solid var(--line);
    border-top-color:#13344f; border-radius:50%; animation:spin .8s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  body.ready #boot-overlay { display:none; }
  /* REQ-065: REP stylesheet preview table */
  table.rep-render { width:100%; border-collapse:collapse; font-size:13px; }
  table.rep-render th { text-align:left; padding:4px 8px; background:var(--surface,#f4f7fb);
    font-weight:600; width:36%; border:1px solid var(--line,#dce3ec); }
  table.rep-render td { padding:4px 8px; border:1px solid var(--line,#dce3ec); }
  table.rep-render .rep-blank { color:#aaa; font-style:italic; }
  table.rep-render .rep-code { background:#e8f0fe; color:#1a56a0; border-radius:3px;
    padding:1px 4px; font-family:monospace; font-size:11px; }
  table.rep-render .rep-group { background:var(--accent-soft,#eef3ff); font-weight:700; }
  table.rep-render .rep-occ { font-size:12px; }
  table.rep-render .rep-empty { color:#aaa; font-style:italic; }
</style>
</head>
<body>
<div id="boot-overlay" role="status" aria-live="polite">
  <div class="spinner"></div>
  <div id="boot-msg">Starting ANDS Portal — bringing up web &amp; API servers…</div>
</div>
<header>
  <h1>ANDS Submission Portal</h1>
  <p>Abbreviated New Drug Submission intake &amp; eCTD sequence validation</p>
</header>
<main>
  <section class="card">
    <h2>New submission</h2>
    <form id="form">
      <label for="fld1">Applicant / company name</label>
      <input id="fld1" name="applicant" aria-label="Applicant / company name" placeholder="Acme Generics Inc." value="Acme Generics Inc.">
      <label for="fld2">Drug product name</label>
      <input id="fld2" name="drug_product" aria-label="Drug product name" placeholder="Metformin HCl 500 mg tablets" value="Metformin HCl 500 mg tablets">
      <div class="row">
        <div>
          <label for="fld3">Dossier ID</label>
          <input id="fld3" name="dossier_id" aria-label="Dossier ID" placeholder="e123456" value="e123456">
          <div class="hint">lowercase 'e' + 6 or 7 digits</div>
        </div>
        <div>
          <label for="fld4">Sequence</label>
          <input id="fld4" name="sequence" aria-label="Sequence" placeholder="0000" value="0000">
          <div class="hint">4 digits; first must be 0000</div>
        </div>
      </div>
      <label for="fld5">Submission type</label>
      <input id="fld5" name="submission_type" aria-label="Submission type" value="ANDS" readonly>
      <label for="fld6">Contact email</label>
      <input id="fld6" name="contact_email" aria-label="Contact email" placeholder="ra@acme.example" value="ra@acme.example">
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

  <section class="card" style="grid-column:1/-1">
    <h2>REP single-entry transaction (CO / RT / PI)</h2>
    <p class="hint">Enter REP identifiers once — the portal emits the REP CO/RT/PI
      XML with immutable machine-generated filenames, the eCTD
      <code>m1/ca/ca-regional.xml</code> backbone metadata, and a cover letter
      from its own template, all without re-keying.</p>
    <form id="repform">
      <div class="row">
        <div>
          <label for="fld7">Company ID (HC-assigned opaque token)</label>
          <input id="fld7" name="company_id" aria-label="Company ID (HC-assigned opaque token)" placeholder="K18276" value="K18276">
          <div class="hint">alphanumeric token — not a 5-digit number</div>
        </div>
        <div>
          <label for="fld8">Dossier ID</label>
          <input id="fld8" name="dossier_id" aria-label="Dossier ID" placeholder="e123456" value="e123456">
          <div class="hint">'e' + 6 or 7 digits</div>
        </div>
      </div>
      <div class="row">
        <div>
          <label for="activitySelect">Regulatory activity type</label>
          <select name="activity_type" id="activitySelect" aria-label="Regulatory activity type"></select>
          <div class="hint">from HC's Module 1 controlled vocabulary</div>
        </div>
        <div>
          <label for="fld9">Sequence</label>
          <input id="fld9" name="sequence" aria-label="Sequence" placeholder="0000" value="0000">
        </div>
      </div>
      <div class="row">
        <div>
          <label for="fld10">Applicant / company name</label>
          <input id="fld10" name="applicant" aria-label="Applicant / company name" placeholder="Acme Generics Inc." value="Acme Generics Inc.">
        </div>
        <div>
          <label for="fld11">Drug product name</label>
          <input id="fld11" name="drug_product" aria-label="Drug product name" placeholder="Metformin HCl 500 mg tablets" value="Metformin HCl 500 mg tablets">
        </div>
      </div>
      <div class="row">
        <div>
          <label for="fld12">DIN (optional, 8 digits)</label>
          <input id="fld12" name="din" aria-label="DIN (optional, 8 digits)" placeholder="02123456">
        </div>
        <div>
          <label for="fld13">PI template required?</label>
          <input id="fld13" type="checkbox" name="pi_required" aria-label="PI template required" style="width:auto">
        </div>
      </div>
      <div class="actions">
        <button type="button" class="primary"
          onclick="assemble()">Assemble transaction</button>
      </div>
    </form>
    <div id="represult"></div>
  </section>

  <section class="card" style="grid-column:1/-1">
    <h2>eCTD dossier — tree, backbones, leaf lifecycle &amp; current view</h2>
    <p class="hint">Drive the Module 1 tree from HC's versioned
      'Organization &amp; document placement' table, assemble leaf operations
      (new / replace / append / delete) across sequences, reconstruct the live
      'current view', and export both deterministic backbones (ICH
      <code>index.xml</code> + CA <code>m1/ca/ca-regional.xml</code>) with
      per-leaf MD5 checksums &amp; <code>index-md5.txt</code>.</p>

    <div class="row" style="align-items:flex-end">
      <div>
        <label for="newDossierId">New dossier ID</label>
        <input aria-label="New dossier ID" id="newDossierId" placeholder="e123456">
        <div class="hint">'e' + 6 or 7 digits</div>
      </div>
      <div style="flex:0 0 auto">
        <button type="button" class="primary"
          onclick="createDossier()">Create dossier</button>
      </div>
      <div>
        <label for="dossierSelect">Open existing dossier</label>
        <select aria-label="Open existing dossier" id="dossierSelect" onchange="loadDossier(this.value)"></select>
      </div>
    </div>
    <div id="dossierMsg" class="hint" style="margin-top:8px"></div>

    <div id="dossierPanel" style="display:none;margin-top:18px">
      <h2 style="margin-top:0">Module 1 placement (v<span id="placementVer"></span>)</h2>
      <div id="placementTable"></div>

      <h2 style="margin-top:18px">Add leaf operation</h2>
      <form id="leafForm">
        <div class="row">
          <div>
            <label for="fld14">Sequence</label>
            <input id="fld14" name="sequence" aria-label="Sequence" placeholder="0000" value="0000">
          </div>
          <div>
            <label for="fld15">Operation</label>
            <select id="fld15" aria-label="Operation" name="operation">
              <option value="new">new</option>
              <option value="replace">replace</option>
              <option value="append">append</option>
              <option value="delete">delete</option>
            </select>
          </div>
          <div>
            <label for="leafHeading">Heading</label>
            <select aria-label="Heading" name="heading" id="leafHeading"></select>
          </div>
        </div>
        <div class="row">
          <div>
            <label for="fld16">Leaf ID</label>
            <input id="fld16" aria-label="Leaf ID" name="leaf_id" placeholder="m1-0-1-cover-letter-0000">
          </div>
          <div>
            <label for="fld17">Title</label>
            <input id="fld17" aria-label="Title" name="title" placeholder="Cover Letter">
          </div>
        </div>
        <div class="row">
          <div>
            <label for="fld18">Modifies prior leaf (replace/append/delete)</label>
            <input id="fld18" aria-label="Modifies prior leaf (replace/append/delete)" name="modified_leaf" placeholder="leaf id in current view">
          </div>
          <div>
            <label for="fld19">Reuse file from prior leaf (REQ-019)</label>
            <input id="fld19" aria-label="Reuse file from prior leaf (REQ-019)" name="reused_from" placeholder="prior leaf id (optional)">
          </div>
        </div>
        <label for="fld20">File content (bytes shipped for this leaf)</label>
        <input id="fld20" aria-label="File content (bytes shipped for this leaf)" name="content" placeholder="document bytes…">
        <div class="actions">
          <button type="button" class="primary" onclick="addLeaf()">Add leaf</button>
        </div>
      </form>
      <div id="leafMsg"></div>

      <h2 style="margin-top:18px">Current view (live leaves)</h2>
      <div id="currentView"></div>

      <h2 style="margin-top:18px">Export sequence</h2>
      <div class="row" style="align-items:flex-end">
        <div>
          <label for="exportSeq">Sequence to export</label>
          <input aria-label="Sequence to export" id="exportSeq" placeholder="0000">
        </div>
        <div style="flex:0 0 auto">
          <button type="button" class="primary"
            onclick="exportSequence()">Build &amp; verify backbones</button>
        </div>
      </div>
      <div id="exportResult"></div>
    </div>
  </section>

  <section class="card" style="grid-column:1/-1">
    <h2>Pre-submission validation (HC versioned ruleset)</h2>
    <p class="hint">Run Health Canada's two-tier (Error/Warning) validation engine
      over an assembled transaction against a <em>pinned</em> ruleset version —
      continuously inline during authoring (severity-coloured gutter with
      one-click fixes), as a downloadable pre-submission report (categorised
      defects + backbone preview + per-leaf MD5), as a cross-document consistency
      &amp; packaging gate, and as a state-retaining package attempt that survives
      schema/service failures.</p>

    <div class="row" style="align-items:flex-end">
      <div style="flex:0 0 auto">
        <label for="rulesetSelect">Ruleset version</label>
        <select aria-label="Ruleset version" id="rulesetSelect"></select>
        <div class="hint" id="rulesetHint"></div>
      </div>
      <div style="flex:0 0 auto">
        <button type="button" class="ghost" onclick="loadRuleset()">Show rules</button>
      </div>
    </div>
    <div id="rulesetTable" style="margin-top:10px"></div>

    <label style="margin-top:14px">Transaction context (JSON)</label>
    <textarea aria-label="Transaction context (JSON)" id="valCtx" rows="14" spellcheck="false"
      style="width:100%;font:12px/1.45 ui-monospace,Menlo,monospace;
             border:1px solid var(--line);border-radius:6px;padding:10px"></textarea>
    <div class="hint">Edit to model files / leaves / REP / cover_letter /
      ca_regional / module5_studies. The pre-filled sample contains a few
      deliberate defects (an unreadable file — A02, an encrypted PDF — A09, a
      DIN disagreement, a missing STF) so the engine has something to flag.</div>

    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="primary" onclick="valRun()">Run validation</button>
      <button type="button" class="ghost" onclick="valInline()">Inline gutter</button>
      <button type="button" class="ghost" onclick="valReport()">Build report</button>
      <button type="button" class="ghost" onclick="valDownload()">Download report</button>
      <button type="button" class="ghost" onclick="valConsistency()">Consistency</button>
      <button type="button" class="ghost" onclick="valPackage()">Packaging gate</button>
      <button type="button" class="ghost" onclick="valAttempt(true)">Package (ESG down)</button>
      <button type="button" class="ghost" onclick="valAttempt(false)">Package (services up)</button>
    </div>
    <div id="valResult" style="margin-top:14px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>Canadian Reference Product &amp; pharmaceutical equivalence (REQ-007)</h2>
    <p class="hint">Capture the structured CRP (brand name, DIN, strength, dosage
      form, innovator/manufacturer), the foreign-CRP justification path, and the
      proposed generic — the portal checks pharmaceutical equivalence (identical
      medicinal ingredient(s) in a comparable dosage form).</p>
    <textarea id="crpCtx" rows="13" spellcheck="false"
      aria-label="Canadian Reference Product context (JSON)"
      style="width:100%;font:12px/1.45 ui-monospace,Menlo,monospace;
             border:1px solid var(--line);border-radius:6px;padding:10px"></textarea>
    <div class="actions"><button type="button" class="primary"
        onclick="crpValidate()">Validate CRP</button></div>
    <div id="crpResult" style="margin-top:12px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>CS-BE builder &amp; versioned BE ruleset (REQ-008 / REQ-063)</h2>
    <p class="hint">Build the Comparative Studies — Bioequivalence evidence for a
      BE-only ANDS: the CS-BE electronic copy lands in Module 1.6, pivotal study
      reports link into Module 5.3.1.2, no Module 2.7.1 is generated (2.4–2.7
      suppressed), and Cmax acceptance branches by ruleset version —
      point-estimate 80.0–125.0% (legacy / non-IR) vs the full 90% CI
      80.00–125.00% under ICH M13A (IR solid oral, effective 2025-12-27). The
      CS-BE template is DRAFT (2004-05-18).</p>
    <textarea id="csbeCtx" rows="16" spellcheck="false"
      aria-label="CS-BE bioequivalence study context (JSON)"
      style="width:100%;font:12px/1.45 ui-monospace,Menlo,monospace;
             border:1px solid var(--line);border-radius:6px;padding:10px"></textarea>
    <div class="actions">
      <button type="button" class="ghost" onclick="beEvaluate()">Evaluate BE</button>
      <button type="button" class="primary" onclick="csBeBuild()">Build CS-BE</button>
    </div>
    <div id="csbeResult" style="margin-top:12px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>Quality Overall Summary — Chemical Entities, Module 2.3 (REQ-061)</h2>
    <p class="hint">Generate, fill and validate the HC QOS-CE template. A missing
      or structurally-incomplete QOS-CE is flagged as a screening-deficiency
      risk.</p>
    <textarea id="qosCtx" rows="12" spellcheck="false"
      aria-label="Quality Overall Summary (QOS-CE) context (JSON)"
      style="width:100%;font:12px/1.45 ui-monospace,Menlo,monospace;
             border:1px solid var(--line);border-radius:6px;padding:10px"></textarea>
    <div class="actions">
      <button type="button" class="ghost" onclick="qosGate()">Screening gate</button>
      <button type="button" class="primary" onclick="qosBuild()">Build QOS-CE</button>
    </div>
    <div id="qosResult" style="margin-top:12px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>Study Tagging File generation &amp; validation (REQ-064)</h2>
    <p class="hint">For transactions with Module 4/5 study data the portal
      generates conformant STF leaves and validates them as their own HC eCTD
      validation category — independent of the other validation categories.</p>
    <textarea id="stfCtx" rows="12" spellcheck="false"
      aria-label="Study Tagging File (STF) context (JSON)"
      style="width:100%;font:12px/1.45 ui-monospace,Menlo,monospace;
             border:1px solid var(--line);border-radius:6px;padding:10px"></textarea>
    <div class="actions">
      <button type="button" class="ghost" onclick="stfGenerate()">Generate STFs</button>
      <button type="button" class="primary" onclick="stfValidate()">Validate STF category</button>
    </div>
    <div id="stfResult" style="margin-top:12px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>Transmission Console — FDA ESG NextGen (REQ-003/025/026/027/046/058)</h2>
    <p class="hint">CESG rides on the FDA ESG (no direct HC endpoint). Configure
      the ESG account, prove a Test-gateway round-trip before Production, then
      route by size (&le;10&nbsp;GB &rarr; gateway, &gt;10&nbsp;GB &rarr;
      physical media), serialise one transaction at a time per dossier, and
      reconcile every transaction by Core&nbsp;ID.</p>
    <div class="row">
      <div>
        <label for="txnDossier">Dossier ID</label>
        <input aria-label="Dossier ID" id="txnDossier" value="e123456">
      </div>
      <div>
        <label for="txnSequence">Sequence</label>
        <input aria-label="Sequence" id="txnSequence" value="0000">
      </div>
      <div>
        <label for="txnSize">Package size (GB)</label>
        <input aria-label="Package size (GB)" id="txnSize" value="6" type="number" step="0.1">
      </div>
    </div>
    <div class="row">
      <div>
        <label for="txnAccount">ESG account type</label>
        <select aria-label="ESG account type" id="txnAccount" style="width:100%;padding:9px 10px;
          border:1px solid var(--line);border-radius:6px;font:inherit">
          <option value="WebTrader">WebTrader (browser upload)</option>
          <option value="AS2">AS2 / EDIINT (machine-to-machine)</option>
        </select>
      </div>
      <div>
        <label for="txnCert">X.509 certificate (PEM)</label>
        <input aria-label="X.509 certificate (PEM)" id="txnCert" value="-----BEGIN CERTIFICATE-----demo-----END CERTIFICATE-----">
      </div>
    </div>
    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="ghost" onclick="txnConfigure()">Configure ESG</button>
      <button type="button" class="ghost" onclick="txnTestRoundTrip()">Test round-trip</button>
      <button type="button" class="ghost" onclick="txnRoute()">Pre-flight route</button>
      <button type="button" class="primary" onclick="txnSubmit()">Submit transaction</button>
    </div>
    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="ghost" onclick="txnAck('mdn')">Receive MDN</button>
      <button type="button" class="ghost" onclick="txnAck('fda')">FDA Ack</button>
      <button type="button" class="ghost" onclick="txnAck('hc')">HC Ack (delivered)</button>
      <button type="button" class="ghost" onclick="txnMonitor()">Run monitors</button>
      <button type="button" class="ghost" onclick="txnResend()">Resend</button>
    </div>
    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="ghost" onclick="txnMedia('build')">Build media</button>
      <button type="button" class="ghost" onclick="txnMedia('ship')">Ship media</button>
      <button type="button" class="ghost" onclick="txnMedia('receive')">Media received</button>
      <button type="button" class="ghost" onclick="txnLoad()">Refresh status</button>
    </div>
    <div id="txnResult" style="margin-top:12px"></div>
    <div id="txnStatus" style="margin-top:12px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>Post-receipt DSTS lifecycle &amp; deadline engine (REQ-030/031/062)</h2>
    <p class="hint">A transaction is only tracked here once it is
      <strong>received by Health Canada</strong> (the HC Acknowledgement Receipt,
      not the MDN). Processing &rarr; Screening (45&nbsp;d) &rarr; Review &rarr;
      decision (NOC/NOD/NON). The Inactive window (45 vs 90) is derived from the
      submission type; the Review clock stops during sponsor response windows; a
      missed service standard surfaces the statutory 25% fee credit.</p>
    <div class="row">
      <div>
        <label for="lcDossier">Dossier ID</label>
        <input aria-label="Dossier ID" id="lcDossier" value="e654321">
      </div>
      <div>
        <label for="lcType">Submission type</label>
        <select aria-label="Submission type" id="lcType" style="width:100%;padding:9px 10px;
          border:1px solid var(--line);border-radius:6px;font:inherit">
          <option value="ANDS">ANDS (180 d, Inactive-90)</option>
          <option value="SANDS">SANDS (180 d)</option>
          <option value="DIN">DIN (180 d, Inactive-45)</option>
          <option value="NC">Notifiable Change (90 d, 90% KPI)</option>
        </select>
      </div>
      <div>
        <label for="lcCore">Core ID</label>
        <input aria-label="Core ID" id="lcCore" value="CORE-654321">
      </div>
    </div>
    <div class="row">
      <div>
        <label for="lcFee">Fee paid (CAD)</label>
        <input aria-label="Fee paid (CAD)" id="lcFee" value="70750" type="number" step="0.01">
      </div>
      <div>
        <label for="lcTier">Clarifax tier</label>
        <select aria-label="Clarifax tier" id="lcTier" style="width:100%;padding:9px 10px;
          border:1px solid var(--line);border-radius:6px;font:inherit">
          <option value="180-300">180-300 day standard (default 15 d)</option>
          <option value="0-90">0-90 day standard (default 5 d)</option>
        </select>
      </div>
      <div>
        <label for="lcOverride">Clarifax override (days, optional)</label>
        <input aria-label="Clarifax override (days, optional)" id="lcOverride" placeholder="e.g. 2" type="number">
      </div>
    </div>
    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="primary" onclick="lcStart()">Start (received by HC)</button>
      <button type="button" class="ghost" onclick="lcTransition('to_screening')">To Screening</button>
      <button type="button" class="ghost" onclick="lcScreening('SAL')">SAL &rarr; Review</button>
      <button type="button" class="ghost" onclick="lcScreening('SDN')">SDN (Inactive-45)</button>
    </div>
    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="ghost" onclick="lcClarifax()">Issue clarifax</button>
      <button type="button" class="ghost" onclick="lcTransition('resume_clock')">Sponsor responded (resume)</button>
      <button type="button" class="ghost" onclick="lcDecision('NOC')">NOC (approve)</button>
      <button type="button" class="ghost" onclick="lcDecision('NOD')">NOD</button>
      <button type="button" class="ghost" onclick="lcServiceStandard()">Check service standard</button>
      <button type="button" class="ghost" onclick="lcLoad()">Refresh</button>
    </div>
    <div id="lcResult" style="margin-top:12px"></div>
    <div id="lcStatus" style="margin-top:12px"></div>
  </section>

  <section class="card">
    <h2>HC deadline calendar (REQ-052)</h2>
    <p class="hint">Calendar vs business-day basis per notice type, Canadian
      federal statutory holidays and the configured review timezone. A due date
      landing on a weekend/holiday is rolled forward and the adjustment is
      surfaced &mdash; never silent.</p>
    <div class="row">
      <div>
        <label for="calStart">Start date</label>
        <input aria-label="Start date" id="calStart" value="2025-06-30">
      </div>
      <div>
        <label for="calDays">Days</label>
        <input aria-label="Days" id="calDays" value="1" type="number">
      </div>
    </div>
    <div class="row">
      <div>
        <label for="calNotice">Notice type</label>
        <select aria-label="Notice type" id="calNotice" style="width:100%;padding:9px 10px;
          border:1px solid var(--line);border-radius:6px;font:inherit">
          <option value="clarifax">clarifax (calendar)</option>
          <option value="sdn">SDN (calendar)</option>
          <option value="nod">NOD (calendar)</option>
          <option value="screening_target">screening target (business)</option>
          <option value="processing_target">processing target (business)</option>
        </select>
      </div>
      <div>
        <label for="calBasis">Basis override (optional)</label>
        <select aria-label="Basis override (optional)" id="calBasis" style="width:100%;padding:9px 10px;
          border:1px solid var(--line);border-radius:6px;font:inherit">
          <option value="">(per notice type)</option>
          <option value="calendar">calendar</option>
          <option value="business">business</option>
        </select>
      </div>
    </div>
    <div class="actions">
      <button type="button" class="primary" onclick="calCompute()">Compute deadline</button>
      <button type="button" class="ghost" onclick="calHolidays()">Show holidays</button>
    </div>
    <div id="calResult" style="margin-top:12px"></div>
  </section>

  <section class="card">
    <h2>Rejection &mdash; eCTD Validation Report ingest (REQ-029)</h2>
    <p class="hint">Paste the emailed eCTD Validation Report. It is correlated to
      the originating transaction by <strong>Core ID</strong> and each reported
      error is mapped back to the exact leaf/node in the dossier tree for
      correction in the next sequence.</p>
    <label for="rejDossier">Dossier ID (for tree/ledger correlation)</label>
    <input aria-label="Dossier ID (for tree/ledger correlation)" id="rejDossier" value="e654321">
    <label for="rejReport">Validation report text</label>
    <textarea aria-label="Validation report text" id="rejReport" rows="7" style="width:100%;padding:9px 10px;
      border:1px solid var(--line);border-radius:6px;font:13px monospace">Core ID: CORE-654321
Dossier ID: e654321
Validation Result: FAIL
[ERROR] HC.1.2.3 | m1/cover.pdf | leaf:cover-001 | Missing PDF bookmark
[WARNING] HC.9.1 | m1/regional.xml | node:/ectd | minor metadata note</textarea>
    <div class="actions">
      <button type="button" class="primary" onclick="rejIngest()">Ingest report</button>
    </div>
    <div id="rejResult" style="margin-top:12px"></div>
  </section>

  <section class="card" style="grid-column:1 / -1">
    <h2>Fees, mitigation &amp; annual Right-to-Sell (REQ-035/036/037)</h2>
    <p class="hint">An ANDS resolves to the Schedule&nbsp;1 <strong>Comparative
      studies</strong> grouping. The current fee is $70,750 (FY2025-26) /
      $71,953 (FY2026-27) &mdash; the $53,836 figure is a historical CPI-anchor
      seed only and is never shown as current. Small-business remission is 100%
      on a first-ever submission and 50% on a subsequent ANDS (attestation
      gated); payment may be deferred until NOC. The per-DIN annual Right-to-Sell
      fee is separate, varies by drug type, and is due each October&nbsp;1.</p>
    <div class="row">
      <div>
        <label for="feeDate">Submission date</label>
        <input aria-label="Submission date" id="feeDate" value="2025-06-30">
      </div>
      <div>
        <label for="feeGross">Gross fee (CAD, for mitigation)</label>
        <input aria-label="Gross fee (CAD, for mitigation)" id="feeGross" value="70750" type="number" step="0.01">
      </div>
      <div>
        <label for="feeDrugType">Drug type (Right-to-Sell)</label>
        <select aria-label="Drug type (Right-to-Sell)" id="feeDrugType" style="width:100%;padding:9px 10px;
          border:1px solid var(--line);border-radius:6px;font:inherit">
          <option value="prescription">Prescription drug</option>
          <option value="non-prescription">Non-prescription drug</option>
          <option value="disinfectant">Disinfectant</option>
          <option value="biocide">Biocide</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div>
        <label><input type="checkbox" id="feeSmall"> Small business</label>
      </div>
      <div>
        <label><input type="checkbox" id="feeFirst"> First-ever submission</label>
      </div>
      <div>
        <label><input type="checkbox" id="feeAttest"> Attestation uploaded</label>
      </div>
      <div>
        <label><input type="checkbox" id="feeDefer"> Defer until NOC</label>
      </div>
      <div>
        <label><input type="checkbox" id="feePaid"> Right-to-Sell paid</label>
      </div>
    </div>
    <div class="actions" style="flex-wrap:wrap">
      <button type="button" class="primary" onclick="feeAnds()">Resolve ANDS fee</button>
      <button type="button" class="ghost" onclick="feeMitigation()">Evaluate mitigation</button>
      <button type="button" class="ghost" onclick="feeRightToSell()">Right-to-Sell status</button>
    </div>
    <div id="feeResult" style="margin-top:12px"></div>
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
    for (const e of data.errors) html += '<li>' + esc(e.message) + '</li>';
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
    html += '<tr><td>' + esc(s.id) + '</td><td>' + esc(s.dossier_id) + '</td><td>' +
            esc(s.sequence) + '</td><td>' + esc(s.drug_product) + '</td></tr>';
  }
  el.innerHTML = html + '</tbody></table>';
}

function repPayload() {
  const f = document.getElementById('repform');
  const d = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    d[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  }
  return d;
}

// Mirror rep.validate_assembly / validate_identifiers (REQ-042/043) on the
// client so an obviously-malformed form is reported inline WITHOUT firing a
// request the server is bound to reject — same pattern as addLeaf()'s guard.
// The server still re-validates as the source of truth (defence in depth).
function repValidate(d) {
  const errors = [];
  const required = {
    applicant: 'Applicant / company name',
    company_id: 'Company ID',
    dossier_id: 'Dossier ID',
    activity_type: 'Regulatory activity type',
    sequence: 'Sequence number',
    drug_product: 'Drug product name'
  };
  for (const f in required) {
    if (!String(d[f] == null ? '' : d[f]).trim()) {
      errors.push(required[f] + ' is required');
    }
  }
  const cid = String(d.company_id == null ? '' : d.company_id).trim();
  const did = String(d.dossier_id == null ? '' : d.dossier_id).trim();
  const seq = String(d.sequence == null ? '' : d.sequence).trim();
  const din = String(d.din == null ? '' : d.din).trim();
  if (cid && !/^[A-Za-z0-9]{2,12}$/.test(cid)) {
    errors.push("Company ID must be an HC-assigned alphanumeric token " +
      "(3-12 letters/digits, e.g. K18276) — it is NOT a 5-digit number");
  }
  if (did && !/^e[0-9]{6,7}$/.test(did)) {
    errors.push("Dossier ID must be 'e' followed by 6 or 7 digits " +
      "(e.g. e123456)");
  }
  if (seq && !/^[0-9]{4}$/.test(seq)) {
    errors.push("Sequence number must be exactly 4 digits (0000-9999)");
  }
  if (din && !/^[0-9]{8}$/.test(din)) {
    errors.push("DIN must be exactly 8 digits");
  }
  return errors;
}

async function loadActivityTypes() {
  const res = await fetch('/api/activity-types');
  const data = await res.json();
  const sel = document.getElementById('activitySelect');
  sel.innerHTML = '';
  for (const a of data.activity_types) {
    const o = document.createElement('option');
    o.value = a.code; o.textContent = a.label;
    if (a.code === 'ANDS') o.selected = true;
    sel.appendChild(o);
  }
}

function esc(s) {
  // Escape &<> AND both quote characters: rendered values land not only in
  // element text but inside double-quoted style/attribute contexts and inside
  // single-quoted JS strings in onclick handlers, so an unescaped " or ' would
  // break out (DOM-XSS). Escaping all five neutralises every such context.
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function assemble() {
  const el = document.getElementById('represult');
  const payload = repPayload();
  const localErrors = repValidate(payload);
  if (localErrors.length) {
    let html = '<span class="badge bad">FAIL</span> ' +
      localErrors.length + ' problem(s):<ul class="errs">';
    for (const m of localErrors) html += '<li>' + esc(m) + '</li>';
    el.innerHTML = html + '</ul>';
    return;
  }
  const res = await fetch('/api/transactions/assemble', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!data.valid) {
    let html = '<span class="badge bad">FAIL</span> ' +
      data.errors.length + ' problem(s):<ul class="errs">';
    for (const e of data.errors) html += '<li>' + esc(e.message) + '</li>';
    el.innerHTML = html + '</ul>';
    return;
  }
  const t = data.transaction;
  let html = '<span class="badge ok">ASSEMBLED</span>';
  const block = (title, name, xml) =>
    '<div style="margin-top:12px"><strong>' + esc(title) + '</strong>' +
    '<div class="hint">' + esc(name) + ' (immutable)</div>' +
    '<pre style="background:#f4f7fb;border:1px solid var(--line);' +
    'border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
    esc(xml) + '</pre></div>';
  html += block('REP CO', t.co.filename, t.co.xml);
  html += block('REP RT (v' + t.rt.template_version + ')', t.rt.filename, t.rt.xml);
  if (t.pi) html += block('REP PI', t.pi.filename, t.pi.xml);
  html += block('eCTD backbone', t.ca_regional.path, t.ca_regional.xml);
  html += '<div style="margin-top:12px"><strong>Cover letter</strong>' +
    '<div class="hint">' + esc(t.cover_letter.leaf) +
    ' — portal template</div><pre style="background:#f4f7fb;border:1px solid ' +
    'var(--line);border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
    esc(t.cover_letter.text) + '</pre></div>';
  // REQ-065: render-for-review button
  html += '<div style="margin-top:16px"><button type="button" class="primary" ' +
    'id="repReviewBtn" onclick="renderRepForReview()">' +
    'Render for review (HC stylesheet)</button></div>';
  html += '<div id="repReviewPanel" style="margin-top:12px"></div>';
  el.innerHTML = html;
  window._lastTransaction = data.transaction;
}

// REQ-065: render every REP artifact through the version-matched HC stylesheet
async function renderRepForReview() {
  const panel = document.getElementById('repReviewPanel');
  if (!window._lastTransaction) { panel.innerHTML = '<p class="error">No assembled transaction.</p>'; return; }
  panel.innerHTML = '<p class="hint">Rendering via HC stylesheet…</p>';
  try {
    const res = await fetch('/api/rep/stylesheet/render', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({transaction: window._lastTransaction})
    });
    const data = await res.json();
    if (!res.ok) { panel.innerHTML = '<p class="error">' + esc(data.error || 'Render failed') + '</p>'; return; }
    let html = '<div class="card" style="padding:12px;margin-top:0">' +
      '<span class="badge ok">STYLESHEET PREVIEW</span> ' +
      '<span class="hint">HC ' + esc(data.stylesheet.package) + ' v' +
      esc(data.stylesheet.versions.join(', ')) + ' — pre-file human review</span>';
    for (const art of data.artifacts) {
      html += '<div style="margin-top:14px"><strong>' + esc(art.title) + '</strong>';
      if (art.filename) html += ' <span class="hint">(' + esc(art.filename) + ')</span>';
      html += '<div style="margin-top:6px">' + art.html + '</div></div>';
    }
    html += '</div>';
    panel.innerHTML = html;
  } catch(e) { panel.innerHTML = '<p class="error">Render error: ' + esc(String(e)) + '</p>'; }
}

// -- eCTD dossier UI (REQ-009/014/015/017/018/019) --------------------
let CURRENT_DOSSIER = null;
let PLACEMENT = null;

async function loadPlacement() {
  if (PLACEMENT) return PLACEMENT;
  const res = await fetch('/api/ectd/placement');
  PLACEMENT = await res.json();
  document.getElementById('placementVer').textContent = PLACEMENT.version;
  let html = '<table><thead><tr><th>Heading</th><th>Title</th>' +
    '<th>Leaf ID</th><th>Folder</th><th>.docx</th><th>Authored</th>' +
    '</tr></thead><tbody>';
  const sel = document.getElementById('leafHeading');
  sel.innerHTML = '';
  for (const e of PLACEMENT.entries) {
    html += '<tr><td>' + esc(e.heading) + '</td><td>' + esc(e.title) +
      '</td><td>' + esc(e.leaf_id) + '</td><td>' + esc(e.folder) + '</td><td>' +
      (e.docx_required ? '✓' : '') + '</td><td>' +
      (e.sponsor_authored ? 'sponsor' : 'HC') + '</td></tr>';
    const o = document.createElement('option');
    o.value = e.heading; o.textContent = e.heading + ' — ' + e.title;
    sel.appendChild(o);
  }
  document.getElementById('placementTable').innerHTML = html + '</tbody></table>';
  return PLACEMENT;
}

async function loadDossierList() {
  const res = await fetch('/api/ectd/dossiers');
  const data = await res.json();
  const sel = document.getElementById('dossierSelect');
  sel.innerHTML = '<option value="">— select —</option>';
  for (const d of data.dossiers) {
    const o = document.createElement('option');
    o.value = d.dossier_id;
    o.textContent = d.dossier_id + ' (' + d.sequences.length + ' seq, ' +
      d.live_leaves + ' live)';
    if (d.dossier_id === CURRENT_DOSSIER) o.selected = true;
    sel.appendChild(o);
  }
}

async function createDossier() {
  const id = document.getElementById('newDossierId').value.trim();
  const res = await fetch('/api/ectd/dossiers', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({dossier_id: id})
  });
  const data = await res.json();
  const msg = document.getElementById('dossierMsg');
  if (!data.valid) {
    msg.innerHTML = '<span class="badge bad">FAIL</span> ' +
      esc((data.errors && data.errors[0] && data.errors[0].message) ||
          data.error || 'could not create dossier');
    return;
  }
  msg.innerHTML = '<span class="badge ok">CREATED</span> ' + esc(id);
  await loadDossierList();
  loadDossier(id);
}

async function loadDossier(id) {
  if (!id) { document.getElementById('dossierPanel').style.display = 'none'; return; }
  CURRENT_DOSSIER = id;
  await loadPlacement();
  document.getElementById('dossierPanel').style.display = 'block';
  await refreshCurrentView();
}

async function refreshCurrentView() {
  const res = await fetch('/api/ectd/dossiers/' + encodeURIComponent(CURRENT_DOSSIER) +
    '/current-view');
  const view = await res.json();
  const el = document.getElementById('currentView');
  if (!view.live || !view.live.length) {
    el.innerHTML = '<p class="empty">No live leaves yet.</p>'; return;
  }
  let html = '<table><thead><tr><th>Leaf ID</th><th>Heading</th>' +
    '<th>Title</th><th>Seq</th><th>Op</th><th>Reused</th></tr></thead><tbody>';
  for (const l of view.live) {
    html += '<tr><td>' + esc(l.leaf_id) + '</td><td>' + esc(l.heading) +
      '</td><td>' + esc(l.title) + '</td><td>' + esc(l.sequence) + '</td><td>' +
      esc(l.operation) + '</td><td>' +
      (l.reused_from ? esc(l.reused_from.leaf_id || 'yes') : '') + '</td></tr>';
  }
  el.innerHTML = html + '</tbody></table>';
}

async function addLeaf() {
  const msgGuard = document.getElementById('leafMsg');
  if (!CURRENT_DOSSIER) {
    msgGuard.innerHTML = '<span class="badge bad">BLOCKED</span> ' +
      'create or open a dossier first';
    return;
  }
  const f = document.getElementById('leafForm');
  const d = {};
  for (const el of f.elements) if (el.name) d[el.name] = el.value;
  const res = await fetch('/api/ectd/dossiers/' +
    encodeURIComponent(CURRENT_DOSSIER) + '/leaves', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(d)
  });
  const data = await res.json();
  const msg = document.getElementById('leafMsg');
  if (!data.valid) {
    msg.innerHTML = '<span class="badge bad">BLOCKED</span> ' +
      esc(data.error || (data.errors && data.errors[0].message) || 'rejected');
    return;
  }
  msg.innerHTML = '<span class="badge ok">ADDED</span> leaf ' +
    esc(data.leaf.leaf_id) + ' (checksum ' + esc(data.leaf.checksum || '—') + ')';
  await refreshCurrentView();
  await loadDossierList();
}

async function exportSequence() {
  const exEl = document.getElementById('exportResult');
  if (!CURRENT_DOSSIER) {
    exEl.innerHTML = '<span class="badge bad">BLOCKED</span> ' +
      'create or open a dossier first';
    return;
  }
  const seq = document.getElementById('exportSeq').value.trim();
  const res = await fetch('/api/ectd/dossiers/' +
    encodeURIComponent(CURRENT_DOSSIER) + '/export/' + encodeURIComponent(seq));
  const data = await res.json();
  const el = document.getElementById('exportResult');
  if (!data.valid) {
    el.innerHTML = '<span class="badge bad">BLOCKED</span> ' +
      esc(data.error || 'export failed'); return;
  }
  let html = '<span class="badge ok">EXPORTED</span> sequence ' + esc(data.sequence) +
    ' — index-md5 <code>' + esc(data.index_md5) + '</code>';
  html += '<div class="hint" style="margin-top:8px">Files: ' +
    esc(data.files.join(', ')) + '</div>';
  const pre = (title, xml) =>
    '<div style="margin-top:12px"><strong>' + esc(title) + '</strong>' +
    '<pre style="background:#f4f7fb;border:1px solid var(--line);' +
    'border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
    esc(xml) + '</pre></div>';
  html += pre('index.xml', data.previews['index.xml']);
  html += pre('m1/ca/ca-regional.xml', data.previews['m1/ca/ca-regional.xml']);
  el.innerHTML = html;
}

// -- Pre-submission validation UI (REQ-022/023/024/045/059/070) --------
const SAMPLE_CTX = {
  dossier_id: "e123456",
  sequence: "0001",
  drug_product: "Metformin HCl 500 mg tablets",
  strength: "500 mg",
  dosage_form: "tablet",
  files: [
    {path: "m1/ca/cover-letter.pdf", kind: "pdf", readable: true,
     encrypted: false, bookmarks: true},
    {path: "m1/ca/locked.pdf", kind: "pdf", readable: false},
    {path: "m3/quality.pdf", kind: "pdf", readable: true, encrypted: true}
  ],
  leaves: [
    {leaf_id: "m1-cover", href: "m1/ca/cover-letter.pdf",
     checksum: "deadbeef", content: "hello", operation: "new"}
  ],
  index_xml: "<ectd:ectd xmlns:ectd=\\"x\\"><leaf/></ectd:ectd>",
  ca_regional_xml: "<ca-regional><dossier-id>e123456</dossier-id></ca-regional>",
  ca_regional: {dossier_id: "e123456", din: "02123456", company_id: "K18276"},
  cover_letter: {din: "02123456", company_id: "K18276", dossier_id: "e123456"},
  rep: {
    co: {company_id: "K18276", dossier_id: "e123456"},
    rt: {company_id: "K18276", dossier_id: "e123456", din: "02123456"},
    pi: {din: "02999999", dossier_id: "e123456",
         product_name: "Metformin HCl 500 mg tablets",
         strength: "500 mg", dosage_form: "tablet"}
  },
  module5_studies: [
    {id: "be-study-01", folder: "m5/be", requires_stf: true, stf_present: false}
  ]
};

function valCtxObj() {
  try { return {ok: true, ctx: JSON.parse(document.getElementById('valCtx').value)}; }
  catch (e) { return {ok: false, error: 'Invalid JSON: ' + e.message}; }
}

function valVersion() { return document.getElementById('rulesetSelect').value; }

async function loadRulesets() {
  const res = await fetch('/api/validation/rulesets');
  const data = await res.json();
  const sel = document.getElementById('rulesetSelect');
  sel.innerHTML = '';
  for (const r of data.rulesets) {
    const o = document.createElement('option');
    o.value = r.version;
    o.textContent = 'v' + r.version + ' (eff. ' + r.effective + ')' +
      (r.active ? ' — active' : '');
    if (r.active) o.selected = true;
    sel.appendChild(o);
  }
  document.getElementById('rulesetHint').textContent =
    'active default: v' + data.active;
}

async function loadRuleset() {
  const res = await fetch('/api/validation/ruleset?version=' +
    encodeURIComponent(valVersion()));
  const data = await res.json();
  const el = document.getElementById('rulesetTable');
  if (data.error) { el.innerHTML = '<p class="empty">' + esc(data.error) + '</p>'; return; }
  let html = '<table><thead><tr><th>Rule</th><th>Category</th>' +
    '<th>Severity</th><th>Description</th></tr></thead><tbody>';
  for (const r of data.rules) {
    html += '<tr><td>' + esc(r.rule_id) + '</td><td>' + esc(r.category) +
      '</td><td>' + esc(r.severity) + '</td><td>' + esc(r.description) +
      '</td></tr>';
  }
  el.innerHTML = html + '</tbody></table><div class="hint">v' +
    esc(data.version) + ' — ' + data.rules.length + ' rules in effect</div>';
}

function valShow(html) { document.getElementById('valResult').innerHTML = html; }

function findingList(items) {
  let html = '<ul class="errs">';
  for (const f of items) {
    const tag = f.severity === 'Warning'
      ? '<span style="color:#b26a00;font-weight:700">[WARN ' + esc(f.rule_id) + ']</span>'
      : '<span style="color:var(--bad);font-weight:700">[ERR ' + esc(f.rule_id) + ']</span>';
    html += '<li style="color:inherit">' + tag + ' ' + esc(f.message) +
      ' <span class="hint">(' + esc(f.file || f.node || '') + ')</span></li>';
  }
  return html + '</ul>';
}

async function valPost(path, extra) {
  const parsed = valCtxObj();
  if (!parsed.ok) { valShow('<span class="badge bad">FAIL</span> ' + esc(parsed.error)); return null; }
  const body = Object.assign({context: parsed.ctx, version: valVersion()}, extra || {});
  const res = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return {status: res.status, data: await res.json()};
}

async function valRun() {
  const r = await valPost('/api/validation/run'); if (!r) return;
  const d = r.data;
  const badge = d.blocking
    ? '<span class="badge bad">BLOCKED</span>' : '<span class="badge ok">PASS</span>';
  valShow(badge + ' ruleset v' + esc(d.ruleset_version) + ' — ' +
    d.error_count + ' error(s), ' + d.warning_count + ' warning(s)' +
    findingList(d.findings));
}

async function valInline() {
  const r = await valPost('/api/validation/inline'); if (!r) return;
  const d = r.data;
  let html = '<span class="badge ' + (d.blocking ? 'bad' : 'ok') + '">' +
    (d.blocking ? 'DEFECTS' : 'CLEAN') + '</span> inline gutter (v' +
    esc(d.ruleset_version) + ')';
  for (const file of Object.keys(d.gutter)) {
    html += '<div style="margin-top:10px"><strong>' + esc(file) + '</strong><ul class="errs">';
    for (const g of d.gutter[file]) {
      html += '<li style="color:inherit"><span style="color:' + esc(g.colour) +
        ';font-weight:700">●</span> [' + esc(g.rule_id) + '] ' + esc(g.message);
      if (g.remediable) {
        // User data (fix_id, file path) rides in double-quoted data-* attrs —
        // safely escaped by esc() — and the inline handler is a STATIC string
        // that reads them back via this.dataset, so a quote in a filename can
        // never break out into the JS-string context (DOM-XSS).
        html += ' <button type="button" class="ghost" style="padding:2px 8px;font-size:12px" ' +
          'data-fix="' + esc(g.fix_id) + '" data-file="' + esc(file) + '" ' +
          'onclick="valFix(this.dataset.fix, this.dataset.file)">one-click fix</button>';
      }
      html += '</li>';
    }
    html += '</ul></div>';
  }
  valShow(html);
}

async function valFix(fixId, file) {
  const r = await valPost('/api/validation/fix', {fix_id: fixId, file: file});
  if (!r) return;
  if (r.status !== 200) { valShow('<span class="badge bad">FAIL</span> ' +
    esc(r.data.error || 'fix failed')); return; }
  // Persist the fixed context back into the editor, then re-render the gutter.
  document.getElementById('valCtx').value = JSON.stringify(r.data.context, null, 2);
  valInline();
}

async function valReport() {
  const r = await valPost('/api/validation/report'); if (!r) return;
  if (r.data.error) { valShow('<span class="badge bad">FAIL</span> ' + esc(r.data.error)); return; }
  valShow('<span class="badge ' + (r.data.blocking ? 'bad' : 'ok') + '">REPORT</span>' +
    '<pre style="background:#f4f7fb;border:1px solid var(--line);border-radius:6px;' +
    'padding:12px;overflow:auto;font-size:12px">' + esc(r.data.text) + '</pre>');
}

async function valDownload() {
  const parsed = valCtxObj();
  if (!parsed.ok) { valShow('<span class="badge bad">FAIL</span> ' + esc(parsed.error)); return; }
  const res = await fetch('/api/validation/report.txt', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({context: parsed.ctx, version: valVersion()})
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'hc-validation-report.txt';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  valShow('<span class="badge ok">DOWNLOADED</span> hc-validation-report.txt');
}

async function valConsistency() {
  const r = await valPost('/api/validation/consistency'); if (!r) return;
  const d = r.data;
  valShow('<span class="badge ' + (d.consistent ? 'ok' : 'bad') + '">' +
    (d.consistent ? 'CONSISTENT' : 'INCONSISTENT') + '</span> ' +
    d.findings.length + ' cross-document finding(s)' + findingList(d.findings));
}

async function valPackage() {
  const r = await valPost('/api/validation/package'); if (!r) return;
  const d = r.data;
  valShow('<span class="badge ' + (d.can_package ? 'ok' : 'bad') + '">' +
    (d.can_package ? 'CAN PACKAGE' : 'BLOCKED') + '</span> v' + esc(d.ruleset_version) +
    ' — ' + d.errors.length + ' error(s)' + findingList(d.errors.concat(d.consistency_findings)));
}

async function valAttempt(esgDown) {
  const services = esgDown ? {fda_esg: 'down'} : {};
  const r = await valPost('/api/validation/package-attempt', {services: services});
  if (!r) return;
  const d = r.data;
  if (d.ok) {
    valShow('<span class="badge ok">PACKAGED</span> ' + esc(d.message) +
      ' (attempt ' + d.attempts + ')');
    return;
  }
  valShow('<span class="badge bad">' + esc(String(d.blocked_by).toUpperCase()) +
    ' FAILURE</span> ' + esc(d.error) +
    '<div class="hint" style="margin-top:6px">State retained: ' +
    (d.state_retained ? 'yes' : 'no') + ' — ' + esc(d.resume) + '</div>');
}

// -- CRP / CS-BE / QOS / STF UI (REQ-007/008/061/063/064) -------------
function readJson(id, target) {
  try { return JSON.parse(document.getElementById(id).value); }
  catch (e) {
    document.getElementById(target).innerHTML =
      '<span class="badge bad">BAD JSON</span> ' + esc(e.message);
    return null;
  }
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return {status: res.status, data: await res.json()};
}

function showErrors(target, errors) {
  let html = '<span class="badge bad">' + (errors.length) +
    ' issue(s)</span><ul class="errs">';
  for (const e of errors) html += '<li>' + esc(e.message) + '</li>';
  return target.innerHTML = html + '</ul>';
}

function preBlock(label, text) {
  return '<div style="margin-top:10px"><strong>' + esc(label) + '</strong>' +
    '<pre style="background:#f4f7fb;border:1px solid var(--line);border-radius:6px;' +
    'padding:10px;overflow:auto;font-size:12px">' + esc(text) + '</pre></div>';
}

async function crpValidate() {
  const body = readJson('crpCtx', 'crpResult'); if (!body) return;
  const {data} = await postJson('/api/crp/validate', body);
  const el = document.getElementById('crpResult');
  if (data.valid) {
    el.innerHTML = '<span class="badge ok">EQUIVALENT</span> CRP captured — ' +
      esc(data.crp.brand_name) + ' (DIN ' + esc(data.crp.din) +
      '), pharmaceutically equivalent.';
  } else showErrors(el, data.errors);
}

async function beEvaluate() {
  const body = readJson('csbeCtx', 'csbeResult'); if (!body) return;
  const {data} = await postJson('/api/be/evaluate', body);
  const el = document.getElementById('csbeResult');
  const rs = data.ruleset || {};
  const head = '<div class="hint">Ruleset <b>' + esc(rs.version) +
    '</b> — Cmax rule <b>' + esc(data.cmax_rule) + '</b> (' +
    esc(rs.lower) + '–' + esc(rs.upper) + '%)</div>';
  if (data.bioequivalent)
    el.innerHTML = '<span class="badge ok">BIOEQUIVALENT</span>' + head;
  else { showErrors(el, data.findings); el.innerHTML += head; }
}

async function csBeBuild() {
  const body = readJson('csbeCtx', 'csbeResult'); if (!body) return;
  const {data} = await postJson('/api/cs-be/build', body);
  const el = document.getElementById('csbeResult');
  const c = data.cs_be || {};
  let html = data.valid
    ? '<span class="badge ok">CS-BE BUILT</span>'
    : '<span class="badge bad">' + data.errors.length + ' BE issue(s)</span>';
  html += '<div class="hint">Electronic copy in Module ' +
    esc((c.electronic_copy || {}).module) + '; pivotal reports in ' +
    '5.3.1.2; generates 2.7.1: <b>' + (c.generates_2_7_1 ? 'yes' : 'no') +
    '</b>; DRAFT (' + esc(c.draft_date) + ').</div>';
  if (!data.valid) {
    html += '<ul class="errs">';
    for (const e of data.errors) html += '<li>' + esc(e.message) + '</li>';
    html += '</ul>';
  }
  el.innerHTML = html + preBlock('CS-BE leaf XML (Module 1.6)', data.leaf_xml);
}

async function qosBuild() {
  const body = readJson('qosCtx', 'qosResult'); if (!body) return;
  const {data} = await postJson('/api/qos/build', body);
  const el = document.getElementById('qosResult');
  if (data.valid) {
    el.innerHTML = '<span class="badge ok">QOS-CE COMPLETE</span>' +
      preBlock('QOS-CE document (Module 2.3)', data.qos_ce.document);
  } else { showErrors(el, data.errors); }
}

async function qosGate() {
  const body = readJson('qosCtx', 'qosResult'); if (!body) return;
  const {data} = await postJson('/api/qos/gate', body);
  const el = document.getElementById('qosResult');
  if (data.can_pass)
    el.innerHTML = '<span class="badge ok">SCREENING OK</span> QOS-CE present.';
  else
    el.innerHTML = '<span class="badge bad">SCREENING-DEFICIENCY RISK</span> ' +
      esc(data.risk_message);
}

async function stfGenerate() {
  const body = readJson('stfCtx', 'stfResult'); if (!body) return;
  const {data} = await postJson('/api/stf/generate', body);
  const el = document.getElementById('stfResult');
  if (!data.stfs.length) {
    el.innerHTML = '<span class="badge ok">NONE</span> No studies require an STF.';
    return;
  }
  let html = '<span class="badge ok">' + data.stfs.length +
    ' STF leaf/leaves</span>';
  for (const s of data.stfs) html += preBlock(s.leaf_id + ' — ' + s.href, s.xml);
  el.innerHTML = html;
}

async function stfValidate() {
  const body = readJson('stfCtx', 'stfResult'); if (!body) return;
  const {data} = await postJson('/api/stf/validate', body);
  const el = document.getElementById('stfResult');
  if (data.valid)
    el.innerHTML = '<span class="badge ok">STF CATEGORY OK</span>';
  else showErrors(el, data.findings);
}

// -- Transmission Console (REQ-003/025/026/027/046/058) ----------------
function txnField(id) { return document.getElementById(id).value.trim(); }
function txnDossier() { return txnField('txnDossier'); }
function txnBody(extra) {
  return Object.assign({dossier_id: txnDossier(),
                        sequence: txnField('txnSequence')}, extra || {});
}
function txnSay(html) { document.getElementById('txnResult').innerHTML = html; }
function txnFail(data) {
  txnSay('<span class="badge bad">BLOCKED</span> ' +
         esc(data.error || (data.errors || []).map(e => e.message).join('; ')));
}

async function txnConfigure() {
  const {status, data} = await postJson('/api/transmission/configure', {
    dossier_id: txnDossier(), account_type: txnField('txnAccount'),
    x509_certificate: txnField('txnCert')});
  if (status >= 400) return txnFail(data);
  txnSay('<span class="badge ok">CONFIGURED</span> ' +
    esc(data.config.esg_environment) + ' · Center ' +
    esc(data.config.recipient_center) + ' · Production ' +
    (data.config.production_enabled ? 'enabled' : 'locked until test round-trip'));
  txnRender(data.status);
}

async function txnTestRoundTrip() {
  const {status, data} = await postJson('/api/transmission/test-round-trip',
    {dossier_id: txnDossier(), acks: {mdn_received: true,
      fda_ack_received: true, hc_ack_received: true}});
  if (status >= 400) return txnFail(data);
  txnSay('<span class="badge ' + (data.production_enabled ? 'ok' : 'bad') +
    '">' + (data.production_enabled ? 'PRODUCTION UNLOCKED' : 'STILL LOCKED') +
    '</span> ' + esc(data.reason || 'Test-gateway round-trip recorded.'));
  txnRender(data.status);
}

async function txnRoute() {
  const {data} = await postJson('/api/transmission/route',
    {size_gb: parseFloat(txnField('txnSize'))});
  const r = data.routing;
  let html = '<span class="badge ' + (r.over_limit ? 'bad' : 'ok') + '">' +
    (r.over_limit ? 'PHYSICAL MEDIA (>10 GB)' : 'GATEWAY') + '</span> ' +
    r.size_gb + ' GB';
  if (r.congestion.offer) html += ' · ' + esc(r.congestion.reason);
  if (r.shipping_instructions) html += '<div class="hint">' +
    esc(r.shipping_instructions) + '</div>';
  txnSay(html);
}

async function txnSubmit() {
  const {status, data} = await postJson('/api/transmission/submit',
    txnBody({size_gb: parseFloat(txnField('txnSize')), production: true}));
  if (status >= 400) return txnFail(data);
  const t = data.transaction;
  txnSay('<span class="badge ok">' + esc(t.state) + '</span> seq ' +
    esc(t.sequence) + ' routed to ' + esc(t.route) +
    (t.state === 'QUEUED' ? ' (held behind ' + esc(t.queued_behind) + ')' : ''));
  txnRender(data.status);
}

async function txnAck(type) {
  const body = txnBody({type: type});
  if (type !== 'mdn') body.core_id = 'CORE-' + txnDossier() + '-' +
    txnField('txnSequence');
  const {status, data} = await postJson('/api/transmission/ack', body);
  if (status >= 400) return txnFail(data);
  txnSay('<span class="badge ok">ACK</span> recorded ' + esc(type.toUpperCase()));
  txnRender(data.status);
}

async function txnMonitor() {
  const {status, data} = await postJson('/api/transmission/monitor',
    {dossier_id: txnDossier()});
  if (status >= 400) return txnFail(data);
  txnSay('<span class="badge ' + (data.alerts.length ? 'bad' : 'ok') + '">' +
    data.alerts.length + ' alert(s)</span>');
  txnRender(data.status);
}

async function txnResend() {
  const rationale = prompt('Resend rationale (required for unresolved deliveries):',
    'no acknowledgement received; confirmed not delivered');
  const {status, data} = await postJson('/api/transmission/resend',
    txnBody({confirm: !!rationale, rationale: rationale || ''}));
  if (status >= 400) return txnFail(data);
  txnSay('<span class="badge ok">RESENT</span> seq ' +
    esc(data.transaction.sequence));
  txnRender(data.status);
}

async function txnMedia(action) {
  const extra = {};
  if (action === 'ship') { extra.carrier = 'Purolator'; extra.tracking = 'PB-12345'; }
  const {status, data} = await postJson('/api/transmission/media/' + action,
    txnBody(extra));
  if (status >= 400) return txnFail(data);
  txnSay('<span class="badge ok">MEDIA ' + action.toUpperCase() + '</span>');
  txnRender(data.status);
}

async function txnLoad() {
  const id = txnDossier();
  const {status, data} = await (async () => {
    try {
      const res = await fetch('/api/transmission/dossiers/' + encodeURIComponent(id));
      return {status: res.status, data: await res.json()};
    } catch (e) { return {status: 500, data: {error: e.message}}; }
  })();
  if (status >= 400) return txnFail(data);
  txnRender(data);
}

function txnRender(status) {
  if (!status) return;
  let html = '<div class="hint">In-flight: ' +
    (status.in_flight.join(', ') || '—') + ' · Queued: ' +
    (status.queued.join(', ') || '—') + '</div>';
  html += '<table><tr><th>Seq</th><th>State</th><th>Route</th>' +
    '<th>Size</th><th>Core ID</th><th>HC ACK</th><th>Alerts</th></tr>';
  for (const t of status.transactions) {
    html += '<tr><td>' + esc(t.sequence) + '</td><td>' + esc(t.state) +
      '</td><td>' + esc(t.route) + '</td><td>' + t.size_gb + '</td><td>' +
      esc(t.core_id || '—') + '</td><td>' + (t.hc_ack_received ? '✓' : '—') +
      '</td><td>' + (t.alerts.length || '') + '</td></tr>';
  }
  document.getElementById('txnStatus').innerHTML = html + '</table>';
}

document.getElementById('crpCtx').value = JSON.stringify({
  brand_name: "Glucophage", din: "02229516", strength: "500 mg",
  dosage_form: "tablet", innovator: "Innovator Pharma Inc.",
  medicinal_ingredients: ["metformin hydrochloride"],
  foreign: false,
  generic: {dosage_form: "film-coated tablet",
            medicinal_ingredients: ["metformin hydrochloride"]}
}, null, 2);
document.getElementById('csbeCtx').value = JSON.stringify({
  submission_date: "2026-01-15", dosage_form_class: "ir_solid_oral",
  auc: {ci_lower: 92.0, ci_upper: 110.0},
  cmax: {ci_lower: 88.5, ci_upper: 116.0},
  pivotal_reports: [{id: "be-2025-01", title: "Pivotal fasting BE study"}]
}, null, 2);
document.getElementById('qosCtx').value = JSON.stringify({
  drug_product: "Metformin HCl 500 mg tablets",
  sections: {introduction: "...", drug_substance: "...", drug_product: "...",
             appendices: "...", regional: "..."}
}, null, 2);
document.getElementById('stfCtx').value = JSON.stringify({
  module5_studies: [
    {id: "be-fasting-01", type: "bioequivalence",
     folder: "m5/53-clin-stud-rep/531-bio/5312-comp-ba-be",
     files: ["study-report-body", "synopsis"]},
    {id: "be-fed-02", type: "bioequivalence", stf_present: false}
  ]
}, null, 2);

// -- Fees, mitigation & Right-to-Sell (REQ-035/036/037) ---------------------
async function feePost(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return [res.status, await res.json()];
}

function feeMoney(n) {
  return '$' + Number(n).toLocaleString('en-CA', {minimumFractionDigits: 2,
    maximumFractionDigits: 2});
}

function feeRow(label, value) {
  return '<tr><td style="padding:2px 12px 2px 0;color:var(--muted)">' +
    esc(label) + '</td><td><strong>' + esc(value) + '</strong></td></tr>';
}

async function feeAnds() {
  const el = document.getElementById('feeResult');
  const [status, d] = await feePost('/api/fees/ands',
    {submission_date: document.getElementById('feeDate').value});
  if (!d.valid) {
    el.innerHTML = '<span class="badge bad">FAIL</span> ' + esc(d.error || '');
    return;
  }
  let html = '<span class="badge ok">RESOLVED</span><table style="margin-top:10px">';
  html += feeRow('Grouping', d.label);
  html += feeRow('Amount', feeMoney(d.amount) + ' ' + d.currency);
  html += feeRow('Fiscal year', d.amount_fiscal_year + ' (eff. ' + d.effective_date + ')');
  html += feeRow('Escalation basis', d.basis);
  html += feeRow('Anchor seed excluded', feeMoney(d.anchor_seed_excluded));
  html += '</table><p class="hint">' + esc(d.rationale) + '</p>';
  el.innerHTML = html;
}

async function feeMitigation() {
  const el = document.getElementById('feeResult');
  const [status, d] = await feePost('/api/fees/mitigation', {
    fee: document.getElementById('feeGross').value,
    small_business: document.getElementById('feeSmall').checked,
    first_submission: document.getElementById('feeFirst').checked,
    attestation_uploaded: document.getElementById('feeAttest').checked,
    defer_until_noc: document.getElementById('feeDefer').checked
  });
  if (!d.valid) {
    el.innerHTML = '<span class="badge bad">FAIL</span> ' + esc(d.error || '');
    return;
  }
  const badge = d.requires_attestation
    ? '<span class="badge bad">ATTESTATION REQUIRED</span>'
    : '<span class="badge ok">EVALUATED</span>';
  let html = badge + '<table style="margin-top:10px">';
  html += feeRow('Gross fee', feeMoney(d.fee));
  html += feeRow('Remission', (d.remission_rate * 100) + '%');
  html += feeRow('Net fee', feeMoney(d.net_fee));
  html += feeRow('Invoice status', d.invoice_status);
  html += '</table><ul class="errs">';
  for (const n of d.notes) html += '<li>' + esc(n) + '</li>';
  el.innerHTML = html + '</ul>';
}

async function feeRightToSell() {
  const el = document.getElementById('feeResult');
  const [status, d] = await feePost('/api/fees/right-to-sell', {
    drug_type: document.getElementById('feeDrugType').value,
    as_of: document.getElementById('feeDate').value,
    paid: document.getElementById('feePaid').checked
  });
  if (!d.valid) {
    el.innerHTML = '<span class="badge bad">FAIL</span> ' + esc(d.error || '');
    return;
  }
  const badge = d.overdue ? '<span class="badge bad">OVERDUE</span>'
    : d.outstanding_balance ? '<span class="badge bad">OUTSTANDING</span>'
    : '<span class="badge ok">PAID</span>';
  let html = badge + '<table style="margin-top:10px">';
  html += feeRow('Drug type', d.label);
  html += feeRow('Annual fee', feeMoney(d.amount) + ' ' + d.currency);
  html += feeRow('Fiscal year', d.amount_fiscal_year);
  html += feeRow('Due date', d.due_date);
  html += feeRow('Days to due', String(d.days_to_due));
  if (d.reminder_due) html += feeRow('Reminder', 'due within 60 days');
  el.innerHTML = html + '</table>';
}

document.getElementById('valCtx').value = JSON.stringify(SAMPLE_CTX, null, 2);

// -- DSTS lifecycle (REQ-030/031/062) ----------------------------------------
function lcField(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

function lcShow(data) {
  const el = document.getElementById('lcResult');
  if (!el) return;
  if (!data.valid && data.error) {
    el.innerHTML = '<span class="badge bad">Error</span> ' + esc(data.error);
    return;
  }
  const s = data.status || data.assessment || data;
  el.innerHTML = '<pre style="background:#f4f7fb;border:1px solid var(--line);' +
    'border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
    esc(JSON.stringify(s, null, 2)) + '</pre>';
}

function lcNow() {
  return new Date().toISOString().slice(0, 10);
}

async function lcStart() {
  const body = {
    dossier_id: lcField('lcDossier'),
    submission_type: lcField('lcType'),
    core_id: lcField('lcCore'),
    fee_paid: parseFloat(lcField('lcFee')) || null,
    now: lcNow(),
  };
  const {status, data} = await postJson('/api/lifecycle/start', body);
  lcShow(data);
}

async function lcTransition(action) {
  const body = {dossier_id: lcField('lcDossier'), action, now: lcNow()};
  const {status, data} = await postJson('/api/lifecycle/transition', body);
  lcShow(data);
}

async function lcScreening(outcome) {
  const body = {dossier_id: lcField('lcDossier'), action: 'screening_outcome', outcome, now: lcNow()};
  const {status, data} = await postJson('/api/lifecycle/transition', body);
  lcShow(data);
}

async function lcClarifax() {
  const override = lcField('lcOverride');
  const body = {
    dossier_id: lcField('lcDossier'),
    action: 'clarifax',
    tier: lcField('lcTier'),
    response_days: override ? parseInt(override, 10) : undefined,
    now: lcNow(),
  };
  const {status, data} = await postJson('/api/lifecycle/transition', body);
  lcShow(data);
}

async function lcDecision(decision) {
  const body = {dossier_id: lcField('lcDossier'), action: 'decision', decision, now: lcNow()};
  const {status, data} = await postJson('/api/lifecycle/transition', body);
  lcShow(data);
}

async function lcServiceStandard() {
  const body = {dossier_id: lcField('lcDossier'), now: lcNow()};
  const {status, data} = await postJson('/api/lifecycle/service-standard', body);
  lcShow(data);
}

async function lcLoad() {
  const id = lcField('lcDossier');
  const el = document.getElementById('lcResult');
  try {
    const res = await fetch('/api/lifecycle/dossiers/' + encodeURIComponent(id));
    const data = await res.json();
    if (!el) return;
    if (res.status >= 400) {
      el.innerHTML = '<span class="badge bad">Error</span> ' + esc(data.error || res.status);
      return;
    }
    el.innerHTML = '<pre style="background:#f4f7fb;border:1px solid var(--line);' +
      'border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
      esc(JSON.stringify(data, null, 2)) + '</pre>';
  } catch (e) {
    if (el) el.innerHTML = '<span class="badge bad">Error</span> ' + esc(e.message);
  }
}

// -- HC deadline calendar (REQ-052) ------------------------------------------
async function calCompute() {
  const el = document.getElementById('calResult');
  const basis = document.getElementById('calBasis').value;
  const body = {
    start: document.getElementById('calStart').value.trim(),
    days: parseInt(document.getElementById('calDays').value, 10),
    notice_type: document.getElementById('calNotice').value,
    basis: basis || undefined,
  };
  const {status, data} = await postJson('/api/calendar/deadline', body);
  if (!el) return;
  if (!data.valid) {
    el.innerHTML = '<span class="badge bad">Error</span> ' + esc(data.error);
    return;
  }
  el.innerHTML = '<pre style="background:#f4f7fb;border:1px solid var(--line);' +
    'border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
    esc(JSON.stringify(data.deadline, null, 2)) + '</pre>';
}

async function calHolidays() {
  const el = document.getElementById('calResult');
  const year = new Date().getFullYear();
  try {
    const res = await fetch('/api/calendar/holidays?start=' + year + '&end=' + (year + 1));
    const data = await res.json();
    if (!el) return;
    if (res.status >= 400) {
      el.innerHTML = '<span class="badge bad">Error</span> ' + esc(data.error || res.status);
      return;
    }
    let html = '<strong>Canadian federal statutory holidays (' + data.start_year +
      '–' + data.end_year + ')</strong><table><tr><th>Date</th><th>Name</th></tr>';
    for (const h of data.holidays)
      html += '<tr><td>' + esc(h.date) + '</td><td>' + esc(h.name) + '</td></tr>';
    el.innerHTML = html + '</table>';
  } catch (e) {
    if (el) el.innerHTML = '<span class="badge bad">Error</span> ' + esc(e.message);
  }
}

// -- Rejection / eCTD Validation Report ingest (REQ-029) ---------------------
async function rejIngest() {
  const el = document.getElementById('rejResult');
  const body = {
    dossier_id: (document.getElementById('rejDossier').value || '').trim(),
    report_text: (document.getElementById('rejReport').value || '').trim(),
  };
  const {status, data} = await postJson('/api/rejections/ingest', body);
  if (!el) return;
  if (!data.valid) {
    el.innerHTML = '<span class="badge bad">Error</span> ' + esc(data.error);
    return;
  }
  el.innerHTML = '<pre style="background:#f4f7fb;border:1px solid var(--line);' +
    'border-radius:6px;padding:10px;overflow:auto;font-size:12px">' +
    esc(JSON.stringify(data, null, 2)) + '</pre>';
}

async function boot() {
  // Client requirement (2026-06-26): present the UI only after BOTH the web
  // server and the API server are confirmed up. The web server already answered
  // (this page is running), so we poll /api/health to gate on the API tier; once
  // both report up we reveal the portal and fire its loaders.
  const msg = document.getElementById('boot-msg');
  for (let attempt = 1; attempt <= 50; attempt++) {
    try {
      const r = await fetch('/api/health', { cache: 'no-store' });
      if (r.ok) {
        const h = await r.json();
        if (h.web && h.api) {
          document.body.classList.add('ready');
          loadActivityTypes();
          loadList();
          loadDossierList();
          loadRulesets();
          return;
        }
      }
    } catch (e) { /* server still coming up — keep polling */ }
    if (msg) msg.textContent =
      'Waiting for web + API servers to come up… (attempt ' + attempt + ')';
    await new Promise(res => setTimeout(res, 200));
  }
  if (msg) msg.textContent =
    'Servers did not come up. Check the portal process and reload.';
}
boot();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(host: str = "127.0.0.1", port: int = 8000, db_path: str = DB_PATH):
    store = SubmissionStore(db_path)
    companies = CompanyStore(db_path)
    dossiers = DossierStore(db_path)
    transmissions = TransmissionStore(db_path)
    lifecycles = LifecycleStore(db_path)
    rejections = RejectionStore(db_path)
    # REQ-038/047/054/060: the audit trail and portfolio MUST persist to the same
    # on-disk DB as everything else — otherwise the regulatory audit trail and
    # the org portfolio would silently evaporate on restart.
    audits = AuditStore(db_path)
    portfolios = PortfolioStore(db_path)
    # Multi-tenant control plane: its OWN database, separate from tenant data
    # (REQ-078). A bootstrap owner is ensured so the /owner console is reachable.
    auth_store = auth.AuthStore(CONTROL_PLANE_DB)
    auth_store.ensure_owner(OWNER_EMAIL, OWNER_PASSWORD)
    entitlement_store = entitlements_mod.EntitlementStore(CONTROL_PLANE_DB)
    tenancy_store = tenancy.TenancyStore(
        CONTROL_PLANE_DB, tenants_root=CONTROL_PLANE_TENANTS_ROOT)
    httpd = ThreadingHTTPServer(
        (host, port),
        make_handler(store, companies, dossiers, transmissions,
                     lifecycles, rejections, audits, portfolios,
                     auth_store=auth_store, tenancy_store=tenancy_store,
                     entitlement_store=entitlement_store))
    print(f"ANDS Submission Portal serving on http://{host}:{port}  (db: {db_path})")
    print(f"  control plane: {CONTROL_PLANE_DB}  | owner console: /owner")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
        store.close()
        companies.close()
        dossiers.close()
        transmissions.close()
        lifecycles.close()
        rejections.close()
        audits.close()
        portfolios.close()
        auth_store.close()
        entitlement_store.close()
        tenancy_store.close()


if __name__ == "__main__":
    # Port is taken from the environment so a verifier can run an isolated
    # instance; behaviour is unchanged (default 8000) when the env is unset.
    run(port=int(os.environ.get("ADF_SMOKE_PORT") or os.environ.get("PORT") or 8000))

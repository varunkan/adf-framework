#!/usr/bin/env python3
"""
ANDS Submission Portal — Transmission & ESG slice (REQ-003/025/026/027/046/058).

Pure-stdlib domain logic for the Transmission Console:

* REQ-003 — ESG transmission configuration: target FDA ESG NextGen (deployed
  April 2025), capture the account type (WebTrader or AS2/EDIINT) + X.509
  certificate, designate recipient Center 'HC', forbid any direct Health Canada
  AS2 endpoint, and gate Production transmission behind a successful Test-gateway
  round-trip. The targeted ESG environment is pinned as tracked configuration.
* REQ-025 — pre-flight 10 GB ceiling routing: <=10 GB -> FDA ESG gateway,
  >10 GB -> physical-media (USB/HDD) workflow with shipping instructions.
* REQ-026 — 5-10 GB packages: offer to schedule after 16:30 EST.
* REQ-027 — one-transaction-at-a-time per dossier: queue subsequent sequences
  until the Health Canada acknowledgement for the prior sequence is received;
  unrelated dossiers are not blocked.
* REQ-046 — stalled/failed detection via timeout monitors (no MDN, MDN-without-
  FDA-ack, FDA-ack transport rejection), operator alert, and duplicate-send
  prevention correlating by Message ID / Core ID against FDA ESG NextGen.
* REQ-058 — physical-media package generation (validated tree, backbones,
  checksums, media-manifest/cover documentation), shipment + receipt tracking,
  and HC-acknowledgement reconciliation by Core ID back to the same record.

Everything is deterministic and clock-injectable (a ``now`` ISO timestamp is
passed in the way ``rep.py`` injects its timestamp) so the engine is testable
without wall-clock dependence.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_attr

# ---------------------------------------------------------------------------
# REQ-003 — ESG environment + account constants
# ---------------------------------------------------------------------------

ESG_ENVIRONMENT = "FDA ESG NextGen"
ESG_ENVIRONMENT_DEPLOYED = "2025-04"          # deployed April 2025
RECIPIENT_CENTER = "HC"
ACCOUNT_TYPES = {
    "WebTrader": "FDA ESG WebTrader (browser upload)",
    "AS2": "AS2/EDIINT (machine-to-machine)",
}

# ---------------------------------------------------------------------------
# REQ-025 / REQ-026 — routing thresholds
# ---------------------------------------------------------------------------

GATEWAY_CEILING_GB = 10.0                      # CESG per-transaction ceiling
CONGESTION_LOWER_GB = 5.0                      # 5-10 GB congestion window
CONGESTION_CUTOFF = "16:30 EST"
SHIPPING_INSTRUCTIONS = (
    "Write the validated eCTD folder tree to USB/HDD media, include the "
    "media manifest and signed cover documentation, and ship to the Health "
    "Canada records office per the CESG media-submission guidance."
)

# ---------------------------------------------------------------------------
# Transaction states (the ack/transport state machine)
# ---------------------------------------------------------------------------

STATE_QUEUED = "QUEUED"                         # held behind a prior in-flight txn
STATE_SENT = "SENT"                             # dispatched to the ESG gateway
STATE_MDN_RECEIVED = "MDN_RECEIVED"             # AS2 transport receipt (NextGen ACK1)
STATE_FDA_ACK = "FDA_ACK"                       # FDA Acknowledgement (Message ID + Core ID)
STATE_RECEIVED_BY_HC = "RECEIVED_BY_HC"         # Health Canada Acknowledgement Receipt
STATE_MEDIA_PREP = "MEDIA_PREP"                 # building the physical-media package
STATE_MEDIA_SHIPPED = "MEDIA_SHIPPED"           # media handed to a carrier
STATE_MEDIA_RECEIVED = "MEDIA_RECEIVED"         # media physically received by HC
STATE_TRANSPORT_UNCONFIRMED = "TRANSPORT_UNCONFIRMED"  # REQ-046: no MDN in window
STATE_INVESTIGATE = "INVESTIGATE"               # REQ-046: MDN but no FDA ack in window
STATE_REJECTED = "REJECTED"                     # transport-level rejection

# A dispatched-but-not-yet-acknowledged transaction occupies the single
# per-dossier transmission slot (REQ-027). QUEUED is not yet dispatched;
# RECEIVED_BY_HC and REJECTED are terminal and free the slot.
IN_FLIGHT_STATES = frozenset({
    STATE_SENT, STATE_MDN_RECEIVED, STATE_FDA_ACK,
    STATE_MEDIA_PREP, STATE_MEDIA_SHIPPED, STATE_MEDIA_RECEIVED,
    STATE_TRANSPORT_UNCONFIRMED, STATE_INVESTIGATE,
})
RESOLVED_STATES = frozenset({STATE_RECEIVED_BY_HC, STATE_REJECTED})
# States whose delivery outcome is not yet known — a resend needs explicit
# operator confirmation + rationale (REQ-046 duplicate-send prevention).
UNRESOLVED_STATES = frozenset({
    STATE_SENT, STATE_MDN_RECEIVED, STATE_FDA_ACK,
    STATE_MEDIA_PREP, STATE_MEDIA_SHIPPED, STATE_MEDIA_RECEIVED,
    STATE_TRANSPORT_UNCONFIRMED, STATE_INVESTIGATE, STATE_QUEUED,
})


class TransmissionError(Exception):
    """Raised for invalid transmission operations (bad sequence, duplicate)."""


class ProductionBlockedError(TransmissionError):
    """Raised when Production transmission is attempted before a successful
    Test-gateway round-trip (REQ-003)."""


class DuplicateSendError(TransmissionError):
    """Raised when an unverified duplicate transmission is attempted without
    explicit operator confirmation + rationale (REQ-046)."""


# ---------------------------------------------------------------------------
# REQ-003 — ESG transmission configuration
# ---------------------------------------------------------------------------

def is_valid_account_type(value) -> bool:
    return str(value or "") in ACCOUNT_TYPES


def validate_esg_config(data: dict) -> list:
    """Validate an ESG transmission-configuration request (REQ-003).

    The account type must be WebTrader or AS2/EDIINT, an X.509 certificate must
    be supplied, and the configuration must never target a direct Health Canada
    AS2 endpoint (CESG rides on the FDA ESG; there is no direct HC endpoint).
    """
    errors = []
    if not is_valid_account_type(data.get("account_type")):
        errors.append({"rule": "account_type_invalid",
                       "message": "ESG account type must be 'WebTrader' or 'AS2'"})
    if not str(data.get("x509_certificate", "") or "").strip():
        errors.append({"rule": "x509_certificate_required",
                       "message": "An X.509 certificate must be uploaded for ESG setup"})
    if str(data.get("hc_direct_endpoint", "") or "").strip():
        errors.append({"rule": "no_direct_hc_endpoint",
                       "message": "CESG rides on the FDA ESG — a direct Health "
                                  "Canada AS2 endpoint must not be targeted"})
    center = str(data.get("recipient_center", RECIPIENT_CENTER) or "").strip()
    if center and center != RECIPIENT_CENTER:
        errors.append({"rule": "recipient_center_must_be_hc",
                       "message": "Recipient Center must be designated 'HC'"})
    return errors


def _cert_fingerprint(pem: str) -> str:
    return "SHA256:" + hashlib.sha256(str(pem or "").encode("utf-8")).hexdigest()


def build_esg_config(data: dict) -> dict:
    """Build the tracked ESG configuration, pinning the targeted environment.

    Production transmission starts disabled and is only unlocked once a Test-
    gateway round-trip completes (see :func:`complete_test_round_trip`).
    """
    return {
        "account_type": str(data.get("account_type", "") or ""),
        "x509_certificate_fingerprint": _cert_fingerprint(
            data.get("x509_certificate", "")),
        "recipient_center": RECIPIENT_CENTER,
        "esg_environment": ESG_ENVIRONMENT,
        "esg_environment_deployed": ESG_ENVIRONMENT_DEPLOYED,
        "nextgen_registration": {
            "registration_id": str(data.get("registration_id", "") or ""),
            "account_type": str(data.get("account_type", "") or ""),
        },
        "test_gateway": {
            "required": True,
            "completed": False,
            "mdn_received": False,
            "fda_ack_received": False,
            "hc_ack_received": False,
        },
        "production_enabled": False,
        "direct_hc_endpoint": False,
    }


def configure_transmission(data: dict) -> dict:
    """Validate + build the ESG configuration (REQ-003)."""
    errors = validate_esg_config(data)
    if errors:
        return {"valid": False, "errors": errors, "config": None}
    return {"valid": True, "errors": [], "config": build_esg_config(data)}


def complete_test_round_trip(config: dict, acks: dict = None) -> dict:
    """Record a Test-gateway round-trip. A round-trip is successful only when
    the MDN, FDA Acknowledgement, and Health Canada Acknowledgement are all
    received; only then is Production transmission unlocked (REQ-003)."""
    acks = acks or {}
    test = dict(config.get("test_gateway") or {})
    test["mdn_received"] = bool(acks.get("mdn_received", True))
    test["fda_ack_received"] = bool(acks.get("fda_ack_received", True))
    test["hc_ack_received"] = bool(acks.get("hc_ack_received", True))
    test["completed"] = (test["mdn_received"] and test["fda_ack_received"]
                         and test["hc_ack_received"])
    new_config = dict(config)
    new_config["test_gateway"] = test
    new_config["production_enabled"] = test["completed"]
    return new_config


def can_transmit_production(config) -> tuple:
    """(allowed, reason) for a Production transmission (REQ-003)."""
    if not config:
        return False, ("No ESG transmission configuration — configure FDA ESG "
                       "NextGen before transmitting")
    if not (config.get("test_gateway") or {}).get("completed"):
        return False, ("Production transmission blocked: complete the Test-"
                       "gateway round-trip checklist (MDN + FDA Ack + HC Ack) "
                       "first")
    return True, ""


def assert_production_allowed(config) -> None:
    allowed, reason = can_transmit_production(config)
    if not allowed:
        raise ProductionBlockedError(reason)


# ---------------------------------------------------------------------------
# REQ-025 / REQ-026 — pre-flight size routing + congestion scheduling
# ---------------------------------------------------------------------------

def congestion_scheduling(size_gb: float) -> dict:
    """REQ-026: offer after-16:30-EST scheduling for 5-10 GB packages."""
    size = float(size_gb or 0)
    offer = CONGESTION_LOWER_GB <= size <= GATEWAY_CEILING_GB
    return {
        "offer": offer,
        "after": CONGESTION_CUTOFF if offer else None,
        "reason": ("Health Canada recommends sending 5-10 GB transactions after "
                   "16:30 EST so they process and deliver overnight."
                   if offer else
                   "No congestion scheduling required for this package size."),
    }


def evaluate_size_routing(size_gb: float) -> dict:
    """REQ-025: evaluate the 10 GB per-transaction ceiling pre-flight.

    Packages at or below 10 GB route to the FDA ESG gateway; packages above
    10 GB route to the physical-media (USB/HDD) workflow with shipping
    instructions. REQ-026's congestion window is folded in.
    """
    size = float(size_gb or 0)
    over_limit = size > GATEWAY_CEILING_GB
    route = "physical_media" if over_limit else "gateway"
    return {
        "size_gb": size,
        "ceiling_gb": GATEWAY_CEILING_GB,
        "over_limit": over_limit,
        "route": route,
        "gateway_available": not over_limit,
        "shipping_instructions": SHIPPING_INSTRUCTIONS if over_limit else None,
        "congestion": congestion_scheduling(size),
    }


# ---------------------------------------------------------------------------
# REQ-058 — physical-media package builder
# ---------------------------------------------------------------------------

def build_media_package(transaction: dict, tree: dict = None) -> dict:
    """Produce a complete media package for a >10 GB transaction (REQ-058):
    the validated eCTD folder tree, both backbones, per-file checksums, and a
    media-manifest/cover documentation. ``tree`` (optional) supplies the
    folder/backbone/file listing; a deterministic placeholder is used when it
    is omitted so the manifest is always well-formed.
    """
    tree = tree or {}
    dossier_id = transaction.get("dossier_id", "")
    sequence = transaction.get("sequence", "")
    folders = list(tree.get("folders") or [f"{sequence}/m1/ca", f"{sequence}/m3",
                                            f"{sequence}/m5"])
    # The dossier_id/sequence are HC-assigned tokens, but they reach this
    # function from caller-supplied transaction data, so escape them the same
    # way every other XML emitter in the portal does — an injected ' or < must
    # never produce malformed or attacker-shaped backbone XML.
    backbones = dict(tree.get("backbones") or {
        "index.xml": (f"<ectd-index dossier={_xml_attr(str(dossier_id))} "
                      f"seq={_xml_attr(str(sequence))}/>"),
        "m1/ca/ca-regional.xml": (f"<ca-regional><dossier-id>"
                                  f"{_xml_escape(str(dossier_id))}"
                                  f"</dossier-id></ca-regional>"),
    })
    files = list(tree.get("files") or [])
    checksums = {f["path"]: md5_hex(f.get("content", f["path"]))
                 for f in files if isinstance(f, dict) and f.get("path")}
    for name, xml in backbones.items():
        checksums[name] = md5_hex(xml)
    manifest = {
        "dossier_id": dossier_id,
        "sequence": sequence,
        "size_gb": transaction.get("size_gb"),
        "route": "physical_media",
        "esg_environment": ESG_ENVIRONMENT,
        "recipient_center": RECIPIENT_CENTER,
        "folders": folders,
        "backbones": sorted(backbones.keys()),
        "file_count": len(checksums),
        "checksums": checksums,
    }
    cover_doc = (
        "HEALTH CANADA — eCTD PHYSICAL MEDIA SUBMISSION\n"
        f"Dossier ID: {dossier_id}\n"
        f"Sequence: {sequence}\n"
        f"Transaction size: {transaction.get('size_gb')} GB "
        f"(exceeds {GATEWAY_CEILING_GB} GB gateway ceiling)\n"
        f"Recipient Center: {RECIPIENT_CENTER}\n"
        f"Files on media: {len(checksums)}\n"
        f"{SHIPPING_INSTRUCTIONS}\n"
    )
    return {
        "folder_tree": folders,
        "backbones": backbones,
        "checksums": checksums,
        "manifest": manifest,
        "cover_documentation": cover_doc,
        "complete": True,
    }


def md5_hex(content) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.md5(content).hexdigest()


# ---------------------------------------------------------------------------
# Per-dossier transmission ledger (REQ-027/028/046/058)
# ---------------------------------------------------------------------------

def _now_iso(now=None) -> str:
    if now is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(now, datetime):
        return now.isoformat()
    return str(now)


def _parse(ts) -> datetime:
    return datetime.fromisoformat(ts)


def _message_id(dossier_id: str, sequence: str) -> str:
    return f"MSG-{dossier_id}-{sequence}"


class TransmissionLedger:
    """The transmission state for a single dossier: its ESG configuration, its
    ordered transactions, the one-at-a-time queue (REQ-027), the ack/transport
    state machine + stall monitors (REQ-046), and the physical-media path
    (REQ-058). Serialisable to/from a dict for sqlite storage.
    """

    def __init__(self, dossier_id: str, config: dict = None):
        self.dossier_id = str(dossier_id or "").strip()
        self.config = config
        self.transactions = []      # ordered list of transaction dicts
        self.audit = []             # immutable, time-ordered event trail

    # -- serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {"dossier_id": self.dossier_id, "config": self.config,
                "transactions": self.transactions, "audit": self.audit}

    @classmethod
    def from_dict(cls, data: dict) -> "TransmissionLedger":
        led = cls(data.get("dossier_id", ""), data.get("config"))
        led.transactions = list(data.get("transactions") or [])
        led.audit = list(data.get("audit") or [])
        return led

    # -- helpers --------------------------------------------------------
    def _log(self, action: str, sequence: str, detail: str, now=None,
             actor: str = "system") -> None:
        self.audit.append({"action": action, "sequence": sequence,
                           "detail": detail, "actor": actor,
                           "at": _now_iso(now)})

    def _find(self, sequence: str):
        for t in self.transactions:
            if t["sequence"] == sequence:
                return t
        return None

    def _find_by_core_id(self, core_id: str):
        for t in self.transactions:
            if t.get("core_id") and t["core_id"] == core_id:
                return t
        return None

    def in_flight(self) -> list:
        """Dispatched, not-yet-resolved transactions occupying the slot."""
        return [t for t in self.transactions if t["state"] in IN_FLIGHT_STATES]

    def queued(self) -> list:
        return [t for t in self.transactions if t["state"] == STATE_QUEUED]

    def set_config(self, config: dict) -> None:
        self.config = config

    # -- REQ-025/026/027: submit a transaction --------------------------
    def submit(self, txn: dict, now=None, production: bool = False) -> dict:
        """Submit a sequence for transmission.

        Routes by size (REQ-025), folds in the congestion offer (REQ-026), and
        — per REQ-027 — dispatches immediately only when no prior transaction is
        in-flight for this dossier; otherwise the transaction is QUEUED until the
        prior Health Canada acknowledgement arrives. ``production=True`` enforces
        the Test-gateway gate (REQ-003).
        """
        sequence = str(txn.get("sequence", "") or "").strip()
        if not sequence:
            raise TransmissionError("a sequence is required to transmit")
        if self._find(sequence):
            raise TransmissionError(
                f"sequence {sequence} already submitted for {self.dossier_id}")
        if production:
            assert_production_allowed(self.config)

        routing = evaluate_size_routing(txn.get("size_gb", 0))
        dispatch = not self.in_flight()      # REQ-027 single-slot gate
        record = {
            "dossier_id": self.dossier_id,
            "sequence": sequence,
            "size_gb": routing["size_gb"],
            "route": routing["route"],
            "over_limit": routing["over_limit"],
            "shipping_instructions": routing["shipping_instructions"],
            "congestion": routing["congestion"],
            "message_id": _message_id(self.dossier_id, sequence),
            "core_id": None,
            "mdn_received": False,
            "fda_ack_received": False,
            "hc_ack_received": False,
            "transport_rejected": False,
            "alerts": [],
            "resends": [],
            "submitted_at": _now_iso(now),
            "sent_at": None,
            "mdn_at": None,
            "fda_ack_at": None,
        }
        if dispatch:
            self._dispatch(record, now)
        else:
            record["state"] = STATE_QUEUED
            record["queued_behind"] = self.in_flight()[0]["sequence"]
            self._log("queued", sequence,
                      f"held behind {record['queued_behind']} (one-at-a-time)",
                      now)
        self.transactions.append(record)
        return record

    def _dispatch(self, record: dict, now=None) -> None:
        """Move a transaction from not-yet-sent to its initial dispatched state."""
        if record["route"] == "physical_media":
            record["state"] = STATE_MEDIA_PREP
            self._log("media_prep", record["sequence"],
                      "routed to physical-media workflow (>10 GB)", now)
        else:
            record["state"] = STATE_SENT
            record["sent_at"] = _now_iso(now)
            self._log("sent", record["sequence"],
                      "dispatched to FDA ESG gateway", now)

    def _process_queue(self, now=None) -> None:
        """Promote the earliest QUEUED transaction once the slot is free."""
        if self.in_flight():
            return
        for t in self.transactions:
            if t["state"] == STATE_QUEUED:
                t.pop("queued_behind", None)
                self._dispatch(t, now)
                self._log("dequeued", t["sequence"],
                          "prior acknowledgement received — now eligible", now)
                break

    # -- REQ-028/046: ack/transport state machine -----------------------
    def receive_mdn(self, sequence: str, now=None) -> dict:
        t = self._require(sequence)
        t["mdn_received"] = True
        t["mdn_at"] = _now_iso(now)
        if t["state"] in (STATE_SENT, STATE_TRANSPORT_UNCONFIRMED):
            t["state"] = STATE_MDN_RECEIVED
        self._log("mdn_received", sequence,
                  "AS2 transport receipt (MDN / NextGen ACK1)", now)
        return t

    def receive_fda_ack(self, sequence: str, core_id: str, now=None,
                        transport_rejected: bool = False) -> dict:
        t = self._require(sequence)
        t["fda_ack_received"] = True
        t["fda_ack_at"] = _now_iso(now)
        t["core_id"] = str(core_id or "") or t.get("core_id")
        if transport_rejected:
            t["transport_rejected"] = True
            t["state"] = STATE_REJECTED
            self._alert(t, "FDA Acknowledgement indicates a transport-level "
                           "rejection", now)
            self._process_queue(now)
        else:
            if t["state"] in (STATE_MDN_RECEIVED, STATE_INVESTIGATE):
                t["state"] = STATE_FDA_ACK
            self._log("fda_ack", sequence,
                      f"FDA Acknowledgement (Message ID {t['message_id']}, "
                      f"Core ID {t['core_id']})", now)
        return t

    def receive_hc_ack(self, core_id: str, now=None, sequence: str = "") -> dict:
        """Record the Health Canada Acknowledgement Receipt — true delivery.

        Correlates by Core ID (gateway path). For the physical-media path the
        Core ID is assigned by HC on receipt, so an explicit ``sequence`` may be
        supplied to bind it (REQ-058 reconciliation). Frees the slot and
        processes the queue (REQ-027).
        """
        t = self._find_by_core_id(core_id)
        if t is None and sequence:
            t = self._find(sequence)
            if t is not None:
                t["core_id"] = str(core_id or "")
        if t is None:
            raise TransmissionError(
                f"no transaction correlates to Core ID '{core_id}'")
        t["hc_ack_received"] = True
        t["state"] = STATE_RECEIVED_BY_HC
        self._log("hc_ack", t["sequence"],
                  f"Health Canada Acknowledgement Receipt (Core ID "
                  f"{t['core_id']}) — received by Health Canada", now)
        self._process_queue(now)
        return t

    # -- REQ-046: timeout monitors + operator alerts --------------------
    def check_monitors(self, now=None, mdn_timeout_s: int = 3600,
                       fda_timeout_s: int = 86400) -> list:
        """Detect stalled transmissions and alert the responsible operator.

        * a SENT transaction with no MDN after ``mdn_timeout_s`` ->
          TRANSPORT_UNCONFIRMED;
        * an MDN-received transaction with no FDA Acknowledgement after
          ``fda_timeout_s`` -> INVESTIGATE (never auto-marked received).

        Returns the list of newly-raised alerts.
        """
        now_dt = _parse(_now_iso(now))
        raised = []
        for t in self.transactions:
            if t["state"] == STATE_SENT and t.get("sent_at"):
                if (now_dt - _parse(t["sent_at"])).total_seconds() > mdn_timeout_s:
                    t["state"] = STATE_TRANSPORT_UNCONFIRMED
                    raised.append(self._alert(
                        t, "transport unconfirmed — no MDN within the configured "
                           "window", now))
            elif t["state"] == STATE_MDN_RECEIVED and t.get("mdn_at"):
                if (now_dt - _parse(t["mdn_at"])).total_seconds() > fda_timeout_s:
                    t["state"] = STATE_INVESTIGATE
                    raised.append(self._alert(
                        t, "MDN received but no FDA Acknowledgement within the "
                           "configured window — flagged for investigation", now))
        return raised

    def _alert(self, t: dict, message: str, now=None) -> dict:
        alert = {"sequence": t["sequence"], "message_id": t["message_id"],
                 "core_id": t.get("core_id"), "message": message,
                 "at": _now_iso(now)}
        t.setdefault("alerts", []).append(alert)
        self._log("alert", t["sequence"], message, now)
        return alert

    # -- REQ-046: duplicate-send prevention -----------------------------
    def resend(self, sequence: str, confirm: bool = False, rationale: str = "",
               now=None, actor: str = "operator") -> dict:
        """Attempt to resend a sequence. If its delivery state is unresolved,
        an unverified duplicate is prevented: explicit confirmation + a recorded
        rationale are required, and the duplicate-send rationale is written to
        the audit trail (REQ-046)."""
        t = self._require(sequence)
        unresolved = t["state"] in UNRESOLVED_STATES
        if unresolved and not (confirm and str(rationale or "").strip()):
            raise DuplicateSendError(
                f"sequence {sequence} delivery state is unresolved "
                f"({t['state']}); resend requires explicit confirmation and a "
                f"recorded rationale to prevent an unverified duplicate")
        entry = {"at": _now_iso(now), "actor": actor,
                 "prior_state": t["state"], "rationale": str(rationale or "")}
        t.setdefault("resends", []).append(entry)
        self._log("resend", sequence,
                  f"duplicate send authorised: {rationale}", now, actor)
        # Re-dispatch from the start of the transport chain.
        t["mdn_received"] = False
        t["fda_ack_received"] = False
        t["mdn_at"] = None
        t["fda_ack_at"] = None
        self._dispatch(t, now)
        return t

    # -- REQ-058: physical-media package + shipment tracking ------------
    def build_media(self, sequence: str, tree: dict = None, now=None) -> dict:
        t = self._require(sequence)
        if t["route"] != "physical_media":
            raise TransmissionError(
                f"sequence {sequence} routes to the gateway, not physical media")
        package = build_media_package(t, tree)
        t["media_package"] = package
        self._log("media_built", sequence,
                  f"media package built ({package['manifest']['file_count']} "
                  f"files + manifest + cover doc)", now)
        return package

    def ship_media(self, sequence: str, carrier: str, tracking: str,
                   now=None) -> dict:
        t = self._require(sequence)
        if not t.get("media_package"):
            raise TransmissionError(
                f"build the media package for {sequence} before shipping")
        t["shipment"] = {"carrier": str(carrier or ""),
                         "tracking": str(tracking or ""),
                         "shipped_at": _now_iso(now), "received": False,
                         "received_at": None}
        t["state"] = STATE_MEDIA_SHIPPED
        self._log("media_shipped", sequence,
                  f"shipped via {carrier} ({tracking})", now)
        return t["shipment"]

    def receive_media(self, sequence: str, now=None) -> dict:
        t = self._require(sequence)
        if not t.get("shipment"):
            raise TransmissionError(f"sequence {sequence} has not been shipped")
        t["shipment"]["received"] = True
        t["shipment"]["received_at"] = _now_iso(now)
        t["state"] = STATE_MEDIA_RECEIVED
        self._log("media_received", sequence,
                  "physical media received by Health Canada records office", now)
        return t["shipment"]

    # -- shared --------------------------------------------------------
    def _require(self, sequence: str) -> dict:
        t = self._find(str(sequence or "").strip())
        if t is None:
            raise TransmissionError(
                f"sequence {sequence} not found for dossier {self.dossier_id}")
        return t

    def status(self) -> dict:
        """A compact, serialisable snapshot for the API/UI."""
        return {
            "dossier_id": self.dossier_id,
            "configured": bool(self.config),
            "production_enabled": bool((self.config or {}).get("production_enabled")),
            "in_flight": [t["sequence"] for t in self.in_flight()],
            "queued": [t["sequence"] for t in self.queued()],
            "transactions": [self._txn_view(t) for t in self.transactions],
            "audit": self.audit,
        }

    @staticmethod
    def _txn_view(t: dict) -> dict:
        return {
            "sequence": t["sequence"], "state": t["state"], "route": t["route"],
            "size_gb": t["size_gb"], "over_limit": t["over_limit"],
            "message_id": t["message_id"], "core_id": t.get("core_id"),
            "hc_ack_received": t["hc_ack_received"],
            "alerts": t.get("alerts", []), "resends": t.get("resends", []),
            "shipment": t.get("shipment"),
            "has_media_package": bool(t.get("media_package")),
            "queued_behind": t.get("queued_behind"),
        }

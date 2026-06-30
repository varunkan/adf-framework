"""Transmission domain — ESG config, size routing, and the ack-chain ledger.

Pure stdlib, clock-injectable (ported from the monolith). The ``TransmissionLedger``
is the per-dossier aggregate: one in-flight transaction at a time (REQ-027), the
MDN → FDA Ack → HC Ack state machine (REQ-028), and stall monitors (REQ-046).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

ESG_ENVIRONMENT = "FDA ESG NextGen"
ESG_ENVIRONMENT_DEPLOYED = "2025-04"
RECIPIENT_CENTER = "HC"
ACCOUNT_TYPES = {"WebTrader": "FDA ESG WebTrader (browser upload)",
                 "AS2": "AS2/EDIINT (machine-to-machine)"}

GATEWAY_CEILING_GB = 10.0
CONGESTION_LOWER_GB = 5.0
CONGESTION_CUTOFF = "16:30 EST"
SHIPPING_INSTRUCTIONS = (
    "Write the validated eCTD folder tree to USB/HDD media, include the media "
    "manifest and signed cover documentation, and ship to the Health Canada "
    "records office per the CESG media-submission guidance.")

STATE_QUEUED = "QUEUED"
STATE_SENT = "SENT"
STATE_MDN_RECEIVED = "MDN_RECEIVED"
STATE_FDA_ACK = "FDA_ACK"
STATE_RECEIVED_BY_HC = "RECEIVED_BY_HC"
STATE_MEDIA_PREP = "MEDIA_PREP"
STATE_TRANSPORT_UNCONFIRMED = "TRANSPORT_UNCONFIRMED"
STATE_INVESTIGATE = "INVESTIGATE"
STATE_REJECTED = "REJECTED"

IN_FLIGHT_STATES = frozenset({
    STATE_SENT, STATE_MDN_RECEIVED, STATE_FDA_ACK, STATE_MEDIA_PREP,
    STATE_TRANSPORT_UNCONFIRMED, STATE_INVESTIGATE})


class TransmissionError(Exception):
    """Invalid transmission operation (bad sequence, duplicate)."""


class ProductionBlockedError(TransmissionError):
    """Production attempted before a successful Test-gateway round-trip."""


# -- config ------------------------------------------------------------------
def is_valid_account_type(value) -> bool:
    return str(value or "") in ACCOUNT_TYPES


def validate_esg_config(data: dict) -> list:
    errors = []
    if not is_valid_account_type(data.get("account_type")):
        errors.append({"rule": "account_type_invalid",
                       "message": "ESG account type must be 'WebTrader' or 'AS2'"})
    if not str(data.get("x509_certificate", "") or "").strip():
        errors.append({"rule": "x509_certificate_required",
                       "message": "An X.509 certificate must be uploaded"})
    if str(data.get("hc_direct_endpoint", "") or "").strip():
        errors.append({"rule": "no_direct_hc_endpoint",
                       "message": "CESG rides on the FDA ESG — no direct HC "
                                  "endpoint may be targeted"})
    center = str(data.get("recipient_center", RECIPIENT_CENTER) or "").strip()
    if center and center != RECIPIENT_CENTER:
        errors.append({"rule": "recipient_center_must_be_hc",
                       "message": "Recipient Center must be 'HC'"})
    return errors


def _cert_fingerprint(pem: str) -> str:
    return "SHA256:" + hashlib.sha256(str(pem or "").encode("utf-8")).hexdigest()


def build_esg_config(data: dict) -> dict:
    return {
        "account_type": str(data.get("account_type", "") or ""),
        "x509_certificate_fingerprint": _cert_fingerprint(
            data.get("x509_certificate", "")),
        "recipient_center": RECIPIENT_CENTER, "esg_environment": ESG_ENVIRONMENT,
        "esg_environment_deployed": ESG_ENVIRONMENT_DEPLOYED,
        "test_gateway": {"required": True, "completed": False,
                         "mdn_received": False, "fda_ack_received": False,
                         "hc_ack_received": False},
        "production_enabled": False, "direct_hc_endpoint": False}


def configure_transmission(data: dict) -> dict:
    errors = validate_esg_config(data)
    if errors:
        return {"valid": False, "errors": errors, "config": None}
    return {"valid": True, "errors": [], "config": build_esg_config(data)}


def complete_test_round_trip(config: dict, acks: dict = None) -> dict:
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
    if not config:
        return False, "No ESG configuration — configure FDA ESG NextGen first"
    if not (config.get("test_gateway") or {}).get("completed"):
        return False, ("Production blocked: complete the Test-gateway round-trip "
                       "(MDN + FDA Ack + HC Ack) first")
    return True, ""


def assert_production_allowed(config) -> None:
    allowed, reason = can_transmit_production(config)
    if not allowed:
        raise ProductionBlockedError(reason)


# -- size routing ------------------------------------------------------------
def congestion_scheduling(size_gb: float) -> dict:
    size = float(size_gb or 0)
    offer = CONGESTION_LOWER_GB <= size <= GATEWAY_CEILING_GB
    return {"offer": offer, "after": CONGESTION_CUTOFF if offer else None}


def evaluate_size_routing(size_gb: float) -> dict:
    size = float(size_gb or 0)
    over = size > GATEWAY_CEILING_GB
    return {"size_gb": size, "ceiling_gb": GATEWAY_CEILING_GB, "over_limit": over,
            "route": "physical_media" if over else "gateway",
            "gateway_available": not over,
            "shipping_instructions": SHIPPING_INSTRUCTIONS if over else None,
            "congestion": congestion_scheduling(size)}


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
    def __init__(self, dossier_id: str, config: dict = None):
        self.dossier_id = str(dossier_id or "").strip()
        self.config = config
        self.transactions = []
        self.audit = []

    def to_dict(self) -> dict:
        return {"dossier_id": self.dossier_id, "config": self.config,
                "transactions": self.transactions, "audit": self.audit}

    @classmethod
    def from_dict(cls, data: dict) -> "TransmissionLedger":
        led = cls(data.get("dossier_id", ""), data.get("config"))
        led.transactions = list(data.get("transactions") or [])
        led.audit = list(data.get("audit") or [])
        return led

    def _log(self, action, sequence, detail, now=None):
        self.audit.append({"action": action, "sequence": sequence,
                           "detail": detail, "at": _now_iso(now)})

    def _find(self, sequence):
        return next((t for t in self.transactions
                     if t["sequence"] == sequence), None)

    def _find_by_core_id(self, core_id):
        return next((t for t in self.transactions
                     if t.get("core_id") and t["core_id"] == core_id), None)

    def _require(self, sequence):
        t = self._find(sequence)
        if t is None:
            raise TransmissionError(f"no transaction for sequence {sequence}")
        return t

    def in_flight(self) -> list:
        return [t for t in self.transactions if t["state"] in IN_FLIGHT_STATES]

    def queued(self) -> list:
        return [t for t in self.transactions if t["state"] == STATE_QUEUED]

    def set_config(self, config: dict) -> None:
        self.config = config

    def submit(self, txn: dict, now=None, production: bool = False) -> dict:
        sequence = str(txn.get("sequence", "") or "").strip()
        if not sequence:
            raise TransmissionError("a sequence is required to transmit")
        if self._find(sequence):
            raise TransmissionError(
                f"sequence {sequence} already submitted for {self.dossier_id}")
        if production:
            assert_production_allowed(self.config)
        routing = evaluate_size_routing(txn.get("size_gb", 0))
        dispatch = not self.in_flight()
        record = {
            "dossier_id": self.dossier_id, "sequence": sequence,
            "size_gb": routing["size_gb"], "route": routing["route"],
            "over_limit": routing["over_limit"],
            "shipping_instructions": routing["shipping_instructions"],
            "message_id": _message_id(self.dossier_id, sequence),
            "core_id": None, "mdn_received": False, "fda_ack_received": False,
            "hc_ack_received": False, "transport_rejected": False, "alerts": [],
            "submitted_at": _now_iso(now), "sent_at": None, "mdn_at": None,
            "fda_ack_at": None}
        if dispatch:
            self._dispatch(record, now)
        else:
            record["state"] = STATE_QUEUED
            record["queued_behind"] = self.in_flight()[0]["sequence"]
            self._log("queued", sequence,
                      f"held behind {record['queued_behind']}", now)
        self.transactions.append(record)
        return record

    def _dispatch(self, record, now=None):
        if record["route"] == "physical_media":
            record["state"] = STATE_MEDIA_PREP
            self._log("media_prep", record["sequence"], ">10 GB media path", now)
        else:
            record["state"] = STATE_SENT
            record["sent_at"] = _now_iso(now)
            self._log("sent", record["sequence"], "dispatched to FDA ESG", now)

    def _process_queue(self, now=None):
        if self.in_flight():
            return
        for t in self.transactions:
            if t["state"] == STATE_QUEUED:
                t.pop("queued_behind", None)
                self._dispatch(t, now)
                self._log("dequeued", t["sequence"], "prior ack received", now)
                break

    def receive_mdn(self, sequence, now=None) -> dict:
        t = self._require(sequence)
        t["mdn_received"] = True
        t["mdn_at"] = _now_iso(now)
        if t["state"] in (STATE_SENT, STATE_TRANSPORT_UNCONFIRMED):
            t["state"] = STATE_MDN_RECEIVED
        self._log("mdn_received", sequence, "AS2 MDN / NextGen ACK1", now)
        return t

    def receive_fda_ack(self, sequence, core_id, now=None,
                        transport_rejected=False) -> dict:
        t = self._require(sequence)
        t["fda_ack_received"] = True
        t["fda_ack_at"] = _now_iso(now)
        t["core_id"] = str(core_id or "") or t.get("core_id")
        if transport_rejected:
            t["transport_rejected"] = True
            t["state"] = STATE_REJECTED
            self._log("rejected", sequence, "transport-level rejection", now)
            self._process_queue(now)
        else:
            if t["state"] in (STATE_MDN_RECEIVED, STATE_INVESTIGATE):
                t["state"] = STATE_FDA_ACK
            self._log("fda_ack", sequence,
                      f"FDA Ack (Core ID {t['core_id']})", now)
        return t

    def receive_hc_ack(self, core_id, now=None, sequence="") -> dict:
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
                  f"HC Acknowledgement Receipt (Core ID {t['core_id']})", now)
        self._process_queue(now)
        return t

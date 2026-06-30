"""Transmission application service — ESG config, submit, ack chain + events."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import transmission as tx
from .ports import TransmissionRepository


def _s(v) -> str:
    return str(v or "").strip()


class TransmissionService:
    def __init__(self, repo: TransmissionRepository, bus,
                 *, source: str = "transmission") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "TransmissionService":
        return self

    # -- helpers ------------------------------------------------------------
    def _load(self, dossier_id: str, *, create: bool = False):
        data = self.repo.get(dossier_id)
        if data:
            return tx.TransmissionLedger.from_dict(data)
        if create:
            return tx.TransmissionLedger(dossier_id)
        return None

    def _save(self, ledger) -> dict:
        return self.repo.save(ledger.to_dict())

    # -- config -------------------------------------------------------------
    def configure(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        result = tx.configure_transmission(data)
        if not result["valid"]:
            raise ProblemError(422, "Invalid ESG configuration",
                               errors=result["errors"])
        ledger = self._load(dossier_id, create=True)
        ledger.set_config(result["config"])
        self._save(ledger)
        return {"dossier_id": dossier_id, "config": ledger.config}

    def test_round_trip(self, data: dict) -> dict:
        ledger = self._load(_s(data.get("dossier_id")))
        if not ledger or not ledger.config:
            raise ProblemError(409, "configure ESG before the test round-trip",
                               rule="not_configured")
        ledger.config = tx.complete_test_round_trip(ledger.config, {
            "mdn_received": data.get("mdn_received", True),
            "fda_ack_received": data.get("fda_ack_received", True),
            "hc_ack_received": data.get("hc_ack_received", True)})
        self._save(ledger)
        return {"dossier_id": ledger.dossier_id, "config": ledger.config}

    def route(self, size_gb: float) -> dict:
        return tx.evaluate_size_routing(size_gb)

    # -- submit / ack -------------------------------------------------------
    def submit(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        ledger = self._load(dossier_id, create=True)
        try:
            record = ledger.submit(
                {"sequence": data.get("sequence"), "size_gb": data.get("size_gb")},
                production=bool(data.get("production")))
        except tx.ProductionBlockedError as exc:
            raise ProblemError(409, str(exc), rule="production_blocked")
        except tx.TransmissionError as exc:
            raise ProblemError(409, str(exc), rule="transmission_error")
        self._save(ledger)
        if record["state"] == tx.STATE_SENT:
            self.bus.publish(EventEnvelope.make(
                EventType.TRANSMISSION_SENT, source=self.source,
                dossier_id=dossier_id,
                data={"sequence": record["sequence"],
                      "message_id": record["message_id"]}))
        return record

    def ack(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        ledger = self._load(dossier_id)
        if not ledger:
            raise ProblemError(404, "no transmission ledger for dossier",
                               detail=dossier_id)
        kind = _s(data.get("kind")).lower()
        try:
            if kind == "mdn":
                txn = ledger.receive_mdn(_s(data.get("sequence")))
            elif kind == "fda":
                txn = ledger.receive_fda_ack(
                    _s(data.get("sequence")), _s(data.get("core_id")),
                    transport_rejected=bool(data.get("transport_rejected")))
            elif kind == "hc":
                txn = ledger.receive_hc_ack(
                    _s(data.get("core_id")), sequence=_s(data.get("sequence")))
            else:
                raise ProblemError(422, f"unknown ack kind: {kind}",
                                   rule="ack_kind_unknown")
        except tx.TransmissionError as exc:
            raise ProblemError(409, str(exc), rule="transmission_error")
        self._save(ledger)
        if kind == "hc":
            self.bus.publish(EventEnvelope.make(
                EventType.TRANSMISSION_HC_ACK, source=self.source,
                dossier_id=dossier_id,
                data={"core_id": txn["core_id"], "sequence": txn["sequence"],
                      "recipients": data.get("notify") or []}))
        return txn

    def get(self, dossier_id: str) -> dict:
        ledger = self.repo.get(_s(dossier_id))
        if not ledger:
            raise ProblemError(404, "no transmission ledger for dossier",
                               detail=_s(dossier_id))
        return ledger

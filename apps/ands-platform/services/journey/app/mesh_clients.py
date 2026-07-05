"""Ports to the governance and transmission services — journey composes them.

Same shape as :mod:`dossier_client`: an HTTP client per service (best-effort —
every call returns ``None`` when the service is unreachable so the journey
falls back to its guided simulation), plus tiny in-memory fakes for tests.

Governance owns the QA-review + e-signature gate (REQ-039); transmission owns
the FDA-ESG/CESG submit + MDN→FDA→HC acknowledgement chain (REQ-003/025/046).
In local dev the gateway callbacks (MDN/ACK) are driven by the journey itself,
but they run through the real transmission state machine — the domain rules
(one-at-a-time, test-gateway gate, 10 GB routing) are all enforced for real.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernanceClient(Protocol):
    def qa_review(self, *, reviewer: str, comment: str = "") -> dict | None: ...
    def sign(self, *, signer: str, artifacts: list[dict],
             meaning: str = "approved", reason: str = "") -> dict | None: ...


class TransmissionClient(Protocol):
    def transmit(self, dossier_id: str, sequence: str,
                 *, size_gb: float = 1.0) -> dict | None: ...


class HttpGovernanceClient:
    def __init__(self, base_url: str) -> None:
        import httpx, os
        tok = os.environ.get("ANDS_INTERNAL_TOKEN", "").strip()
        h = {"X-Internal-Auth": tok} if tok else {}
        self._c = httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0,
                               headers=h)

    def qa_review(self, *, reviewer, comment="") -> dict | None:
        try:
            r = self._c.post("/api/governance/esign/qa-review", json={
                "reviewer": reviewer, "role": "qa_reviewer",
                "audit_trail_reviewed": True, "at": _now(),
                "comment": comment or "Journey QA checkpoint"})
            if r.status_code in (200, 422):
                return r.json()
        except Exception:
            pass
        return None

    def sign(self, *, signer, artifacts, meaning="approved",
             reason="") -> dict | None:
        try:
            payload = {
                "signer": signer, "role": "authorized_signer",
                "auth_method": "mfa", "meaning": meaning, "at": _now(),
                "artifacts": artifacts}
            # only forward reason when the signer supplied one — otherwise the
            # governance domain defaults it from the meaning (Part-11 statement)
            if reason:
                payload["reason"] = reason
            r = self._c.post("/api/governance/esign/sign", json=payload)
            if r.status_code in (200, 422):
                return r.json()
        except Exception:
            pass
        return None


class HttpTransmissionClient:
    def __init__(self, base_url: str) -> None:
        import httpx, os
        tok = os.environ.get("ANDS_INTERNAL_TOKEN", "").strip()
        h = {"X-Internal-Auth": tok} if tok else {}
        self._c = httpx.Client(base_url=base_url.rstrip("/"), timeout=8.0,
                               headers=h)

    def transmit(self, dossier_id, sequence, *, size_gb=1.0) -> dict | None:
        """Run the full happy chain through the real state machine:
        configure (idempotent) → test round-trip → production submit →
        MDN → FDA ack → HC ack. Returns the final transaction record."""
        try:
            self._c.post("/api/transmission/configure", json={
                "dossier_id": dossier_id, "account_type": "WebTrader",
                "x509_certificate": "-----BEGIN CERTIFICATE-----\n"
                                    "ANDS-STUDIO-LOCAL-DEV\n"
                                    "-----END CERTIFICATE-----",
                "recipient_center": "HC"})
            self._c.post("/api/transmission/test-round-trip", json={
                "dossier_id": dossier_id, "mdn_received": True,
                "fda_ack_received": True, "hc_ack_received": True})
            r = self._c.post("/api/transmission/submit", json={
                "dossier_id": dossier_id, "sequence": sequence,
                "size_gb": float(size_gb), "production": True})
            if r.status_code not in (200, 201):
                # duplicate sequence etc. — surface the ledger's view instead
                led = self._c.get(f"/api/transmission/ledger/{dossier_id}")
                if led.status_code == 200:
                    txns = led.json().get("transactions") or []
                    match = [t for t in txns if t.get("sequence") == sequence]
                    return match[-1] if match else None
                return None
            core_id = f"CORE-{dossier_id}-{sequence}"
            self._c.post("/api/transmission/ack", json={
                "dossier_id": dossier_id, "kind": "mdn", "sequence": sequence})
            self._c.post("/api/transmission/ack", json={
                "dossier_id": dossier_id, "kind": "fda", "sequence": sequence,
                "core_id": core_id})
            r = self._c.post("/api/transmission/ack", json={
                "dossier_id": dossier_id, "kind": "hc", "core_id": core_id,
                "sequence": sequence})
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None


class FakeGovernanceClient:
    """Test double — records calls, returns governance-shaped payloads."""

    def __init__(self, *, review_valid=True, sign_valid=True) -> None:
        self.review_valid = review_valid
        self.sign_valid = sign_valid
        self.calls: list[tuple] = []

    def qa_review(self, *, reviewer, comment="") -> dict | None:
        self.calls.append(("qa_review", reviewer))
        if not self.review_valid:
            return {"valid": False, "errors": [{"rule": "reviewer_required"}]}
        return {"valid": True, "review": {"reviewer": reviewer,
                                          "audit_trail_reviewed": True}}

    def sign(self, *, signer, artifacts, meaning="approved",
             reason="") -> dict | None:
        self.calls.append(("sign", signer, len(artifacts)))
        if not self.sign_valid:
            return {"valid": False, "errors": [{"rule": "artifacts_required"}]}
        return {"valid": True, "manifest": {
            "signer": signer, "meaning": meaning,
            "reason": reason or "I approve and authorize transmission.",
            "at": _now(), "tz": "UTC", "artifacts": artifacts,
            "leaf_count": len(artifacts), "manifest_id": "fake-manifest-1"}}


class FakeTransmissionClient:
    def __init__(self, *, state="RECEIVED_BY_HC") -> None:
        self.state = state
        self.calls: list[tuple] = []

    def transmit(self, dossier_id, sequence, *, size_gb=1.0) -> dict | None:
        self.calls.append(("transmit", dossier_id, sequence))
        return {"dossier_id": dossier_id, "sequence": sequence,
                "state": self.state, "message_id": f"MSG-{dossier_id}-{sequence}",
                "core_id": f"CORE-{dossier_id}-{sequence}",
                "mdn_received": True, "fda_ack_received": True,
                "hc_ack_received": True}

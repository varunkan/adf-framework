"""Port to the dossier service (the eCTD engine) — the journey composes it.

The journey BFF cannot import the dossier service in-process (their top-level
``app`` packages collide), so it talks to it through this client port:
``HttpDossierClient`` (httpx to ``DOSSIER_URL``) in production, and an
``InProcessDossierClient`` (wrapping a ``DossierService``) for the in-process
integration mesh + tests. Every call is best-effort: if the dossier service is
unreachable the journey falls back to its own flat content model, so a
dossier-less session still works.
"""

from __future__ import annotations

from typing import Protocol


class DossierClient(Protocol):
    def ensure_dossier(self, dossier_id: str, *, title: str = "",
                       submission_type: str = "ANDS",
                       cs_be_only: bool = True,
                       tenant_id: str | None = None,
                       company_id: str = "", sponsor: str = "") -> None: ...
    def content_state(self, dossier_id: str) -> dict | None: ...
    def validate(self, dossier_id: str) -> dict | None: ...
    def set_fees(self, dossier_id: str, fee_paid: bool,
                 sme_granted: bool) -> dict | None: ...


class HttpDossierClient:
    def __init__(self, base_url: str) -> None:
        import httpx
        self._c = httpx.Client(base_url=base_url.rstrip("/"), timeout=5.0)

    def ensure_dossier(self, dossier_id, *, title="", submission_type="ANDS",
                       cs_be_only=True, tenant_id=None, company_id="",
                       sponsor="") -> None:
        try:
            headers = {"X-Tenant-Id": tenant_id} if tenant_id else {}
            self._c.post("/api/dossier/dossiers", json={
                "dossier_id": dossier_id, "title": title or dossier_id,
                "submission_type": submission_type, "cs_be_only": cs_be_only,
                "company_id": company_id, "sponsor": sponsor},
                headers=headers)
        except Exception:
            pass

    def content_state(self, dossier_id) -> dict | None:
        try:
            r = self._c.get(f"/api/dossier/dossiers/{dossier_id}/content")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def validate(self, dossier_id) -> dict | None:
        """Full technical eCTD validation (PDF conformance on stored bytes)."""
        try:
            r = self._c.get(f"/api/dossier/dossiers/{dossier_id}/validate")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def set_fees(self, dossier_id, fee_paid, sme_granted) -> dict | None:
        try:
            r = self._c.post(f"/api/dossier/dossiers/{dossier_id}/fees", json={
                "fee_paid": bool(fee_paid), "sme_granted": bool(sme_granted)})
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None


class InProcessDossierClient:
    """Wraps a live ``DossierService`` — for the integration mesh + unit tests."""

    def __init__(self, service) -> None:
        self.service = service

    def ensure_dossier(self, dossier_id, *, title="", submission_type="ANDS",
                       cs_be_only=True, tenant_id=None, company_id="",
                       sponsor="") -> None:
        try:
            self.service.create_dossier({
                "dossier_id": dossier_id, "title": title or dossier_id,
                "submission_type": submission_type, "cs_be_only": cs_be_only,
                "company_id": company_id, "sponsor": sponsor},
                tenant_id)
        except Exception:
            pass

    def content_state(self, dossier_id) -> dict | None:
        try:
            return self.service.content_state(dossier_id)
        except Exception:
            return None

    def validate(self, dossier_id) -> dict | None:
        try:
            return self.service.validate_submission(dossier_id)
        except Exception:
            return None

    def set_fees(self, dossier_id, fee_paid, sme_granted) -> dict | None:
        try:
            return self.service.set_fee_status(dossier_id, fee_paid, sme_granted)
        except Exception:
            return None

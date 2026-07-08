"""Registry application service — registrations + status + Right-to-Sell."""

from __future__ import annotations

from datetime import datetime, timezone

from ands_shared import EventEnvelope, EventType, ProblemError, utcnow_iso

from . import registry
from .ports import RegistrationRepository


def _s(v) -> str:
    return str(v or "").strip()


class RegistryService:
    def __init__(self, repo: RegistrationRepository, bus,
                 *, source: str = "registry", reauth=None) -> None:
        self.repo = repo
        self.bus = bus
        self.source = source
        # round-9: the credential re-auth port for controlled e-signatures —
        # callable (email, password, mfa_code) -> bool, wired to the identity
        # service in main.py; injectable in tests. Signing REQUIRES it.
        self.reauth = reauth

    def register(self) -> "RegistryService":
        return self

    @staticmethod
    def _enrich(reg: dict | None) -> dict | None:
        """TIER-B: re-derive the honest NNHPD/Biocides regulatory note from the
        row's drug_type on the way out. The note is not a stored column (it is a
        pure function of drug_type), so deriving it here keeps every read path —
        create, get, list, set_status — honestly annotated without a migration."""
        if reg is not None:
            reg["regulatory_note"] = registry.regulatory_note(reg.get("drug_type"))
        return reg

    def create(self, data: dict, tenant_id: str | None = None) -> dict:
        res = registry.new_registration(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid registration",
                               errors=res["errors"])
        reg_data = dict(res["registration"])
        reg_data["tenant_id"] = _s(tenant_id) or None
        reg = self._enrich(self.repo.add(reg_data))
        self._emit(reg, "created")
        return reg

    def get(self, reg_id: str, tenant_id: str | None = None) -> dict:
        reg = self.repo.get(_s(reg_id))
        if not reg or not self._tenant_ok(reg, tenant_id):
            raise ProblemError(404, "registration not found", detail=_s(reg_id))
        return self._enrich(reg)

    def list(self, *, tenant_id: str | None = None, **filters) -> dict:
        regs = [self._enrich(r) for r in self.repo.list(tenant_id=_s(tenant_id),
                                                         **filters)]
        return {"registrations": regs, "count": len(regs)}

    def set_status(self, reg_id: str, status: str,
                   tenant_id: str | None = None) -> dict:
        reg = self.repo.get(_s(reg_id))
        if not reg or not self._tenant_ok(reg, tenant_id):
            raise ProblemError(404, "registration not found", detail=_s(reg_id))
        check = registry.validate_status_transition(reg["status"], status)
        if not check["valid"]:
            http = 422 if check["rule"] == "status_unknown" else 409
            raise ProblemError(http, check["message"], rule=check["rule"])
        reg = self._enrich(self.repo.set_status(reg_id, _s(status)))
        self._emit(reg, "status_changed")
        return reg

    @staticmethod
    def _tenant_ok(reg: dict, tenant_id: str | None) -> bool:
        """Per-row tenant ownership. When no tenant context is supplied
        (in-process mesh / tests) access is unscoped. When it IS supplied a row
        owned by a DIFFERENT tenant — or by no tenant at all — is invisible
        (caller raises 404, not 403, to avoid confirming existence)."""
        if not _s(tenant_id):
            return True
        return _s(reg.get("tenant_id")) == _s(tenant_id)

    def right_to_sell(self, reg_id: str, as_of: str,
                      tenant_id: str | None = None) -> dict:
        reg = self.get(reg_id, tenant_id)
        try:
            return registry.right_to_sell_obligation(reg, as_of)
        except ValueError as exc:
            raise ProblemError(422, f"invalid as_of date: {exc}",
                               rule="invalid_as_of")

    # -- annual notification checklist (server-tracked, per workspace) -------
    def annual_checklist(self, year: int,
                         tenant_id: str | None = None) -> dict:
        year = int(year) or datetime.now(timezone.utc).year
        saved = {r["item_key"]: r
                 for r in self.repo.get_checklist(_s(tenant_id), year)}
        items = []
        for key, label in registry.ANNUAL_CHECKLIST_ITEMS:
            row = saved.get(key) or {}
            done = bool(row.get("done"))
            items.append({"item_key": key, "label": label, "done": done,
                          "signed_by": row.get("signed_by") if done else None,
                          "signed_at": row.get("signed_at") if done else None,
                          "meaning": row.get("meaning") if done else None,
                          "reauthenticated":
                              bool(row.get("reauthenticated")) if done
                              else False})
        return {"year": year, "items": items, "count": len(items)}

    def set_annual_item(self, data: dict, tenant_id: str | None = None,
                        user_email: str = "") -> dict:
        key = _s(data.get("item_key"))
        if key not in registry.ANNUAL_CHECKLIST_KEYS:
            raise ProblemError(422, f"unknown checklist item: {key}",
                               rule="checklist_item_unknown")
        year = int(data.get("year") or 0) or datetime.now(timezone.utc).year
        done = bool(data.get("done"))
        signed_by = signed_at = meaning = None
        reauthed = False
        if done:
            # round-9 (qa_manager): a tick is a CONTROLLED e-signature —
            # credential re-auth at the moment of signing + a captured
            # meaning-of-signature. Identity comes from the RE-AUTHENTICATED
            # email, never from a spoofable header.
            meaning = _s(data.get("meaning"))
            if not meaning:
                raise ProblemError(
                    422, "a meaning-of-signature attestation is required",
                    rule="signature_meaning_required")
            email = _s(data.get("email")).lower()
            password = _s(data.get("password"))
            if not email or not password:
                raise ProblemError(
                    401, "re-enter your credentials to sign",
                    rule="signature_reauth_required")
            if self.reauth is None or not self.reauth(
                    email, password, _s(data.get("mfa_code"))):
                raise ProblemError(
                    401, "credentials did not verify — the item was NOT signed",
                    rule="signature_reauth_failed")
            signed_by, signed_at, reauthed = email, utcnow_iso(), True
        else:
            # unticking clears the signature; the actor lands in the log
            signed_by = None
        row = self.repo.set_checklist_item(
            _s(tenant_id), year, key, done,
            signed_by if done else (_s(user_email) or None),
            signed_at, meaning, reauthed)
        self.bus.publish(EventEnvelope.make(
            EventType.ANNUAL_CHECKLIST_SIGNED, source=self.source,
            tenant_id=_s(tenant_id),
            data={"year": year, "item_key": key, "done": done,
                  "signed_by": signed_by, "signed_at": signed_at,
                  "meaning": meaning, "reauthenticated": reauthed}))
        item = {"item_key": key,
                "label": dict(registry.ANNUAL_CHECKLIST_ITEMS)[key],
                "done": bool(row.get("done")),
                "signed_by": row.get("signed_by") if done else None,
                "signed_at": row.get("signed_at"),
                "meaning": row.get("meaning"),
                "reauthenticated": bool(row.get("reauthenticated"))}
        return {"year": year, "item": item}

    def annual_signing_log(self, year: int,
                           tenant_id: str | None = None) -> dict:
        """The viewable, append-only signing record (round-9)."""
        year = int(year) or datetime.now(timezone.utc).year
        entries = [
            {"item_key": r["item_key"], "action": r["action"],
             "signed_by": r["signed_by"], "signed_at": r["signed_at"],
             "meaning": r["meaning"],
             "reauthenticated": bool(r["reauthenticated"])}
            for r in self.repo.get_checklist_log(_s(tenant_id), year)]
        return {"year": year, "entries": entries, "count": len(entries)}

    def _emit(self, reg: dict, event: str) -> None:
        self.bus.publish(EventEnvelope.make(
            EventType.REGISTRATION_STATUS_CHANGED, source=self.source,
            dossier_id=reg.get("dossier_id"),
            data={"registration_id": reg["id"], "event": event,
                  "status": reg["status"], "din": reg.get("din")}))

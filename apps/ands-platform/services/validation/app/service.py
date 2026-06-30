"""Validation application service — run/inline/fix + event emission (REQ-104).

``validate`` persists the run and publishes ``validation.completed`` always and
``validation.failed`` when blocking — the latter is what the collaboration
service consumes to notify owners of a blocking defect.
"""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import engine, remediation, rules
from .ports import ValidationRepository


def _s(v) -> str:
    return str(v or "").strip()


class ValidationService:
    def __init__(self, repo: ValidationRepository, bus,
                 *, source: str = "validation") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "ValidationService":
        return self

    # -- rulesets -----------------------------------------------------------
    def list_rulesets(self) -> dict:
        return {"active": rules.ACTIVE_RULESET_VERSION,
                "versions": [{"version": v, "effective": meta["effective"]}
                             for v, meta in sorted(rules.RULESETS.items())]}

    def ruleset(self, version: str, profile: str = rules.PROFILE_ECTD) -> dict:
        try:
            return rules.ruleset_catalog(
                version or rules.ACTIVE_RULESET_VERSION,
                profile or rules.PROFILE_ECTD)
        except rules.UnknownRulesetError as exc:
            raise ProblemError(404, "Unknown ruleset", detail=str(exc))
        except rules.UnknownProfileError as exc:
            raise ProblemError(404, "Unknown profile", detail=str(exc))

    def profiles(self) -> dict:
        return rules.list_validation_profiles()

    # -- run / inline / fix -------------------------------------------------
    def validate(self, data: dict) -> dict:
        ctx = data.get("context") or {}
        version = _s(data.get("version")) or rules.ACTIVE_RULESET_VERSION
        profile = _s(data.get("profile")) or rules.PROFILE_ECTD
        try:
            result = engine.run_validation(ctx, version, profile)
        except (rules.UnknownRulesetError, rules.UnknownProfileError) as exc:
            raise ProblemError(422, "Invalid ruleset/profile", detail=str(exc))
        dossier_id = _s(data.get("dossier_id")) or _s(ctx.get("dossier_id"))
        sequence = _s(data.get("sequence")) or _s(ctx.get("sequence")) or "0000"
        run = self.repo.save_run(dossier_id, sequence, result)

        self.bus.publish(EventEnvelope.make(
            EventType.VALIDATION_COMPLETED, source=self.source,
            dossier_id=dossier_id,
            data={"run_id": run["id"], "sequence": sequence,
                  "blocking": result["blocking"],
                  "error_count": result["error_count"],
                  "warning_count": result["warning_count"]}))
        if result["blocking"]:
            top = result["errors"][0]
            self.bus.publish(EventEnvelope.make(
                EventType.VALIDATION_FAILED, source=self.source,
                dossier_id=dossier_id,
                data={"run_id": run["id"], "sequence": sequence,
                      "error_count": result["error_count"],
                      "finding": {"rule": top["rule_id"],
                                  "message": top["message"]},
                      "recipients": data.get("notify") or []}))
        return {"run_id": run["id"], **result}

    def inline(self, data: dict) -> dict:
        ctx = data.get("context") or {}
        version = _s(data.get("version")) or rules.ACTIVE_RULESET_VERSION
        profile = _s(data.get("profile")) or rules.PROFILE_ECTD
        try:
            return engine.inline_findings(ctx, version, profile)
        except (rules.UnknownRulesetError, rules.UnknownProfileError) as exc:
            raise ProblemError(422, "Invalid ruleset/profile", detail=str(exc))

    def fix(self, data: dict) -> dict:
        ctx = data.get("context") or {}
        try:
            new_ctx = engine.apply_fix(ctx, _s(data.get("fix_id")),
                                       _s(data.get("file")))
        except ValueError as exc:
            raise ProblemError(422, "Unknown fix", detail=str(exc))
        return {"context": new_ctx, "inline": engine.inline_findings(new_ctx)}

    # -- batch validation jobs (REQ-116) -----------------------------------
    def submit_batch(self, data: dict) -> dict:
        contexts = data.get("contexts") or []
        if not contexts:
            raise ProblemError(422, "contexts is required and non-empty",
                               rule="contexts_required")
        version = _s(data.get("version")) or rules.ACTIVE_RULESET_VERSION
        profile = _s(data.get("profile")) or rules.PROFILE_ECTD
        try:
            result = engine.run_batch(contexts, version, profile)
        except (rules.UnknownRulesetError, rules.UnknownProfileError) as exc:
            raise ProblemError(422, "Invalid ruleset/profile", detail=str(exc))
        return self.repo.save_job(result)

    def get_job(self, job_id: str) -> dict:
        job = self.repo.get_job(_s(job_id))
        if not job:
            raise ProblemError(404, "validation job not found", detail=_s(job_id))
        return job

    # -- PDF remediation pipeline (REQ-108) --------------------------------
    def remediation_plan(self, pdf: dict) -> dict:
        return {"plan": remediation.remediation_plan(pdf or {})}

    def remediate(self, data: dict) -> dict:
        result = remediation.remediate_pdf(data.get("file") or {},
                                           data.get("ops"))
        if result["remediated"]:
            self.bus.publish(EventEnvelope.make(
                EventType.DOCUMENT_REMEDIATED, source=self.source,
                dossier_id=_s(data.get("dossier_id")),
                data={"path": result["path"], "changes": result["changes"]}))
        return result

    def report(self, dossier_id: str, sequence: str) -> dict:
        run = self.repo.latest_run(_s(dossier_id), _s(sequence) or "0000")
        if not run:
            raise ProblemError(404, "No validation run for dossier/sequence",
                               detail=f"{dossier_id}/{sequence}")
        return run

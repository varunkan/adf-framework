#!/usr/bin/env python3
"""Unit tests for requirements_crew.py — the multi-agent requirements crew (offline,
complete + gather injected).

    python3 scripts/orch/test_requirements_crew.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requirements_crew as rc  # noqa: E402

_CANNED = {
    "plan": '{"queries":["ands ectd"],"categories":["functional","data"],"seed_urls":["https://hc.gc.ca"]}',
    "draft": '{"requirements":[{"id":"R1","shall":"store eCTD modules","acceptance":"GIVEN a submission WHEN saved THEN modules persist","source":"https://x"}]}',
    "verify": '{"pass":true,"gaps":[]}',
    "judge": '{"pass":false,"gaps":["missing Health Canada validation rule"]}',
    "questions": '{"questions":["Which eCTD modules: 1 only or 1-5?"],"improvements":["add an audit trail"]}',
    "synthesis": '{"problem_statement":"An ANDS submission portal","requirements":[{"id":"R1","shall":"store eCTD modules","acceptance":"...","source":"https://x"}],"assumptions":["single tenant"],"out_of_scope":["e-signatures"],"open_questions":[]}',
    "cross_check": '{"issues":["R1 acceptance is not fully testable"]}',
}


def fake_complete(prompt, role, system=None):
    return _CANNED.get(role, "{}")


def fake_gather(queries, urls):
    return [{"url": "https://hc.gc.ca/ectd", "title": "eCTD", "facts": "5 modules",
             "citations": ["https://hc.gc.ca/ectd"]}]


class CrewRun(unittest.TestCase):
    def _run(self, sources=None, write=False):
        specs = tempfile.mkdtemp() if write else None
        verdicts = os.path.join(specs, "judge-verdicts") if write else None
        return rc.run("pharma-demo", "build a Health Canada ANDS submission app",
                      sources=sources or [], specs_dir=specs, verdict_dir=verdicts,
                      complete=fake_complete, gather=fake_gather), specs

    def test_perspective_diverse_po_fails_if_either_flags(self):
        res, _ = self._run()
        # judge flagged a gap (rigor passed) → PO does NOT pass
        self.assertFalse(res["po"]["pass"])
        self.assertIn("missing Health Canada validation rule", res["po"]["gaps"])

    def test_open_questions_surface_for_user(self):
        res, _ = self._run()
        self.assertTrue(any("eCTD modules" in q for q in res["open_questions"]))
        self.assertIn("add an audit trail", res["improvements"])

    def test_adversarial_cross_check_runs(self):
        res, _ = self._run()
        self.assertTrue(any("testable" in i for i in res["cross_check"]))

    def test_sources_traceability(self):
        sources = [{"source": "uploaded-reqs.md", "requirements": "- SHALL track status"}]
        res, _ = self._run(sources=sources)
        self.assertIn("https://hc.gc.ca/ectd", res["sources"])   # research corpus
        self.assertIn("uploaded-reqs.md", res["sources"])         # user doc

    def test_writes_spec_artifacts(self):
        res, specs = self._run(write=True)
        for fn in ("spec.md", "problem-statement.md", "requirements-draft.json",
                   "po-validation.md"):
            self.assertTrue(os.path.isfile(os.path.join(specs, fn)), fn)
        spec = open(os.path.join(specs, "spec.md")).read()
        self.assertIn("Requirements (EARS)", spec)
        self.assertIn("eCTD modules", spec)
        # the PO verdict is written where the approval gate reads it
        verdict = open(os.path.join(specs, "judge-verdicts", "phase-2.md")).read()
        self.assertIn("REVISE", verdict)   # judge flagged a gap
        draft = json.load(open(os.path.join(specs, "requirements-draft.json")))
        self.assertEqual(draft["feature_id"], "pharma-demo")

    def test_no_garbage_orchestrator_leak(self):
        # the crew's spec must never contain the @orch-orchestrator chop the old engine produced
        _res, specs = self._run(write=True)
        spec = open(os.path.join(specs, "spec.md")).read()
        self.assertNotIn("@orch-orchestrator", spec)


if __name__ == "__main__":
    unittest.main()

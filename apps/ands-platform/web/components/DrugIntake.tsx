"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { IntakeAssessment } from "@/lib/types";
import { Term } from "./Term";

// The branching "Tell me about your drug" conversation — routes the pathway and
// steers a wrong-pathway filer off ANDS BEFORE they build an invalid submission.
export function DrugIntake({
  sessionId,
  initial,
  onAssessed,
}: {
  sessionId: string;
  initial?: IntakeAssessment | null;
  onAssessed?: (a: IntakeAssessment) => void;
}) {
  const [drug, setDrug] = useState("");
  const [type, setType] = useState("ANDS");
  const [newIndication, setNewIndication] = useState(false);
  const [dosageClass, setDosageClass] = useState("ir_solid_oral");
  const [busy, setBusy] = useState(false);
  const [assessment, setAssessment] = useState<IntakeAssessment | null>(
    initial ?? null
  );
  const [err, setErr] = useState("");

  async function assess() {
    setBusy(true);
    setErr("");
    try {
      const { assessment } = await api.intake(
        {
          drug_product: drug,
          submission_type: type,
          new_indication: newIndication,
          dosage_form_class: dosageClass,
          submission_date: "2026-06-30",
        },
        sessionId
      );
      setAssessment(assessment);
      onAssessed?.(assessment);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="teach" style={{ marginTop: 18 }}>
      <b>Tell me about your drug</b>
      <p className="mut" style={{ margin: "6px 0 2px" }}>
        I&apos;ll route you to the right pathway before you build anything.
      </p>
      <div className="field-row">
        <div>
          <label>What&apos;s your drug?</label>
          <input
            value={drug}
            onChange={(e) => setDrug(e.target.value)}
            placeholder="e.g. Drugazole 10 mg tablet"
          />
        </div>
        <div>
          <label>What are you filing?</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="ANDS">Generic of an approved brand (ANDS)</option>
            <option value="NDS">A brand-new drug (NDS)</option>
            <option value="SANDS">Change to an existing generic (SANDS)</option>
            <option value="SNDS">Change to an existing brand (SNDS)</option>
            <option value="DIN">DIN application</option>
          </select>
        </div>
      </div>
      <div className="field-row" style={{ marginTop: 4 }}>
        <div>
          <label>Dosage form</label>
          <select
            value={dosageClass}
            onChange={(e) => setDosageClass(e.target.value)}
          >
            <option value="ir_solid_oral">Immediate-release tablet/capsule</option>
            <option value="mr_solid_oral">Modified-release tablet/capsule</option>
            <option value="non_ir">Other / liquid / injectable</option>
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end" }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={newIndication}
              style={{ width: "auto" }}
              onChange={(e) => setNewIndication(e.target.checked)}
            />
            <span>It&apos;s for a new use the brand isn&apos;t approved for</span>
          </label>
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        <button onClick={assess} disabled={busy}>
          {busy ? "Checking…" : "Check my pathway"}
        </button>
      </div>

      {err && <div className="notice bad">{err}</div>}

      {assessment && (
        <div style={{ marginTop: 14 }}>
          {assessment.route.valid ? (
            <div className={`notice ${assessment.eligible_ands ? "ok" : "warn"}`}>
              <b>{assessment.route.label}</b> — {assessment.route.advice}
            </div>
          ) : (
            <div className="notice bad">{assessment.route.error}</div>
          )}
          {assessment.advisories.map((a) => (
            <div key={a.rule} className="notice warn">
              ⚠ {a.message}
            </div>
          ))}
          {assessment.route.ands_content_model && (
            <p className="mut" style={{ fontSize: 13 }}>
              Because this is an <Term k="ANDS" />, you won&apos;t need Module 4
              (animal studies). You&apos;ll prove <Term k="bioequivalence" /> to
              the <Term k="CRP">Canadian Reference Product</Term> instead.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

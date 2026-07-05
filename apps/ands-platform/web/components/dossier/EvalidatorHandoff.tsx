"use client";
// WS-VALIDATE (round-8 blocker, n=12): the eValidator PARITY / HANDOFF surface.
// Pinned to the validation/export success state, this answers the one question
// every regulatory-ops persona asked — "does a green result here mean my
// sequence would pass Health Canada's official eValidator?". The honest answer
// is NO. This surface EXTENDS the honesty disclaimers into an actionable next
// step; it never removes them.
//
// It renders (a) a persistent "you must still run HC eValidator before
// transmission" banner with a concrete next action, and (b) a parity-gap table
// stating, per rule family, whether HC's eValidator checks the same defect
// class (an OVERLAP, not a 1:1 numeric-parity claim) or has no counterpart.
// The parity map mirrors the backend ectd_validation.parity() family map; the
// rule ids are read live from the same rule catalogue the ValidationCard shows,
// so the table can never claim a rule the engine does not run.
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { dossierApi } from "@/lib/dossierApi";
import {
  ShieldAlert,
  ExternalLink,
  ClipboardCheck,
  CheckCircle2,
  XCircle,
  Copy,
  Paperclip,
  Download,
  PlayCircle,
} from "lucide-react";
import type {
  EvalidatorAttestation,
  SequenceValidationResult,
  ValidationCriteria,
  ValidationRule,
} from "@/lib/dossierTypes";

// family key -> whether HC's official eValidator checks the same class of
// defect + a plain note. Mirrors ectd_validation._FAMILY_PARITY. `covered`
// means OVERLAP (eValidator remains authoritative), NOT equivalence.
const FAMILY_PARITY: Record<string, { covered: boolean; note: string }> = {
  "1": {
    covered: true,
    note: "HC eValidator also checks leaf inventory integrity (href, checksum presence, MD5 format). Overlaps — eValidator remains authoritative.",
  },
  "2": {
    covered: true,
    note: "HC eValidator validates eCTD life-cycle operations (new/replace/append/delete) against the cumulative dossier.",
  },
  "3": {
    covered: true,
    note: "HC eValidator flags file/folder naming defects (case, spaces, module-folder placement).",
  },
  "4": {
    covered: true,
    note: "HC eValidator checks sequence numbering (four-digit, from 0000, contiguity).",
  },
  "5": {
    covered: true,
    note: "HC eValidator validates the index.xml backbone against the ICH eCTD DTD.",
  },
  "55": {
    covered: true,
    note: "HC eValidator validates the transmissible per-sequence <ectd:ectd> backbone (operation attrs, lifecycle back-pointers, live hrefs).",
  },
  "6": {
    covered: true,
    note: "HC eValidator validates the CA Module 1 v2.2 regional backbone (ca-regional.xml).",
  },
  "7": {
    covered: false,
    note: "ANDS Studio checks only the %PDF header and encryption. HC eValidator and your publisher verify full PDF/A-1 conformance — this tool does NOT.",
  },
  REP: {
    covered: false,
    note: "The Dossier ID is issued by Health Canada via the Regulatory Enrolment Process (REP); no validator mints or confirms it. An ANDS Studio guardrail, not an eValidator rule.",
  },
};

function familyKey(ruleId: string): string {
  if (ruleId.startsWith("CA-REP")) return "REP";
  const digits = ruleId.split("-")[2] || "";
  return digits.startsWith("55") ? "55" : digits.slice(0, 1);
}

interface ParityRow {
  family: string;
  ruleIds: string[];
  covered: boolean;
  note: string;
}

function buildParity(rules: ValidationRule[]): ParityRow[] {
  const byFamily: Record<string, ParityRow> = {};
  for (const r of rules) {
    const key = familyKey(r.rule_id);
    const p = FAMILY_PARITY[key];
    if (!p) continue;
    const row = (byFamily[r.family] ||= {
      family: r.family,
      ruleIds: [],
      covered: p.covered,
      note: p.note,
    });
    row.ruleIds.push(r.rule_id);
  }
  return Object.values(byFamily).sort((a, b) => a.family.localeCompare(b.family));
}

// ADOPT-EVALIDATOR: the recorded USER-ATTESTED external result. Shown as
// external evidence — the label makes the provenance unmistakable so a green
// chip here is never read as an ANDS Studio self-claim of eValidator parity.
function AttestationBadge({ a }: { a: EvalidatorAttestation }) {
  const pass = a.result === "pass";
  return (
    <div
      className={`notice ${pass ? "ok" : "bad"}`}
      role="status"
      style={{ marginTop: 10, fontSize: 12, display: "flex", gap: 8, alignItems: "flex-start" }}
    >
      {pass ? (
        <CheckCircle2 size={16} aria-hidden style={{ flexShrink: 0, marginTop: 1 }} />
      ) : (
        <XCircle size={16} aria-hidden style={{ flexShrink: 0, marginTop: 1 }} />
      )}
      <div>
        <b>
          {a.validator_name}
          {a.validator_version ? ` v${a.validator_version}` : ""}:{" "}
          {pass ? "PASSED" : "FAILED"}
        </b>{" "}
        <span className="mut">(external result)</span>
        <div className="mut" style={{ marginTop: 3 }}>
          Attested by {a.attested_by || "an unnamed user"}
          {a.validated_on ? ` · validated ${a.validated_on}` : ""}
          {a.report_filename && !a.report_doc_id
            ? ` · report: ${a.report_filename}`
            : ""}
        </div>
        {/* TIER2-PARITY-UX: the ACTUAL attached report file — downloadable
            evidence, not just a filename string. */}
        {a.report_doc_id && (
          <div style={{ marginTop: 4 }}>
            <a
              href={dossierApi.documentUrl(a.report_doc_id)}
              target="_blank"
              rel="noreferrer"
              className="chip"
              style={{ fontSize: 10, display: "inline-flex", gap: 4, alignItems: "center", textDecoration: "none" }}
            >
              <Download size={11} aria-hidden />
              {a.report_filename || "eValidator report"}
              {typeof a.report_size === "number"
                ? ` (${Math.max(1, Math.round(a.report_size / 1024))} KB)`
                : ""}
            </a>
            <span className="mut" style={{ marginLeft: 6, fontSize: 10 }}>
              attached report file
            </span>
          </div>
        )}
        {a.notes && (
          <div className="mut" style={{ marginTop: 3 }}>
            &ldquo;{a.notes}&rdquo;
          </div>
        )}
        <div className="mut" style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
          {a.disclaimer}
        </div>
      </div>
    </div>
  );
}

// The "I ran HC eValidator — attach the result" form. Records the real,
// user-supplied outcome. It never claims the tool IS eValidator; it records
// what the filer ran externally. A report FILE name/reference can be noted (we
// keep the bytes out of scope here — the filename/reference is the audit hook).
function AttestForm({
  dossierId,
  existing,
  onSaved,
}: {
  dossierId: string;
  existing: EvalidatorAttestation | null;
  onSaved: (a: EvalidatorAttestation) => void;
}) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<"pass" | "fail">(existing?.result || "pass");
  const [validatorName, setValidatorName] = useState(
    existing?.validator_name || "HC eValidator"
  );
  const [validatorVersion, setValidatorVersion] = useState(
    existing?.validator_version || ""
  );
  const [validatedOn, setValidatedOn] = useState(existing?.validated_on || "");
  const [notes, setNotes] = useState(existing?.notes || "");
  const [reportName, setReportName] = useState(
    existing?.report_doc_id ? "" : existing?.report_filename || ""
  );
  const [busy, setBusy] = useState(false);
  // TIER2-PARITY-UX: the ACTUAL report file to attach (bytes), not just a name.
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [attaching, setAttaching] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Attach the real eValidator report file (its own endpoint — stores the bytes
  // and links them on the attestation as downloadable evidence).
  async function attachReport() {
    if (!reportFile) return;
    setAttaching(true);
    try {
      const res = await dossierApi.attachEvalidatorReport(dossierId, reportFile);
      onSaved(res.attestation);
      toast.success("eValidator report file attached.");
      setReportFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      toast.error(`Could not attach the report file — ${String(e)}`);
    } finally {
      setAttaching(false);
    }
  }

  async function save() {
    if (!validatorName.trim()) {
      toast.error("Name the validator you ran (e.g. HC eValidator).");
      return;
    }
    setBusy(true);
    try {
      const saved = await dossierApi.setEvalidatorAttestation(dossierId, {
        result,
        validator_name: validatorName.trim(),
        validator_version: validatorVersion.trim() || undefined,
        validated_on: validatedOn.trim() || undefined,
        notes: notes.trim() || undefined,
        report_filename: reportName.trim() || undefined,
      });
      onSaved(saved);
      toast.success("External eValidator result recorded.");
      setOpen(false);
    } catch (e) {
      toast.error(`Could not record the result — ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        className="ghost"
        style={{ fontSize: 11, padding: "4px 8px", marginTop: 8, display: "inline-flex", gap: 5, alignItems: "center" }}
        onClick={() => setOpen(true)}
      >
        <ClipboardCheck size={12} aria-hidden />
        {existing ? "Update the recorded eValidator result" : "I ran HC eValidator — attach the result"}
      </button>
    );
  }

  return (
    <div className="notice" style={{ marginTop: 8, fontSize: 12 }}>
      <div style={{ fontWeight: 600, display: "flex", gap: 5, alignItems: "center" }}>
        <ClipboardCheck size={13} aria-hidden />
        Attach your external eValidator result
      </div>
      <div className="mut" style={{ fontSize: 11, marginTop: 3 }}>
        Record the REAL outcome of running Health Canada&apos;s eValidator (or your
        publisher&apos;s validator) on the exported package. ANDS Studio stores this
        as your external, user-attested evidence — it does not run or reproduce it.
      </div>
      <div className="field-row" style={{ marginTop: 6 }}>
        <div>
          <label htmlFor="att-result">Result</label>
          <select
            id="att-result"
            value={result}
            onChange={(e) => setResult(e.target.value as "pass" | "fail")}
          >
            <option value="pass">Passed</option>
            <option value="fail">Failed</option>
          </select>
        </div>
        <div>
          <label htmlFor="att-validator">Validator</label>
          <input
            id="att-validator"
            value={validatorName}
            onChange={(e) => setValidatorName(e.target.value)}
            placeholder="HC eValidator"
          />
        </div>
        <div>
          <label htmlFor="att-version">Version</label>
          <input
            id="att-version"
            value={validatorVersion}
            onChange={(e) => setValidatorVersion(e.target.value)}
            placeholder="5.3"
          />
        </div>
      </div>
      <div className="field-row" style={{ marginTop: 6 }}>
        <div>
          <label htmlFor="att-date">Date validated</label>
          <input
            id="att-date"
            type="date"
            value={validatedOn}
            onChange={(e) => setValidatedOn(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="att-report">Report reference note (optional)</label>
          <input
            id="att-report"
            value={reportName}
            onChange={(e) => setReportName(e.target.value)}
            placeholder="e123456-0000-evalidator.pdf"
          />
        </div>
      </div>
      {/* TIER2-PARITY-UX: attach the ACTUAL eValidator report file (bytes),
          the post-adopt ask. Stored as downloadable evidence on the record. */}
      <div style={{ marginTop: 8 }}>
        <label style={{ display: "flex", gap: 5, alignItems: "center" }}>
          <Paperclip size={12} aria-hidden />
          Attach the actual eValidator report file (recommended)
        </label>
        <div className="mut" style={{ fontSize: 11, margin: "2px 0 4px" }}>
          Attach the real report PDF/XML your validator produced — it is stored
          as downloadable evidence against this dossier, not just referenced by
          name.
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            ref={fileRef}
            type="file"
            aria-label="eValidator report file"
            accept=".pdf,.xml,.txt,.htm,.html,application/pdf,text/xml,application/xml"
            onChange={(e) => setReportFile(e.target.files?.[0] || null)}
            style={{ fontSize: 12 }}
          />
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "5px 9px", display: "inline-flex", gap: 5, alignItems: "center" }}
            onClick={attachReport}
            disabled={!reportFile || attaching}
          >
            <Paperclip size={12} aria-hidden />
            {attaching ? "Attaching…" : "Attach report file"}
          </button>
        </div>
        {existing?.report_doc_id && (
          <div className="mut" style={{ fontSize: 11, marginTop: 4, display: "flex", gap: 5, alignItems: "center" }}>
            <CheckCircle2 size={12} aria-hidden />
            A report file is already attached
            {existing.report_filename ? ` (${existing.report_filename})` : ""}.
          </div>
        )}
      </div>
      <label htmlFor="att-notes" style={{ marginTop: 8, display: "block" }}>Notes (optional)</label>
      <textarea
        id="att-notes"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        rows={2}
        placeholder="e.g. 0 errors, 0 warnings on sequence 0000."
      />
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button className="ghost" style={{ fontSize: 12, padding: "6px 10px" }} onClick={save} disabled={busy}>
          {busy ? "Recording…" : "Record result"}
        </button>
        <button className="ghost" style={{ fontSize: 12, padding: "6px 10px" }} onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// The shadow / parallel-run helper. Two honest capabilities:
//  (a) a SELF-SERVE structural check: point ANDS Studio's OWN structural
//      validator at a known-good prior sequence and see it pass too — a
//      confidence-building "it passes here too" (STRUCTURAL only, never an HC
//      eValidator parity claim; the disclaimer travels with the result).
//  (b) guidance to then run the real HC eValidator on that known-good baseline
//      first and compare, before trusting a new export on a live filing.
function ShadowRunHelper({ dossierId }: { dossierId?: string }) {
  const [open, setOpen] = useState(false);
  const [sequences, setSequences] = useState<string[]>([]);
  const [seq, setSeq] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SequenceValidationResult | null>(null);

  // load the dossier's sequences so the filer can pick a known-good one
  useEffect(() => {
    if (!open || !dossierId) return;
    let live = true;
    dossierApi
      .listSequences(dossierId)
      .then((s) => {
        if (!live) return;
        const nums = (s.sequences || []).map((x) => x.sequence);
        setSequences(nums);
        setSeq((cur) => cur || nums[0] || "0000");
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [open, dossierId]);

  async function runValidate() {
    if (!dossierId || !seq) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await dossierApi.validateSequence(dossierId, seq);
      setResult(r);
      if (r.passed) {
        toast.success(`Sequence ${r.sequence} passes ANDS Studio's structural checks.`);
      } else {
        toast(`Sequence ${r.sequence}: ${r.errors.length} structural finding(s).`);
      }
    } catch (e) {
      toast.error(`Could not validate the sequence — ${String(e)}`);
    } finally {
      setRunning(false);
    }
  }

  const steps = [
    "Pick a prior sequence you KNOW Health Canada already accepted (a known-good baseline).",
    "Run the self-serve structural check above on it — confirm ANDS Studio's structural validator passes it too.",
    "Then export that sequence and run it through HC eValidator (or your publisher's validator) to confirm the real, authoritative result.",
    "Now export your NEW sequence and validate it the same way. Compare the findings against the known-good run.",
    "Attach the new sequence's result (and the report file) above so the pass/fail is recorded against this dossier.",
  ];
  const copyText = "eValidator shadow / parallel-run checklist:\n" +
    steps.map((s, i) => `${i + 1}. ${s}`).join("\n");
  return (
    <div style={{ marginTop: 8 }}>
      <button
        className="ghost"
        style={{ fontSize: 11, padding: "2px 6px" }}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide known-good sequence check" : "Validate a known-good sequence (build trust first)"}
      </button>
      {open && (
        <div className="notice" style={{ marginTop: 6, fontSize: 11 }}>
          <div className="mut" style={{ marginBottom: 4 }}>
            Prove parity to yourself: run ANDS Studio&apos;s OWN structural checks on
            a sequence you already know Health Canada accepted, and confirm it
            passes here too — before trusting a new export on a live filing.
          </div>
          {/* SELF-SERVE structural validate on a chosen sequence */}
          {dossierId && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", margin: "6px 0" }}>
              <label htmlFor="known-good-seq" className="mut">
                Known-good sequence
              </label>
              <select
                id="known-good-seq"
                value={seq}
                onChange={(e) => setSeq(e.target.value)}
                style={{ fontSize: 11, padding: "2px 4px" }}
              >
                {(sequences.length ? sequences : ["0000"]).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <button
                className="ghost"
                style={{ fontSize: 11, padding: "3px 8px", display: "inline-flex", gap: 5, alignItems: "center" }}
                onClick={runValidate}
                disabled={running || !seq}
              >
                <PlayCircle size={12} aria-hidden />
                {running ? "Checking…" : "Run structural check"}
              </button>
            </div>
          )}
          {result && (
            <div
              className={`notice ${result.passed ? "ok" : "bad"}`}
              role="status"
              style={{ fontSize: 11, margin: "4px 0" }}
            >
              <b>
                Sequence {result.sequence}:{" "}
                {result.passed
                  ? "passes ANDS Studio's structural checks"
                  : `${result.errors.length} structural finding(s)`}
              </b>
              {!result.passed && (
                <ul style={{ margin: "3px 0 0 16px", padding: 0 }}>
                  {result.errors.slice(0, 6).map((e, i) => (
                    <li key={i} className="mut">
                      {e.rule_id ? `${e.rule_id}: ` : ""}
                      {e.message}
                    </li>
                  ))}
                </ul>
              )}
              <div className="mut" style={{ marginTop: 4, fontSize: 10, opacity: 0.9 }}>
                Structural check only — this is NOT Health Canada&apos;s official
                eValidator and does not claim parity with it. Run HC eValidator
                (or your publisher&apos;s) before you transmit.
              </div>
            </div>
          )}
          <ol style={{ margin: "6px 0 0 16px", padding: 0 }}>
            {steps.map((s) => (
              <li key={s} className="mut" style={{ marginTop: 2 }}>
                {s}
              </li>
            ))}
          </ol>
          <button
            className="ghost"
            style={{ fontSize: 11, padding: "3px 7px", marginTop: 6, display: "inline-flex", gap: 5, alignItems: "center" }}
            onClick={() => {
              navigator.clipboard?.writeText(copyText).then(
                () => toast.success("Checklist copied."),
                () => toast.error("Could not copy to clipboard.")
              );
            }}
          >
            <Copy size={11} aria-hidden />
            Copy checklist
          </button>
        </div>
      )}
    </div>
  );
}

// The persistent banner — always shown, never collapsible: this is the safety
// next-step, not a nice-to-have. Extends the honesty disclaimer into an action.
export function EvalidatorBanner({ criteria }: { criteria?: ValidationCriteria }) {
  return (
    <div
      className="notice"
      role="status"
      style={{
        marginTop: 10,
        fontSize: 12,
        display: "flex",
        gap: 8,
        alignItems: "flex-start",
      }}
    >
      <ShieldAlert size={16} aria-hidden style={{ flexShrink: 0, marginTop: 1 }} />
      <div>
        <b>You must still run Health Canada&apos;s official eValidator before transmission.</b>{" "}
        A clean result here means the sequence is structurally plausible — it does{" "}
        <b>not</b> mean it will pass HC&apos;s eValidator or be accepted on screening.
        <div className="mut" style={{ marginTop: 4 }}>
          Next step: export the eCTD package, validate it in HC&apos;s eValidator (or
          your publisher&apos;s validator — e.g. Lorenz eValidator / docuBridge),
          resolve any findings, then upload through CESG WebTrader.
        </div>
        {criteria?.synced && (
          <div className="mut" style={{ marginTop: 4, fontSize: 11 }}>
            Ruleset: {criteria.name} v{criteria.version} · synced {criteria.synced}
          </div>
        )}
      </div>
    </div>
  );
}

// The full handoff surface: banner + attest-result flow + shadow-run helper +
// collapsible parity-gap table. Intended to be pinned to the export/validation
// success state. Pass `dossierId` to enable the "attach your real eValidator
// result" flow (the ADOPT-EVALIDATOR loop-closer). `attestation` seeds the
// currently-recorded external result so the badge renders without a refetch.
export function EvalidatorHandoff({
  criteria,
  dossierId,
  attestation,
}: {
  criteria?: ValidationCriteria;
  dossierId?: string;
  attestation?: EvalidatorAttestation | null;
}) {
  const [rules, setRules] = useState<ValidationRule[] | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const [att, setAtt] = useState<EvalidatorAttestation | null>(attestation ?? null);

  useEffect(() => {
    let live = true;
    dossierApi
      .validationRules()
      .then((c) => {
        if (live) setRules(c.rules);
      })
      .catch((e) => {
        if (live) setErr(String(e));
      });
    return () => {
      live = false;
    };
  }, []);

  // keep in sync when the parent's validation result carries a fresher one
  useEffect(() => {
    if (attestation !== undefined) setAtt(attestation);
  }, [attestation]);

  // if the parent didn't seed an attestation, fetch the current one once we
  // have a dossier id (so the badge shows a previously-recorded result).
  useEffect(() => {
    if (!dossierId || attestation !== undefined) return;
    let live = true;
    dossierApi
      .getEvalidatorAttestation(dossierId)
      .then((r) => {
        if (live) setAtt(r.attestation);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [dossierId, attestation]);

  const parity = rules ? buildParity(rules) : [];
  const notCovered = parity.filter((p) => !p.covered).length;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, display: "flex", gap: 6, alignItems: "center" }}>
        <ShieldAlert size={14} aria-hidden />
        eValidator handoff
      </div>
      <EvalidatorBanner criteria={criteria} />
      {att && <AttestationBadge a={att} />}
      {dossierId && (
        <AttestForm dossierId={dossierId} existing={att} onSaved={setAtt} />
      )}
      <ShadowRunHelper dossierId={dossierId} />
      {err && <div className="notice bad" style={{ marginTop: 6 }}>{err}</div>}
      {rules && (
        <>
          <button
            className="ghost"
            style={{ fontSize: 11, padding: "2px 6px", marginTop: 6 }}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open
              ? "Hide parity-gap table"
              : `Parity-gap table (which rules overlap HC eValidator${
                  notCovered ? `, ${notCovered} family without a counterpart` : ""
                })`}
          </button>
          {open && (
            <div style={{ marginTop: 6, fontSize: 11 }}>
              <div className="mut" style={{ marginBottom: 6 }}>
                &ldquo;Overlaps&rdquo; means HC&apos;s eValidator checks the same class of
                defect — it is <b>not</b> a claim of 1:1 numeric parity. Rows marked
                &ldquo;no HC counterpart&rdquo; are ANDS Studio convenience checks only.
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 11 }}>
                  <thead>
                    <tr style={{ textAlign: "left" }}>
                      <th style={{ padding: "3px 6px" }}>Rule family</th>
                      <th style={{ padding: "3px 6px" }}>HC eValidator</th>
                      <th style={{ padding: "3px 6px" }}>Rule ids</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parity.map((p) => (
                      <tr key={p.family} style={{ borderTop: "1px solid var(--hairline, rgba(128,128,128,0.2))" }}>
                        <td style={{ padding: "4px 6px", verticalAlign: "top" }}>
                          <div style={{ fontWeight: 600 }}>{p.family}</div>
                          <div className="mut">{p.note}</div>
                        </td>
                        <td style={{ padding: "4px 6px", verticalAlign: "top", whiteSpace: "nowrap" }}>
                          <span className={`chip ${p.covered ? "" : "bad"}`} style={{ fontSize: 9, padding: "0 5px" }}>
                            {p.covered ? "overlaps" : "no HC counterpart"}
                          </span>
                        </td>
                        <td style={{ padding: "4px 6px", verticalAlign: "top" }}>
                          {p.ruleIds.map((id) => (
                            <code key={id} style={{ fontSize: 9, opacity: 0.85, marginRight: 4 }}>
                              {id}
                            </code>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mut" style={{ marginTop: 6, display: "flex", gap: 4, alignItems: "center" }}>
                <ExternalLink size={11} aria-hidden />
                HC eValidator and the eCTD validation criteria are published at
                canada.ca (Health Canada — &ldquo;Preparation of Regulatory Activities in
                eCTD Format&rdquo;).
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

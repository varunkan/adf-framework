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
import { useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { ShieldAlert, ExternalLink } from "lucide-react";
import type { ValidationCriteria, ValidationRule } from "@/lib/dossierTypes";

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

// The full handoff surface: banner + collapsible parity-gap table. Intended to
// be pinned to the export/validation success state.
export function EvalidatorHandoff({ criteria }: { criteria?: ValidationCriteria }) {
  const [rules, setRules] = useState<ValidationRule[] | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);

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

  const parity = rules ? buildParity(rules) : [];
  const notCovered = parity.filter((p) => !p.covered).length;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, display: "flex", gap: 6, alignItems: "center" }}>
        <ShieldAlert size={14} aria-hidden />
        eValidator handoff
      </div>
      <EvalidatorBanner criteria={criteria} />
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

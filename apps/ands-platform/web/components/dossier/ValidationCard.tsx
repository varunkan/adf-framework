"use client";
import { useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { Disclosure } from "../Disclosure";
import { RuleCatalogue } from "./RuleCatalogue";
import { EctdPrimer } from "./EctdPrimer";
import { EvalidatorHandoff } from "./EvalidatorHandoff";
import {
  groupPdfaWarnings,
  pdfaLeafItems,
  type PdfaAdvisoryGroup,
} from "@/lib/pdfaAdvisories";
import type {
  ValidationCriteria,
  ValidationFinding,
  ValidationResult,
} from "@/lib/dossierTypes";

// One finding, labeled with its rule id, severity, the failing leaf/file and
// the message. Regulatory-ops people reason in rule ids, not prose.
function Row({ f, warn }: { f: ValidationFinding; warn?: boolean }) {
  return (
    <div
      className="mut"
      style={{
        fontSize: 12.5,
        marginTop: 6,
        display: "flex",
        gap: 8,
        alignItems: "baseline",
      }}
    >
      <code style={{ fontSize: 11, opacity: 0.85, whiteSpace: "nowrap" }}>
        {f.rule_id || (warn ? "CA-W" : "CA-E")}
      </code>
      <span
        className={`chip ${warn ? "" : "bad"}`}
        style={{ fontSize: 10, padding: "0 6px", textTransform: "uppercase" }}
      >
        {warn ? "warning" : "error"}
      </span>
      <span>
        {f.leaf ? (
          <code style={{ fontSize: 11, opacity: 0.8 }}>{f.leaf}: </code>
        ) : null}
        {f.message}
      </span>
    </div>
  );
}

// FIX-PDFA-NOISE — one COLLAPSED PDF/A advisory: the per-rule summary
// ("PDF/A-1b advisory CA-W-7006 (XMP metadata) — 9 leaves"), rendered in a
// clearly SECONDARY / muted style so it never reads as a hard error, with the
// affected leaves tucked behind an expander. The advisory nature (does not
// block) is stated on the face; the leaf list is one click away.
function PdfaAdvisoryRow({ g }: { g: PdfaAdvisoryGroup }) {
  const [open, setOpen] = useState(false);
  const n = g.count;
  return (
    <div
      className="mut"
      style={{
        fontSize: 12,
        marginTop: 6,
        paddingLeft: 8,
        borderLeft: "2px solid var(--warn)",
        opacity: 0.92,
      }}
    >
      <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
        <code style={{ fontSize: 10, opacity: 0.85, whiteSpace: "nowrap" }}>
          {g.rule_id}
        </code>
        <span
          className="chip"
          style={{ fontSize: 9, padding: "0 5px", textTransform: "uppercase" }}
        >
          advisory
        </span>
        <span>
          PDF/A-1b advisory ({g.label}) —{" "}
          <b>
            {n} leaf{n === 1 ? "" : "s"}
          </b>{" "}
          <span style={{ opacity: 0.8 }}>· advisory only, does not block</span>
        </span>
        <button
          className="ghost"
          style={{ fontSize: 10, padding: "1px 6px" }}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open
            ? "Hide itemized list"
            : `Review ${n} item${n === 1 ? "" : "s"}`}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: 4 }}>
          <div style={{ fontSize: 10, opacity: 0.75, marginBottom: 4 }}>
            {g.message}
          </div>
          {/* POLISH-PDFA-ITEMIZE: one reviewable ROW per affected leaf so a
              publisher can clear or accept EACH one, not just trust the count.
              Each row states the leaf id, the specific marker it lacks, and the
              plain non-blocking note. */}
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {pdfaLeafItems(g).map((item, i) => (
              <li
                key={i}
                style={{
                  marginTop: i === 0 ? 0 : 4,
                  paddingTop: i === 0 ? 0 : 4,
                  borderTop: i === 0 ? "none" : "1px solid var(--line)",
                  display: "flex",
                  gap: 6,
                  alignItems: "baseline",
                  flexWrap: "wrap",
                }}
              >
                <code
                  style={{ fontSize: 10, opacity: 0.9, whiteSpace: "nowrap" }}
                >
                  {item.leaf || "(document)"}
                </code>
                <span style={{ fontSize: 11 }}>
                  lacks <b>{item.marker}</b>
                </span>
                <span
                  className="mut"
                  style={{ fontSize: 10, opacity: 0.7, whiteSpace: "nowrap" }}
                >
                  · {item.note}
                </span>
              </li>
            ))}
          </ul>
          <div style={{ fontSize: 10, opacity: 0.7, marginTop: 6 }}>
            Generated leaves are marked PDF/A post-generation, so residual
            advisories are typically on <b>uploaded</b> plain PDFs. A plain,
            transmissible PDF is not a defect merely for lacking PDF/A markers —
            your publisher can clear or accept each item above.
          </div>
        </div>
      )}
    </div>
  );
}

// The honest coverage statement: names + versions the criteria, states the
// disclaimer, and expands into what IS and — explicitly — what is NOT checked.
function CriteriaHeader({ criteria }: { criteria?: ValidationCriteria }) {
  const [open, setOpen] = useState(false);
  const [showRules, setShowRules] = useState(false);
  if (!criteria) {
    return (
      <div className="mut" style={{ fontSize: 12, marginTop: 6 }}>
        Draft completeness check — checks presence and format only, not
        scientific adequacy or full eCTD technical validation. Run Health
        Canada&apos;s eValidator before you transmit.
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8 }}>
      {/* R6-B: the profile NAME + VERSION headline is on the FACE (not hidden
          in the expander), with the honest "structural; not HC eValidator"
          qualifier inline so the green result is never mistaken for the
          official validator. */}
      <div style={{ fontSize: 13, fontWeight: 600 }}>
        {criteria.name}{" "}
        <span className="mut" style={{ fontWeight: 400 }}>
          v{criteria.version}
        </span>{" "}
        <span className="mut" style={{ fontWeight: 400 }}>
          (structural; not HC eValidator)
        </span>
      </div>
      {/* WS-VALIDATE: the ruleset SYNC DATE travels on the face so provenance
          (name + version + when it was last reconciled to HC criteria) is
          legible without opening the expander or an exported report. */}
      {criteria.synced && (
        <div className="mut" style={{ fontSize: 12, marginTop: 3 }}>
          Ruleset synced: {criteria.synced}
        </div>
      )}
      <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
        {criteria.disclaimer}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          className="ghost"
          style={{ fontSize: 12, padding: "3px 8px", marginTop: 8 }}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Hide coverage" : "What this does / does NOT check"}
        </button>
        <button
          className="ghost"
          style={{ fontSize: 12, padding: "3px 8px", marginTop: 8 }}
          aria-expanded={showRules}
          onClick={() => setShowRules((o) => !o)}
        >
          {showRules ? "Hide rule catalogue" : "Rule catalogue (CA-E/CA-W ids)"}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <div className="mut" style={{ opacity: 0.9 }}>
            Modeled on: {criteria.modeled_on}
          </div>
          <div style={{ marginTop: 10, fontWeight: 600 }}>Checks (structure &amp; format):</div>
          <ul style={{ margin: "4px 0 0 18px", padding: 0, lineHeight: 1.55 }}>
            {criteria.coverage.checked.map((c) => (
              <li key={c} className="mut">
                {c}
              </li>
            ))}
          </ul>
          <div style={{ marginTop: 12, fontWeight: 600 }}>
            Does NOT check:
          </div>
          <ul style={{ margin: "4px 0 0 18px", padding: 0, lineHeight: 1.55 }}>
            {criteria.coverage.not_checked.map((c) => (
              <li key={c} className="mut">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
      {showRules && (
        <div style={{ marginTop: 8 }}>
          <RuleCatalogue criteria={criteria} />
        </div>
      )}
    </div>
  );
}

// Client-side export of findings + criteria — no backend. Triggers a Blob
// download in CSV or JSON.
function downloadBlob(name: string, mime: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvCell(v: unknown): string {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// WS-VALIDATE: the ruleset provenance (name + version + synced date) must be
// STAMPED into every exported report so it travels with the evidence, not just
// live in the UI. One helper renders that stamp as a human line reused across
// CSV/JSON/PDF exports.
function criteriaStamp(c?: ValidationCriteria): string {
  if (!c) return "Ruleset: (unnamed structural check)";
  return (
    `Ruleset: ${c.name} v${c.version}` +
    (c.synced ? ` · synced ${c.synced}` : "") +
    " · structural/technical only — NOT Health Canada's official eValidator"
  );
}

function report(v: ValidationResult, dossierId: string) {
  const rows: { severity: string; finding: ValidationFinding }[] = [
    ...v.errors.map((finding) => ({ severity: "error", finding })),
    ...v.warnings.map((finding) => ({ severity: "warning", finding })),
  ];
  const generatedAt = new Date().toISOString();
  const c = v.criteria;
  // CSV: stamp the ruleset provenance into leading comment lines (# …) so the
  // criteria name/version/sync date travels with the file even when opened in a
  // spreadsheet. Then the normal header row + findings.
  const csv = [
    `# ${criteriaStamp(c)}`,
    `# Dossier: ${dossierId} · generated ${generatedAt} · result: ${
      v.passed ? "no structural issues" : `${v.errors.length} error(s)`
    }`,
    "# You must still run HC eValidator before transmission.",
    ["severity", "rule_id", "rule", "leaf", "message"].join(","),
    ...rows.map((r) =>
      [
        r.severity,
        r.finding.rule_id || "",
        r.finding.rule,
        r.finding.leaf || "",
        r.finding.message,
      ]
        .map(csvCell)
        .join(",")
    ),
  ].join("\n");
  const json = JSON.stringify(
    {
      dossier_id: dossierId,
      generated_at: generatedAt,
      passed: v.passed,
      // WS-VALIDATE: explicit provenance block so the ruleset name/version/sync
      // date is machine-readable at the top of the report, in addition to the
      // full criteria object.
      ruleset: c
        ? { name: c.name, version: c.version, synced: c.synced || null }
        : null,
      criteria: c || null,
      note:
        "Structural/format completeness check only — NOT Health Canada " +
        "review and NOT full eCTD technical validation. You must still run " +
        "HC eValidator before transmission.",
      errors: v.errors,
      warnings: v.warnings,
    },
    null,
    2
  );
  return { csv, json };
}

// WS-VALIDATE: a print-friendly PDF export. We do NOT claim PDF/A conformance —
// this opens a stamped, print-ready report the filer can "Save as PDF" from the
// browser print dialog. The ruleset name/version/synced date is stamped in the
// header so provenance travels with the printed evidence.
function reportPdf(v: ValidationResult, dossierId: string) {
  const c = v.criteria;
  const generatedAt = new Date().toISOString();
  const rows = [
    ...v.errors.map((f) => ({ severity: "error", f })),
    ...v.warnings.map((f) => ({ severity: "warning", f })),
  ];
  const esc = (s: unknown) =>
    String(s == null ? "" : s).replace(
      /[&<>]/g,
      (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch] as string)
    );
  const body = rows.length
    ? rows
        .map(
          (r) =>
            `<tr><td>${esc(r.severity)}</td><td><code>${esc(
              r.f.rule_id || ""
            )}</code></td><td><code>${esc(r.f.leaf || "")}</code></td><td>${esc(
              r.f.message
            )}</td></tr>`
        )
        .join("")
    : `<tr><td colspan="4">No presence/format issues found. This does not confirm scientific adequacy or full eCTD validity.</td></tr>`;
  const html =
    `<!doctype html><html><head><meta charset="utf-8"><title>` +
    `${esc(dossierId)} — completeness check</title><style>` +
    `body{font:13px system-ui,sans-serif;padding:24px;color:#111}` +
    `h1{font-size:18px;margin:0 0 4px}` +
    `.stamp{font-size:11px;color:#555;margin:2px 0}` +
    `.banner{border:1px solid #b45309;background:#fffbeb;color:#7c2d12;` +
    `padding:8px 10px;border-radius:6px;margin:12px 0;font-size:12px}` +
    `table{border-collapse:collapse;width:100%;margin-top:12px;font-size:12px}` +
    `th,td{border:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}` +
    `code{font-size:11px}` +
    `@media print{button{display:none}}` +
    `</style></head><body>` +
    `<h1>eCTD structural completeness check</h1>` +
    `<div class="stamp">${esc(criteriaStamp(c))}</div>` +
    `<div class="stamp">Dossier: ${esc(dossierId)} · generated ${esc(
      generatedAt
    )} · result: ${
      v.passed ? "no structural issues" : `${v.errors.length} error(s)`
    }</div>` +
    (c?.modeled_on
      ? `<div class="stamp">Modeled on: ${esc(c.modeled_on)}</div>`
      : "") +
    `<div class="banner"><b>You must still run Health Canada's official ` +
    `eValidator before transmission.</b> A clean result here means the sequence ` +
    `is structurally plausible — it does NOT mean it will pass HC's eValidator ` +
    `or be accepted on screening. This is NOT full eCTD technical validation ` +
    `and does NOT claim PDF/A conformance.</div>` +
    `<table><thead><tr><th>Severity</th><th>Rule id</th><th>Leaf/file</th>` +
    `<th>Message</th></tr></thead><tbody>${body}</tbody></table>` +
    `<button onclick="window.print()">Print / Save as PDF</button>` +
    `</body></html>`;
  const w = window.open("", "_blank");
  if (w) {
    w.document.write(html);
    w.document.close();
    w.focus();
  }
}

// Draft completeness check — the structural/format check run from content
// state, with a button to run the fuller technical check (incl. the PDF header
// / encryption check on the stored bytes). This is NOT a Health Canada review
// and does NOT assert scientific adequacy or full eCTD technical validation.
export function ValidationCard({
  dossierId,
  structural,
}: {
  dossierId: string;
  structural: ValidationResult;
}) {
  const [full, setFull] = useState<ValidationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const v = full || structural;
  const errs = showAll ? v.errors : v.errors.slice(0, 5);
  // FIX-PDFA-NOISE: collapse the repetitive PDF/A-1b advisories (CA-W-70xx) into
  // a per-rule summary so 10-12 near-identical yellow rows read as the 2-4
  // grouped advisories they actually are. Non-PDF/A warnings stay individual.
  const { pdfaGroups, other: otherWarnings } = groupPdfaWarnings(v.warnings);
  const shownOther = showAll ? otherWarnings : otherWarnings.slice(0, 3);

  async function run() {
    setBusy(true);
    try {
      setFull(await dossierApi.validate(dossierId));
    } finally {
      setBusy(false);
    }
  }

  const { csv, json } = report(v, dossierId);
  const stamp = `${dossierId}-completeness-check`;

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Draft completeness check</h3>
        <span
          style={{ marginLeft: "auto" }}
          className={`ready-status ${v.passed ? "READY" : "BLOCKED"}`}
        >
          {v.passed
            ? "● NO STRUCTURAL ISSUES"
            : `● ${v.errors.length} issue(s)`}
        </span>
      </div>

      <CriteriaHeader criteria={v.criteria} />
      <EctdPrimer compact />

      <div style={{ marginTop: 14 }}>
        {errs.map((e, i) => (
          <Row key={i} f={e} />
        ))}
        {v.errors.length > 5 && (
          <button
            className="ghost"
            style={{ fontSize: 11, padding: "2px 6px", marginTop: 4 }}
            onClick={() => setShowAll((s) => !s)}
          >
            {showAll ? "Show fewer" : `Show all ${v.errors.length} findings`}
          </button>
        )}
        {/* FIX-PDFA-NOISE: the PDF/A advisories are grouped per rule and shown
            in full (there are only ever 2-4), each collapsing its affected
            leaves behind an expander. They are visually SECONDARY (muted, warn
            left-rule, "advisory" chip) so they never read as hard errors. */}
        {pdfaGroups.map((g) => (
          <PdfaAdvisoryRow key={g.rule_id} g={g} />
        ))}
        {shownOther.map((w, i) => (
          <Row key={`w${i}`} f={w} warn />
        ))}
        {otherWarnings.length > 3 && (
          <button
            className="ghost"
            style={{ fontSize: 11, padding: "2px 6px", marginTop: 4 }}
            onClick={() => setShowAll((s) => !s)}
          >
            {showAll
              ? "Show fewer warnings"
              : `+${otherWarnings.length - 3} more warning(s)`}
          </button>
        )}
        {v.errors.length === 0 && v.warnings.length === 0 && (
          <div className="mut" style={{ fontSize: 12 }}>
            No presence/format issues found. This does not confirm scientific
            adequacy or full eCTD validity — run eValidator before transmission.
          </div>
        )}
      </div>

      {/* WS-VALIDATE (round-8 blocker, n=12): the eValidator handoff surface is
          PINNED to the validation success state (no structural errors) — the
          exact point a filer might mistake a green result for an eValidator
          pass. It carries the persistent "run HC eValidator before transmission"
          banner + the parity-gap table, extending (never removing) the honesty
          disclaimers into an actionable next step. */}
      {v.passed && (
        <EvalidatorHandoff
          criteria={v.criteria}
          dossierId={dossierId}
          attestation={v.external_attestation}
          cleared={v.evalidator_cleared}
        />
      )}

      {/* Round-6 WS-A (density reduction): the pass/fail result + findings above
          are the GATING signal — always visible. The extra technical sub-check,
          report exports and the coverage footnote are non-gating detail, so they
          collapse behind a quiet expander (still one click away). */}
      <Disclosure
        showLabel="Technical check & report"
        hideLabel="Hide technical check & report"
        summary={
          <span>
            Run PDF header / encryption / PDF/A-1b structural sub-check · export
            CSV/JSON
          </span>
        }
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={run}
            disabled={busy}
          >
            {busy
              ? "Checking…"
              : "Run technical check (PDF header / encryption / PDF/A-1b)"}
          </button>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={() =>
              downloadBlob(`${stamp}.csv`, "text/csv;charset=utf-8", csv)
            }
          >
            Download report (CSV)
          </button>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={() =>
              downloadBlob(`${stamp}.json`, "application/json", json)
            }
          >
            Download report (JSON)
          </button>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={() => reportPdf(v, dossierId)}
            title="Opens a print-ready, ruleset-stamped report — use your browser's Save as PDF. Not a PDF/A conformance claim."
          >
            Download report (PDF)
          </button>
        </div>

        <div className="mut" style={{ fontSize: 11.5, marginTop: 10, lineHeight: 1.55 }}>
          Findings carry structural-rule ids (CA-E-…/CA-W-…) covering leaf
          integrity, lifecycle legality, naming, sequence numbering, XML backbone
          and the document payload: PDF header, encryption, and PDF/A-1b{" "}
          <b>structural</b> markers (XMP pdfaid packet, OutputIntent, PDF-1.4
          base version, and prohibited active content). This is a
          presence/format completeness check — <b>not</b> a Health Canada review,{" "}
          <b>not</b> full eCTD technical validation, and <b>not</b> full ISO
          19005-1 (PDF/A-1) conformance validation. Where a checksum is shown it
          is document control (md5), not validation.
        </div>
      </Disclosure>
    </div>
  );
}

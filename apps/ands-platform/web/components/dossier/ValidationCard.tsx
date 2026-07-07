"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { HelpCircle } from "lucide-react";
import { dossierApi } from "@/lib/dossierApi";
import { auth } from "@/lib/auth";
import { Disclosure } from "../Disclosure";
import { RuleCatalogue } from "./RuleCatalogue";
import { EctdPrimer } from "./EctdPrimer";
import { ChipLegend } from "./ChipLegend";
import { ValidationTour, useFirstRunTour } from "./ValidationTour";
import {
  EvalidatorHandoff,
  buildParity,
  type ParityRow,
} from "./EvalidatorHandoff";
import {
  groupPdfaWarnings,
  pdfaLeafItems,
  type PdfaAdvisoryGroup,
} from "@/lib/pdfaAdvisories";
import {
  AUTO_PLACEMENT_STATEMENT,
  RULESET_PINNING_LIMIT,
  SPONSOR_SCOPE_STATEMENT,
  criteriaChecksumNote,
  criteriaStaleness,
  indexRules,
  moduleOfLeaf,
  modulePath,
  ruleForFinding,
  ruleHowToFix,
} from "./validationExtras";
import type {
  CurrentView,
  ValidationCriteria,
  ValidationFinding,
  ValidationResult,
  ValidationRule,
} from "@/lib/dossierTypes";

// ROUND9-VALIDATE item 13 (cro_pm): per-finding "Assign as task" — a real
// task in the collaboration store (same POST /api/collab/tasks contract the
// CollabPane uses), so it surfaces in the Collaboration pane + portfolio
// rollup. HONEST label: it creates a dossier task; it does not add fields to
// the immutable finding itself.
function AssignTask({
  dossierId,
  f,
}: {
  dossierId: string;
  f: ValidationFinding;
}) {
  const [open, setOpen] = useState(false);
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(false);

  function openForm() {
    setOpen(true);
    if (!assignee) {
      auth
        .me()
        .then((p) => setAssignee((a) => a || p.email))
        .catch(() => {});
    }
  }

  async function create() {
    if (!assignee.trim()) return;
    setBusy(true);
    try {
      const me = await auth.me().catch(() => null);
      const title = `[${f.rule_id || f.rule}] ${
        f.leaf ? `${f.leaf}: ` : ""
      }${f.message}`.slice(0, 200);
      const res = await fetch("/api/collab/tasks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          title,
          assignee: assignee.trim(),
          due_date: due || null,
          created_by: me?.email || assignee.trim(),
          target_type: "dossier",
          target_id: dossierId,
          dossier_id: dossierId,
        }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setCreated(true);
      setOpen(false);
      toast.success(
        "Task created — it appears in this dossier's Collaboration pane."
      );
    } catch (e) {
      toast.error(`Could not create the task — ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <span className="chip" style={{ fontSize: 9, padding: "0 6px" }}>
        task created
      </span>
    );
  }
  if (!open) {
    return (
      <button
        className="ghost"
        style={{ fontSize: 10, padding: "1px 6px" }}
        onClick={openForm}
        title="Creates a dossier task (assignee + target date) in the Collaboration pane for this finding"
      >
        Assign as task
      </button>
    );
  }
  return (
    <span
      style={{ display: "inline-flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}
    >
      <input
        aria-label="Task assignee"
        placeholder="assignee@company.com"
        value={assignee}
        onChange={(e) => setAssignee(e.target.value)}
        style={{ fontSize: 10, padding: "2px 5px", width: 150 }}
      />
      <input
        aria-label="Target date"
        type="date"
        value={due}
        onChange={(e) => setDue(e.target.value)}
        style={{ fontSize: 10, padding: "2px 5px" }}
      />
      <button
        className="ghost"
        style={{ fontSize: 10, padding: "1px 6px" }}
        onClick={create}
        disabled={busy || !assignee.trim()}
      >
        {busy ? "Creating…" : "Create task"}
      </button>
      <button
        className="ghost"
        style={{ fontSize: 10, padding: "1px 6px" }}
        onClick={() => setOpen(false)}
        disabled={busy}
      >
        Cancel
      </button>
    </span>
  );
}

// One finding, labeled with its rule id, severity, the failing leaf/file and
// the message. Regulatory-ops people reason in rule ids, not prose.
// ROUND9-VALIDATE item 14 (ra_junior): each row also names the FIX — a
// one-line how-to-fix hint (live from the rule catalogue) and a "Fix this"
// deep link to the module page that owns the failing leaf (omitted when the
// owning module cannot be resolved — never a wrong link).
function Row({
  f,
  warn,
  dossierId,
  hint,
  fixHref,
}: {
  f: ValidationFinding;
  warn?: boolean;
  dossierId?: string;
  hint?: string;
  fixHref?: string | null;
}) {
  return (
    <div className="mut" style={{ fontSize: 12.5, marginTop: 6 }}>
      <div
        style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}
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
        {fixHref && (
          <Link
            href={fixHref}
            className="chip"
            style={{ fontSize: 10, padding: "0 6px", textDecoration: "none" }}
            title="Open the module page that owns this failing leaf"
          >
            Fix this →
          </Link>
        )}
        {!warn && dossierId && <AssignTask dossierId={dossierId} f={f} />}
      </div>
      {hint && (
        <div style={{ fontSize: 11, marginTop: 2, paddingLeft: 8, opacity: 0.85 }}>
          Fix: {hint}
        </div>
      )}
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
  // ROUND9-VALIDATE item 5 (n=10, "people skip what is collapsed, and that
  // list is the most important thing on the card"): the Checks / Does-NOT-
  // check coverage now defaults OPEN.
  const [open, setOpen] = useState(true);
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
  const stale = criteriaStaleness(criteria);
  const checksumNote = criteriaChecksumNote(criteria);
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
      {/* ROUND9-VALIDATE item 1 (BLOCKER, n=14): the LOUD staleness warning
          when the scheduled ruleset review is overdue — plus, always, the
          honest one-liner naming where HC publishes the current criteria
          (ANDS Studio cannot detect an HC republication automatically). */}
      {stale?.review_overdue ? (
        <div
          className="notice bad"
          role="alert"
          style={{ marginTop: 8, fontSize: 12, lineHeight: 1.55 }}
        >
          <b>{stale.message}</b>
          <div className="mut" style={{ marginTop: 4 }}>
            {stale.limitation}
          </div>
        </div>
      ) : (
        stale && (
          <div className="mut" style={{ fontSize: 11.5, marginTop: 3, lineHeight: 1.5 }}>
            {stale.message} ANDS Studio cannot detect a Health Canada
            republication automatically — verify the current criteria at{" "}
            {stale.verify_at}.
          </div>
        )
      )}
      {/* ROUND9-VALIDATE item 2 (cdmo_ra_manager): the honest sponsor-scoping
          statement + the ruleset-pinning limit, stated in-UI rather than
          implied. */}
      <div className="mut" style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.5 }}>
        {SPONSOR_SCOPE_STATEMENT} {RULESET_PINNING_LIMIT}
      </div>
      {/* ROUND9-VALIDATE item 15 (ra_director_cro): the direct auto-placement
          statement, on the flow itself. */}
      <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
        {AUTO_PLACEMENT_STATEMENT}
      </div>
      <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
        {criteria.disclaimer}
      </div>
      {/* ROUND9-VALIDATE item 5: the md5 caveat moves ONTO the card face (the
          full footnote also remains in the technical-check disclosure). */}
      <div className="mut" style={{ fontSize: 11.5, marginTop: 3 }}>
        Where a checksum is shown it is document control (md5), not validation.
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
          {/* ROUND9-VALIDATE item 10: how the leaf md5 is computed — exactly
              the eCTD 3.2.2 convention — surfaced with the coverage lists. */}
          {checksumNote && (
            <div className="mut" style={{ marginTop: 10, lineHeight: 1.55 }}>
              {checksumNote}
            </div>
          )}
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
// CSV/JSON/PDF exports. ROUND9-VALIDATE item 1: when the scheduled ruleset
// review is overdue, the staleness warning rides the stamp into every export.
function criteriaStamp(c?: ValidationCriteria): string {
  if (!c) return "Ruleset: (unnamed structural check)";
  const stale = criteriaStaleness(c);
  return (
    `Ruleset: ${c.name} v${c.version}` +
    (c.synced ? ` · synced ${c.synced}` : "") +
    " · structural/technical only — NOT Health Canada's official eValidator" +
    (stale?.review_overdue
      ? " · RULESET REVIEW OVERDUE — may trail HC's current published " +
        "criteria; verify at canada.ca"
      : "")
  );
}

// ROUND9-VALIDATE item 6 (n=10): the defensibility artifacts gathered
// on-demand when a report is exported — who ran it, the live rule catalogue
// (per-finding Source + how-to-fix), the parity-gap rows, the recorded
// override history, and the per-leaf md5 inventory (document control).
interface ExportExtras {
  runBy: string;
  rules: ValidationRule[];
  parity: ParityRow[];
  overrides: { actor: string; timestamp: string; sequence: string; reason: string }[];
  leaves: { leaf_id: string; href: string; checksum: string }[];
  view: CurrentView | null;
}

const LEAF_MD5_LABEL =
  "Leaf md5 checksums — document control, not validation (a byte " +
  "fingerprint so silent changes are detectable; never an acceptance signal)";

async function gatherExportExtras(dossierId: string): Promise<ExportExtras> {
  const [me, catalog, hist, view] = await Promise.all([
    auth.me().catch(() => null),
    dossierApi.validationRules().catch(() => null),
    dossierApi.getHistory(dossierId).catch(() => null),
    dossierApi.currentView(dossierId).catch(() => null),
  ]);
  const rules = catalog?.rules ?? [];
  const overrides = (hist?.events ?? [])
    .filter((e) => e.event_type === "dossier.sequence_exported_override")
    .map((e) => {
      const data = (e.data ?? {}) as Record<string, unknown>;
      return {
        actor: e.actor || "(unknown)",
        timestamp: e.timestamp,
        sequence: String(data.sequence ?? ""),
        reason: e.reason || String(data.override_reason ?? data.reason ?? ""),
      };
    });
  return {
    runBy: me?.email || "(not signed in)",
    rules,
    parity: buildParity(rules),
    overrides,
    leaves: (view?.live ?? []).map((l) => ({
      leaf_id: l.leaf_id,
      href: l.href,
      checksum: l.checksum,
    })),
    view,
  };
}

function findingExportRow(
  f: ValidationFinding,
  severity: string,
  x: ExportExtras,
  idx: Map<string, ValidationRule>
) {
  const rule = ruleForFinding(idx, f);
  return {
    severity,
    rule_id: f.rule_id || "",
    rule: f.rule,
    leaf: f.leaf || "",
    module: moduleOfLeaf(f.leaf, x.view) || "",
    message: f.message,
    how_to_fix: ruleHowToFix(rule),
    source: rule?.source || "",
  };
}

function reportCsv(v: ValidationResult, dossierId: string, x: ExportExtras): string {
  const generatedAt = new Date().toISOString();
  const c = v.criteria;
  const idx = indexRules(x.rules);
  const rows = [
    ...v.errors.map((f) => findingExportRow(f, "error", x, idx)),
    ...v.warnings.map((f) => findingExportRow(f, "warning", x, idx)),
  ];
  const lines = [
    `# ${criteriaStamp(c)}`,
    `# Dossier: ${dossierId} · generated ${generatedAt} · result: ${
      v.passed ? "no structural issues" : `${v.errors.length} error(s)`
    }`,
    // item 6: who ran the check
    `# Run by: ${x.runBy}`,
    "# You must still run HC eValidator before transmission.",
    ["severity", "rule_id", "rule", "leaf", "module", "message", "how_to_fix", "source"].join(","),
    ...rows.map((r) =>
      [r.severity, r.rule_id, r.rule, r.leaf, r.module, r.message, r.how_to_fix, r.source]
        .map(csvCell)
        .join(",")
    ),
    "",
    "# --- Parity-gap table ('overlaps' = same defect class, NOT a 1:1 parity claim; 'no HC counterpart' = ANDS Studio convenience check) ---",
    ["family", "hc_evalidator", "rule_ids", "note"].join(","),
    ...x.parity.map((p) =>
      [p.family, p.covered ? "overlaps" : "no HC counterpart", p.ruleIds.join(" "), p.note]
        .map(csvCell)
        .join(",")
    ),
    "",
    "# --- Override history (typed reasons recorded to the audit trail) ---",
    ["who", "when", "sequence", "reason"].join(","),
    ...(x.overrides.length
      ? x.overrides.map((o) =>
          [o.actor, o.timestamp, o.sequence, o.reason].map(csvCell).join(",")
        )
      : ["# (no export overrides recorded)"]),
    "",
    `# --- ${LEAF_MD5_LABEL} ---`,
    ["leaf_id", "href", "md5 (document control)"].join(","),
    ...x.leaves.map((l) =>
      [l.leaf_id, l.href, l.checksum].map(csvCell).join(",")
    ),
  ];
  return lines.join("\n");
}

function reportJson(v: ValidationResult, dossierId: string, x: ExportExtras): string {
  const generatedAt = new Date().toISOString();
  const c = v.criteria;
  const idx = indexRules(x.rules);
  return JSON.stringify(
    {
      dossier_id: dossierId,
      generated_at: generatedAt,
      // item 6: who ran the check — part of the machine-readable evidence
      run_by: x.runBy,
      passed: v.passed,
      // WS-VALIDATE: explicit provenance block so the ruleset name/version/sync
      // date is machine-readable at the top of the report, in addition to the
      // full criteria object.
      ruleset: c
        ? {
            name: c.name,
            version: c.version,
            synced: c.synced || null,
            staleness: criteriaStaleness(c),
          }
        : null,
      criteria: c || null,
      checksum_note: criteriaChecksumNote(c) || null,
      note:
        "Structural/format completeness check only — NOT Health Canada " +
        "review and NOT full eCTD technical validation. You must still run " +
        "HC eValidator before transmission. Findings carry stable rule ids, " +
        "leaf ids and source clauses so this file can be diffed against an " +
        "eValidator report.",
      // item 6: findings enriched with the rule-to-guidance Source mapping +
      // the how-to-fix hint, keyed by stable rule ids.
      errors: v.errors.map((f) => findingExportRow(f, "error", x, idx)),
      warnings: v.warnings.map((f) => findingExportRow(f, "warning", x, idx)),
      rule_catalogue: x.rules,
      parity: {
        note:
          "'overlaps' means HC's eValidator checks the same class of defect " +
          "— not a 1:1 numeric-parity claim. 'no HC counterpart' rows are " +
          "ANDS Studio convenience checks.",
        rows: x.parity,
      },
      overrides: x.overrides,
      leaf_checksums: {
        md5_note: LEAF_MD5_LABEL,
        items: x.leaves.map((l) => ({
          leaf_id: l.leaf_id,
          href: l.href,
          md5: l.checksum,
        })),
      },
    },
    null,
    2
  );
}

// WS-VALIDATE: a print-friendly PDF export. We do NOT claim PDF/A conformance —
// this opens a stamped, print-ready report the filer can "Save as PDF" from the
// browser print dialog. ROUND9-VALIDATE item 6: restructured as a
// human-readable REMEDIATION CHECKLIST — findings grouped by module with
// checkbox rows (rule id · leaf · message · how-to-fix · Source), then the
// parity-gap table, override history and the leaf-md5 appendix (document
// control), so it reads as a work plan rather than a data dump.
function reportPdf(v: ValidationResult, dossierId: string, x: ExportExtras) {
  const c = v.criteria;
  const generatedAt = new Date().toISOString();
  const idx = indexRules(x.rules);
  const esc = (s: unknown) =>
    String(s == null ? "" : s).replace(
      /[&<>]/g,
      (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch] as string)
    );
  const rows = [
    ...v.errors.map((f) => findingExportRow(f, "error", x, idx)),
    ...v.warnings.map((f) => findingExportRow(f, "warning", x, idx)),
  ];
  const byModule = new Map<string, typeof rows>();
  for (const r of rows) {
    const key = r.module || "(module unresolved)";
    const arr = byModule.get(key) || [];
    arr.push(r);
    byModule.set(key, arr);
  }
  const moduleSections = [...byModule.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(
      ([mod, rs]) =>
        `<h3>${esc(mod)} — ${rs.length} item(s)</h3>` +
        `<table><thead><tr><th></th><th>Severity</th><th>Rule id</th>` +
        `<th>Leaf/file</th><th>Message</th><th>How to fix</th><th>Source</th></tr></thead><tbody>` +
        rs
          .map(
            (r) =>
              `<tr><td class="cb">&#9744;</td><td>${esc(r.severity)}</td>` +
              `<td><code>${esc(r.rule_id)}</code></td>` +
              `<td><code>${esc(r.leaf)}</code></td><td>${esc(r.message)}</td>` +
              `<td>${esc(r.how_to_fix)}</td><td class="src">${esc(r.source)}</td></tr>`
          )
          .join("") +
        `</tbody></table>`
    )
    .join("");
  const checklist = rows.length
    ? moduleSections
    : `<p>No presence/format issues found. This does not confirm scientific adequacy or full eCTD validity.</p>`;
  const parityRows = x.parity
    .map(
      (p) =>
        `<tr><td>${esc(p.family)}</td><td>${
          p.covered ? "overlaps" : "no HC counterpart"
        }</td><td><code>${esc(p.ruleIds.join(" "))}</code></td><td class="src">${esc(
          p.note
        )}</td></tr>`
    )
    .join("");
  const overrideRows = x.overrides.length
    ? x.overrides
        .map(
          (o) =>
            `<tr><td>${esc(o.actor)}</td><td>${esc(o.timestamp)}</td><td>${esc(
              o.sequence
            )}</td><td>${esc(o.reason)}</td></tr>`
        )
        .join("")
    : `<tr><td colspan="4">No export overrides recorded.</td></tr>`;
  const leafRows = x.leaves
    .map(
      (l) =>
        `<tr><td><code>${esc(l.leaf_id)}</code></td><td>${esc(
          l.href
        )}</td><td><code>${esc(l.checksum)}</code></td></tr>`
    )
    .join("");
  const html =
    `<!doctype html><html><head><meta charset="utf-8"><title>` +
    `${esc(dossierId)} — remediation checklist</title><style>` +
    `body{font:13px system-ui,sans-serif;padding:24px;color:#111}` +
    `h1{font-size:18px;margin:0 0 4px}h2{font-size:15px;margin:18px 0 4px}` +
    `h3{font-size:13px;margin:14px 0 4px}` +
    `.stamp{font-size:11px;color:#555;margin:2px 0}` +
    `.banner{border:1px solid #b45309;background:#fffbeb;color:#7c2d12;` +
    `padding:8px 10px;border-radius:6px;margin:12px 0;font-size:12px}` +
    `table{border-collapse:collapse;width:100%;margin-top:6px;font-size:11.5px}` +
    `th,td{border:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}` +
    `td.cb{font-size:14px;text-align:center;width:22px}` +
    `td.src{font-size:10px;color:#555}` +
    `code{font-size:11px}` +
    `@media print{button{display:none}}` +
    `</style></head><body>` +
    `<h1>eCTD structural completeness — remediation checklist</h1>` +
    `<div class="stamp">${esc(criteriaStamp(c))}</div>` +
    `<div class="stamp">Dossier: ${esc(dossierId)} · generated ${esc(
      generatedAt
    )} · result: ${
      v.passed ? "no structural issues" : `${v.errors.length} error(s)`
    }</div>` +
    `<div class="stamp">Run by: ${esc(x.runBy)}</div>` +
    (c?.modeled_on
      ? `<div class="stamp">Modeled on: ${esc(c.modeled_on)}</div>`
      : "") +
    `<div class="banner"><b>You must still run Health Canada's official ` +
    `eValidator before transmission.</b> A clean result here means the sequence ` +
    `is structurally plausible — it does NOT mean it will pass HC's eValidator ` +
    `or be accepted on screening. This is NOT full eCTD technical validation ` +
    `and does NOT claim PDF/A conformance.</div>` +
    `<h2>Findings by module — work the boxes top to bottom</h2>` +
    checklist +
    `<h2>Parity-gap table</h2>` +
    `<p class="stamp">'overlaps' = HC eValidator checks the same defect class ` +
    `(not a 1:1 parity claim); 'no HC counterpart' = ANDS Studio convenience check.</p>` +
    `<table><thead><tr><th>Rule family</th><th>HC eValidator</th>` +
    `<th>Rule ids</th><th>Note</th></tr></thead><tbody>${parityRows}</tbody></table>` +
    `<h2>Override history</h2>` +
    `<table><thead><tr><th>Who</th><th>When</th><th>Sequence</th>` +
    `<th>Typed reason (audit trail)</th></tr></thead><tbody>${overrideRows}</tbody></table>` +
    `<h2>Leaf md5 appendix</h2>` +
    `<p class="stamp">${esc(LEAF_MD5_LABEL)}.</p>` +
    `<table><thead><tr><th>Leaf id</th><th>href</th>` +
    `<th>md5 (document control)</th></tr></thead><tbody>${leafRows}</tbody></table>` +
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
  const [showAllWarnings, setShowAllWarnings] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  // context for hints / links / filters — best-effort, never blocks the card
  const [view, setView] = useState<CurrentView | null>(null);
  const [rules, setRules] = useState<ValidationRule[] | null>(null);
  const [moduleFilter, setModuleFilter] = useState("all");
  // ROUND9-VALIDATE item 7: the first-run tour (auto-opens once, replayable
  // from the help icon in the header).
  const [tourOpen, openTour, closeTour] = useFirstRunTour();

  useEffect(() => {
    let live = true;
    dossierApi
      .currentView(dossierId)
      .then((cv) => {
        if (live) setView(cv);
      })
      .catch(() => {});
    dossierApi
      .validationRules()
      .then((c) => {
        if (live) setRules(c.rules);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [dossierId]);

  const v = full || structural;
  const idx = useMemo(() => indexRules(rules), [rules]);

  // ROUND9-VALIDATE item 3 (n=12, "never truncate error-severity findings"):
  // errors are ALWAYS rendered in full — only warnings stay capped.
  const moduleOf = (f: ValidationFinding) => moduleOfLeaf(f.leaf, view);
  const errorModules = useMemo(() => {
    const mods = new Set<string>();
    for (const f of v.errors) {
      const m = moduleOfLeaf(f.leaf, view);
      if (m) mods.add(m);
    }
    return [...mods].sort();
  }, [v.errors, view]);
  const errs =
    moduleFilter === "all"
      ? v.errors
      : v.errors.filter((f) => moduleOf(f) === moduleFilter);
  // FIX-PDFA-NOISE: collapse the repetitive PDF/A-1b advisories (CA-W-70xx) into
  // a per-rule summary so 10-12 near-identical yellow rows read as the 2-4
  // grouped advisories they actually are. Non-PDF/A warnings stay individual.
  const { pdfaGroups, other: otherWarnings } = groupPdfaWarnings(v.warnings);
  const shownOther = showAllWarnings ? otherWarnings : otherWarnings.slice(0, 3);

  async function run() {
    setBusy(true);
    try {
      setFull(await dossierApi.validate(dossierId));
    } finally {
      setBusy(false);
    }
  }

  // ROUND9-VALIDATE item 6: exports gather the defensibility artifacts
  // on-demand (run-by, Source mapping, parity table, overrides, leaf md5).
  async function exportReport(kind: "csv" | "json" | "pdf") {
    setExportBusy(true);
    try {
      const extras = await gatherExportExtras(dossierId);
      const stamp = `${dossierId}-completeness-check`;
      if (kind === "csv") {
        downloadBlob(
          `${stamp}.csv`,
          "text/csv;charset=utf-8",
          reportCsv(v, dossierId, extras)
        );
      } else if (kind === "json") {
        downloadBlob(
          `${stamp}.json`,
          "application/json",
          reportJson(v, dossierId, extras)
        );
      } else {
        reportPdf(v, dossierId, extras);
      }
    } catch (e) {
      toast.error(`Could not build the report — ${String(e)}`);
    } finally {
      setExportBusy(false);
    }
  }

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Draft completeness check</h3>
        <button
          className="ghost"
          style={{
            fontSize: 11,
            padding: "2px 6px",
            display: "inline-flex",
            gap: 4,
            alignItems: "center",
          }}
          onClick={openTour}
          title="Replay the first-run walkthrough (completeness check → findings → sequences → export block & override → eValidator handoff)"
          aria-label="Replay the validation walkthrough"
        >
          <HelpCircle size={12} aria-hidden /> Tour
        </button>
        <span
          style={{ marginLeft: "auto" }}
          className={`ready-status ${v.passed ? "READY" : "BLOCKED"}`}
        >
          {/* ROUND9-VALIDATE item 5: the "(structural; not HC eValidator)"
              limitation is baked INTO the green chip so a clean result can
              never be misread as an HC pass. item 3: the blocked chip carries
              the warning count too. */}
          {v.passed
            ? "● NO STRUCTURAL ISSUES (structural; not HC eValidator)"
            : `● ${v.errors.length} issue(s)${
                v.warnings.length ? ` · ${v.warnings.length} warning(s)` : ""
              }`}
        </span>
      </div>

      {/* ROUND9-VALIDATE item 3: the persistent blocker summary strip — the
          gate state in one line, never hidden behind an expander. */}
      <div
        role="status"
        className={`notice ${v.passed ? "ok" : "bad"}`}
        style={{ marginTop: 8, fontSize: 12, padding: "5px 10px" }}
      >
        <b>{v.errors.length} error(s)</b> · {v.warnings.length} warning(s) ·{" "}
        {v.passed
          ? "clean — export gate open (structural only; run HC eValidator before transmission)"
          : "blocked — export is gated until the errors below are resolved or overridden with a typed reason"}
      </div>

      <ValidationTour open={tourOpen} onClose={closeTour} />

      <CriteriaHeader criteria={v.criteria} />
      <EctdPrimer compact />
      {/* ROUND9-VALIDATE item 4: the chip-type legend, beside the persistent
          glossary affordance. */}
      <ChipLegend compact />

      <div style={{ marginTop: 14 }}>
        {/* ROUND9-VALIDATE item 2: module filter chips for parallel work —
            shown when the errors span more than one module. Findings are
            already sponsor-scoped by the workspace tenant boundary. */}
        {errorModules.length > 1 && (
          <div
            style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 6 }}
            role="group"
            aria-label="Filter findings by module"
          >
            {["all", ...errorModules].map((m) => (
              <button
                key={m}
                className={`chip ${moduleFilter === m ? "ready" : ""}`}
                style={{ fontSize: 10, padding: "1px 8px" }}
                aria-pressed={moduleFilter === m}
                onClick={() => setModuleFilter(m)}
              >
                {m === "all" ? `All (${v.errors.length})` : m.toUpperCase()}
              </button>
            ))}
          </div>
        )}
        {errs.map((e, i) => {
          const rule = ruleForFinding(idx, e);
          const mod = moduleOf(e);
          return (
            <Row
              key={i}
              f={e}
              dossierId={dossierId}
              hint={ruleHowToFix(rule)}
              fixHref={mod ? modulePath(dossierId, mod) : null}
            />
          );
        })}
        {moduleFilter !== "all" && errs.length < v.errors.length && (
          <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
            Showing {errs.length} of {v.errors.length} error(s) (module filter
            active — errors are never hidden; clear the filter to see all).
          </div>
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
            onClick={() => setShowAllWarnings((s) => !s)}
          >
            {showAllWarnings
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
            onClick={() => exportReport("csv")}
            disabled={exportBusy}
            title="Findings with Source + how-to-fix, parity-gap table, override history, leaf md5 appendix (document control), run-by and ruleset stamps"
          >
            {exportBusy ? "Building…" : "Download report (CSV)"}
          </button>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={() => exportReport("json")}
            disabled={exportBusy}
            title="Machine-readable report (stable rule ids + source clauses) structured to diff against an eValidator report"
          >
            {exportBusy ? "Building…" : "Download report (JSON)"}
          </button>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "6px 10px" }}
            onClick={() => exportReport("pdf")}
            disabled={exportBusy}
            title="Opens a print-ready remediation CHECKLIST (findings by module with how-to-fix + Source) — use your browser's Save as PDF. Not a PDF/A conformance claim."
          >
            {exportBusy ? "Building…" : "Download report (PDF)"}
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

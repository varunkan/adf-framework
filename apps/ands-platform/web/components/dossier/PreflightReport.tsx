"use client";
import { useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  PenLine,
  FileDown,
  Printer,
  ClipboardCheck,
} from "lucide-react";
import { toast } from "sonner";
import { dossierApi } from "@/lib/dossierApi";
import type {
  PreflightReport as Report,
  SignatureStatus,
} from "@/lib/dossierTypes";

// TIER3-PREFLIGHT: ONE consolidated pre-flight / QA hand-off report. Tier-2
// respondents asked verbatim for "ONE consolidated pre-flight report I can hand
// to QA rather than re-running validate at each step." This surface renders the
// whole filing-readiness picture — structural validation, the user-attested
// external eValidator result, the Part-11 e-sign + SoD outcome + live
// verification, the fee state, the sequence/lifecycle view, and the
// placeholder/real Dossier-ID + REP status — and offers export (CSV / JSON /
// print-to-PDF) so a QA reviewer or client can archive ONE artifact.
//
// HONESTY: every disclaimer travels inline (it is a consolidation of already-
// honest pieces — no caveat is laundered away). The readiness line is a
// STRUCTURAL statement and always names the still-required HC eValidator step;
// it never claims Health Canada acceptance or certification.

function download(name: string, mime: string, text: string) {
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

// Flatten the consolidated report into a QA-readable checklist of rows +
// findings — the same "stamp provenance into leading # comment lines" pattern
// the validation report uses, so criteria/version/sync travels with the file.
function toCsv(r: Report): string {
  const c = r.validation.criteria;
  const lines: string[] = [
    `# ANDS Studio pre-flight / QA hand-off report`,
    `# Dossier: ${r.dossier_id} · ${r.title} · generated ${r.generated_at}`,
    c
      ? `# Ruleset: ${c.name} v${c.version}${
          c.synced ? ` · synced ${c.synced}` : ""
        } · structural/technical only — NOT Health Canada's official eValidator`
      : `# Ruleset: (unnamed structural check)`,
    `# ${r.readiness.summary}`,
    `# ${r.readiness.next_step}`,
    ...Object.values(r.disclaimers).map((d) => `# ${d}`),
    ["section", "item", "status", "detail"].join(","),
  ];
  const row = (section: string, item: string, status: string, detail = "") =>
    [section, item, status, detail].map(csvCell).join(",");

  lines.push(
    row(
      "readiness",
      "structural gate",
      r.readiness.ready ? "no structural issues" : "blocked",
      `${r.readiness.structural_errors} error(s), ${r.readiness.structural_warnings} warning(s)`
    )
  );
  lines.push(
    row(
      "dossier-id",
      "REP / Dossier ID",
      r.rep.placeholder ? "placeholder" : "real",
      r.rep.rep_request
        ? "REP request prepared (not transmitted)"
        : "no REP request recorded"
    )
  );
  lines.push(
    row(
      "fees",
      "fee arranged",
      r.fees?.fee_paid ? "arranged" : "not arranged",
      r.fees?.sme_granted ? "small-business status granted" : ""
    )
  );
  lines.push(
    row(
      "e-sign",
      "Part 11 signature",
      r.esign.signature_status,
      r.esign.message
    )
  );
  lines.push(
    row(
      "evalidator",
      "external eValidator (user-attested)",
      r.evalidator_attestation
        ? r.evalidator_attestation.result
        : "not attested",
      r.evalidator_attestation
        ? `${r.evalidator_attestation.validator_name}${
            r.evalidator_attestation.validated_on
              ? ` on ${r.evalidator_attestation.validated_on}`
              : ""
          } (external result)`
        : "run HC eValidator on the exported package and attach the result"
    )
  );
  for (const e of r.validation.errors)
    lines.push(row("validation", e.rule_id || e.rule, "error", e.message));
  for (const w of r.validation.warnings)
    lines.push(row("validation", w.rule_id || w.rule, "warning", w.message));
  return lines.join("\n");
}

function esc(s: unknown): string {
  return String(s == null ? "" : s).replace(
    /[&<>]/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch] as string)
  );
}

// Print-ready HTML — reuses the validation report's print pattern (open a
// window, "Save as PDF"). We do NOT claim PDF/A conformance; the disclaimers are
// stamped into a banner so provenance + honest scope travels with the printout.
function printReport(r: Report) {
  const c = r.validation.criteria;
  const yesno = (b: boolean) => (b ? "Yes" : "No");
  const findings = [
    ...r.validation.errors.map((f) => ({ sev: "error", f })),
    ...r.validation.warnings.map((f) => ({ sev: "warning", f })),
  ];
  const findingRows = findings.length
    ? findings
        .map(
          (x) =>
            `<tr><td>${esc(x.sev)}</td><td><code>${esc(
              x.f.rule_id || ""
            )}</code></td><td><code>${esc(x.f.leaf || "")}</code></td><td>${esc(
              x.f.message
            )}</td></tr>`
        )
        .join("")
    : `<tr><td colspan="4">No structural presence/format issues found. This does not confirm scientific adequacy or full eCTD validity.</td></tr>`;
  const disclaimerItems = Object.values(r.disclaimers)
    .map((d) => `<li>${esc(d)}</li>`)
    .join("");
  const att = r.evalidator_attestation;
  const html =
    `<!doctype html><html><head><meta charset="utf-8"><title>` +
    `${esc(r.dossier_id)} — pre-flight / QA hand-off report</title><style>` +
    `body{font:13px system-ui,sans-serif;padding:24px;color:#111}` +
    `h1{font-size:19px;margin:0 0 2px}h2{font-size:14px;margin:18px 0 6px}` +
    `.stamp{font-size:11px;color:#555;margin:2px 0}` +
    `.banner{border:1px solid #b45309;background:#fffbeb;color:#7c2d12;` +
    `padding:8px 10px;border-radius:6px;margin:12px 0;font-size:12px}` +
    `.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 18px;font-size:12px;margin-top:6px}` +
    `.grid div span{color:#555}` +
    `table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}` +
    `th,td{border:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}` +
    `code{font-size:11px}ul{margin:4px 0 0 18px;padding:0;font-size:11px;color:#555}` +
    `@media print{button{display:none}}` +
    `</style></head><body>` +
    `<h1>Pre-flight / QA hand-off report</h1>` +
    `<div class="stamp">Dossier: ${esc(r.dossier_id)} · ${esc(
      r.title
    )} · generated ${esc(r.generated_at)}</div>` +
    (c
      ? `<div class="stamp">Ruleset: ${esc(c.name)} v${esc(c.version)}${
          c.synced ? ` · synced ${esc(c.synced)}` : ""
        } · structural/technical only — NOT Health Canada's official eValidator</div>`
      : "") +
    `<div class="banner"><b>${esc(r.readiness.summary)}</b><br/>${esc(
      r.readiness.next_step
    )}</div>` +
    `<h2>Readiness</h2><div class="grid">` +
    `<div><span>Structural gate:</span> ${
      r.readiness.ready ? "no structural issues" : "blocked"
    }</div>` +
    `<div><span>Structural errors / warnings:</span> ${r.readiness.structural_errors} / ${r.readiness.structural_warnings}</div>` +
    `<div><span>Dossier ID:</span> ${
      r.rep.placeholder ? "placeholder (request real ID via REP)" : "real"
    }</div>` +
    `<div><span>Fee arranged:</span> ${yesno(!!r.fees?.fee_paid)}</div>` +
    `<div><span>Part 11 e-signature:</span> ${esc(
      r.esign.signature_status
    )} — ${esc(r.esign.message)}</div>` +
    `<div><span>Segregation of duties:</span> ${
      r.esign.segregation_of_duties?.separated
        ? "separated"
        : r.esign.segregation_of_duties?.conflict
        ? "CONFLICT"
        : "not proven"
    }</div>` +
    `<div><span>External eValidator (user-attested):</span> ${
      att ? `${esc(att.result)} — ${esc(att.validator_name)}` : "not attested"
    }</div>` +
    `<div><span>Sequences:</span> ${r.sequences.sequences.length} (active ${esc(
      r.sequences.active_sequence
    )})</div>` +
    `</div>` +
    `<h2>Structural validation findings</h2>` +
    `<table><thead><tr><th>Severity</th><th>Rule id</th><th>Leaf/file</th>` +
    `<th>Message</th></tr></thead><tbody>${findingRows}</tbody></table>` +
    `<h2>Honest scope — read before you rely on this report</h2>` +
    `<ul>${disclaimerItems}</ul>` +
    `<button onclick="window.print()">Print / Save as PDF</button>` +
    `</body></html>`;
  const w = window.open("", "_blank");
  if (w) {
    w.document.write(html);
    w.document.close();
    w.focus();
  }
}

// FIX-PREFLIGHT-SIG: surface the e-sign signature_status LOUDLY. The report
// shows the LATEST stored manifest + a LIVE verify, so after a leaf change or a
// conflict-demo sign the current signature is legitimately stale/conflicted.
// A bare "verified=false" reads like a defect to a QA reviewer — this banner
// says WHICH state it is, WHY, and (when actionable) to re-sign the current
// package before hand-off. It never claims Health Canada acceptance.
const SIG_PRESENT: Record<
  SignatureStatus,
  {
    tone: "ok" | "warn" | "bad";
    Icon: typeof ShieldCheck;
    label: string;
    resign: boolean;
  }
> = {
  verified: {
    tone: "ok",
    Icon: ShieldCheck,
    label: "Signature verified",
    resign: false,
  },
  unsigned: {
    tone: "warn",
    Icon: ShieldAlert,
    label: "Not signed yet",
    resign: false,
  },
  stale_unverified: {
    tone: "bad",
    Icon: ShieldX,
    label: "Signature stale — package changed after signing",
    resign: true,
  },
  sod_conflict: {
    tone: "bad",
    Icon: ShieldX,
    label: "Segregation-of-duties conflict",
    resign: true,
  },
};

function SignatureBanner({ esign }: { esign: Report["esign"] }) {
  const p = SIG_PRESENT[esign.signature_status] ?? SIG_PRESENT.unsigned;
  const { Icon } = p;
  return (
    <div
      className={`notice ${p.tone}`}
      style={{ marginTop: 10, fontSize: 12 }}
      role={p.tone === "bad" ? "alert" : undefined}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontWeight: 700,
        }}
      >
        <Icon size={14} aria-hidden />
        Part 11 e-signature: {p.label}
      </div>
      <div style={{ marginTop: 4 }}>{esign.message}</div>
      {p.resign && (
        <div
          style={{
            marginTop: 6,
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            fontWeight: 600,
          }}
        >
          <PenLine size={12} aria-hidden />
          Action: re-sign the current package before QA hand-off.
        </div>
      )}
    </div>
  );
}

function StatusChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`chip ${ok ? "ready" : "blocked"}`} style={{ fontSize: 11 }}>
      {ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />} {label}
    </span>
  );
}

export function PreflightReport({ dossierId }: { dossierId: string }) {
  const [rep, setRep] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    setBusy(true);
    setErr("");
    try {
      const r = await dossierApi.preflightReport(dossierId);
      setRep(r);
      toast.success("Pre-flight report assembled");
    } catch (e) {
      const m = String(e instanceof Error ? e.message : e);
      setErr(m);
      toast.error("Could not assemble the pre-flight report");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <ClipboardCheck size={15} aria-hidden />
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          Pre-flight / QA hand-off report
        </div>
        {rep && (
          <span
            style={{ marginLeft: "auto" }}
            className={`ready-status ${rep.readiness.ready ? "READY" : "BLOCKED"}`}
          >
            {rep.readiness.ready
              ? "● NO STRUCTURAL ISSUES"
              : `● ${rep.readiness.structural_errors} issue(s)`}
          </span>
        )}
      </div>
      <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
        One consolidated document a QA reviewer or client can archive — the whole
        filing-readiness picture in one place, instead of re-running validate at
        each step. This is a <b>structural</b> readiness snapshot, not a Health
        Canada review or acceptance.
      </div>

      {!rep && (
        <button
          className="chip"
          style={{ marginTop: 10 }}
          onClick={load}
          disabled={busy}
        >
          {busy ? "Assembling…" : "Assemble pre-flight report"}
        </button>
      )}
      {err && (
        <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
          {err}
        </div>
      )}

      {rep && (
        <>
          <div
            className="notice warn"
            style={{ marginTop: 10, fontSize: 12 }}
          >
            <b>{rep.readiness.summary}</b>
            <div style={{ marginTop: 4 }}>{rep.readiness.next_step}</div>
          </div>

          {/* FIX-PREFLIGHT-SIG: loud, unambiguous signature status banner */}
          <SignatureBanner esign={rep.esign} />

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              marginTop: 10,
            }}
          >
            <StatusChip
              ok={rep.readiness.ready}
              label={
                rep.readiness.ready
                  ? "Structural: clean"
                  : `Structural: ${rep.readiness.structural_errors} error(s)`
              }
            />
            <StatusChip
              ok={!rep.rep.placeholder}
              label={rep.rep.placeholder ? "Dossier ID: placeholder" : "Dossier ID: real"}
            />
            <StatusChip
              ok={!!rep.fees?.fee_paid}
              label={rep.fees?.fee_paid ? "Fee: arranged" : "Fee: not arranged"}
            />
            <StatusChip
              ok={rep.esign.handoff_ready_signature}
              label={`Part 11: ${SIG_PRESENT[rep.esign.signature_status].label}`}
            />
            <StatusChip
              ok={!!rep.evalidator_attestation}
              label={
                rep.evalidator_attestation
                  ? `eValidator: ${rep.evalidator_attestation.result} (external)`
                  : "eValidator: not attested"
              }
            />
          </div>

          {/* SoD detail — honest role-separation, not an SSO/IdP claim */}
          {rep.esign.signed && rep.esign.segregation_of_duties && (
            <div className="mut" style={{ fontSize: 11, marginTop: 8 }}>
              <ShieldCheck size={12} aria-hidden />{" "}
              {rep.esign.segregation_of_duties.reason}
            </div>
          )}

          {/* the consolidated honesty disclaimers, inline with the report */}
          <details style={{ marginTop: 10 }}>
            <summary
              className="mut"
              style={{ fontSize: 12, cursor: "pointer" }}
            >
              Honest scope — what this report is and is NOT
            </summary>
            <ul
              className="mut"
              style={{ margin: "6px 0 0 16px", padding: 0, fontSize: 11 }}
            >
              {Object.entries(rep.disclaimers).map(([k, v]) => (
                <li key={k}>{v}</li>
              ))}
            </ul>
          </details>

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              marginTop: 12,
            }}
          >
            <button
              className="ghost"
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={() => printReport(rep)}
              title="Opens a print-ready, disclaimer-stamped report — use your browser's Save as PDF. Not a PDF/A conformance claim."
            >
              <Printer size={13} /> Export (PDF)
            </button>
            <button
              className="ghost"
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={() =>
                download(
                  `${dossierId}-preflight-report.csv`,
                  "text/csv;charset=utf-8",
                  toCsv(rep)
                )
              }
            >
              <FileDown size={13} /> Export (CSV)
            </button>
            <button
              className="ghost"
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={() =>
                download(
                  `${dossierId}-preflight-report.json`,
                  "application/json",
                  JSON.stringify(rep, null, 2)
                )
              }
            >
              <FileDown size={13} /> Export (JSON)
            </button>
            <button
              className="ghost"
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={load}
              disabled={busy}
            >
              {busy ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

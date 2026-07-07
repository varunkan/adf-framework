"use client";
// journey · J18 printable one-pager (round-9 minor, n=2; veteran_contractor):
// "I can't hover on a hover when I'm reading a binder at my desk". One
// binder-ready printout combining: the journey snapshot, the ruleset
// name/version/sync date + what it mirrors and its review cadence, the FULL
// plain-language glossary definitions, and the session event ledger (plus a
// pointer to the dossier's Part-11 ledger export). The eValidator disclaimer
// is included VERBATIM — printing never softens it.
import { useCallback, useState } from "react";
import { Printer } from "lucide-react";
import { TERMS } from "@/lib/terms";
import { dossierApi } from "@/lib/dossierApi";
import type { JourneyView } from "@/lib/types";
import { fetchSessionEvents, type SessionEvent } from "./SessionLedgerCard";

// DO-NOT-BREAK: the trust-earning disclaimer, verbatim from the readiness card.
const EVALIDATOR_DISCLAIMER =
  "structural/technical checks, not HC's official eValidator; run eValidator " +
  "before you transmit";

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function PrintOnePager({ view }: { view: JourneyView }) {
  const [busy, setBusy] = useState(false);

  const print = useCallback(async () => {
    setBusy(true);
    try {
      // best-effort loads — the printout states plainly when a section is
      // unavailable rather than inventing content.
      let criteria: any = null;
      try {
        criteria = (await dossierApi.validationRules()).criteria;
      } catch {
        criteria = null;
      }
      let events: SessionEvent[] = [];
      try {
        events = (await fetchSessionEvents(view.id)).events;
      } catch {
        events = [];
      }

      const stages = view.journey.stages
        .map(
          (s) =>
            `<tr><td>${s.n}</td><td>${esc(s.label)}</td><td>${esc(
              s.status
            )}</td><td>${esc(s.reg || "")}</td></tr>`
        )
        .join("");

      const glossary = Object.entries(TERMS)
        .sort(([a], [b]) => a.toLowerCase().localeCompare(b.toLowerCase()))
        .map(
          ([k, v]) =>
            `<dt><b>${esc(k)}</b></dt><dd>${esc(v)}</dd>`
        )
        .join("");

      const ledger = events.length
        ? events
            .map(
              (e) =>
                `<tr><td>${e.seq}</td><td>${esc(e.at)}</td><td>${esc(
                  e.type
                )}</td><td>${esc(JSON.stringify(e.data || {}))}</td></tr>`
            )
            .join("")
        : `<tr><td colspan="4">Session ledger unavailable at print time.</td></tr>`;

      const rulesetBlock = criteria
        ? `<p><b>${esc(criteria.name)}</b> v${esc(criteria.version)}${
            criteria.synced ? ` · synced ${esc(criteria.synced)}` : ""
          }${
            criteria.modeled_on
              ? `<br/>Mirrors: ${esc(criteria.modeled_on)}`
              : ""
          }${
            criteria.review
              ? `<br/>Review cadence: ${esc(
                  criteria.review.cadence || ""
                )} · last reviewed ${esc(
                  criteria.review.last_reviewed || "—"
                )} · next review ${esc(criteria.review.next_review || "—")}`
              : ""
          }</p>`
        : "<p>Ruleset details unavailable at print time — see the readiness panel in-app.</p>";

      const html = `<!doctype html><html><head><meta charset="utf-8">
<title>ANDS Studio — journey one-pager</title>
<style>
  body{font:12px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;
       margin:28px;max-width:760px}
  h1{font-size:18px;margin:0 0 2px} h2{font-size:14px;margin:18px 0 6px;
       border-bottom:1px solid #ccc;padding-bottom:3px}
  table{border-collapse:collapse;width:100%;font-size:11px}
  td,th{border:1px solid #ccc;padding:3px 6px;text-align:left;
       vertical-align:top}
  dt{margin-top:7px} dd{margin:1px 0 0 0;color:#333}
  .mut{color:#555} .warn{border:1px solid #b45309;background:#fffbeb;
       padding:8px 10px;margin:8px 0;font-weight:600}
  @media print {.noprint{display:none}}
</style></head><body>
<h1>ANDS Studio — guided journey one-pager</h1>
<div class="mut">Printed ${esc(new Date().toISOString().slice(0, 19))} UTC ·
session ${esc(view.id)}${
        view.journey.dossier_id
          ? ` · dossier ${esc(view.journey.dossier_id)}`
          : " · no Dossier ID yet"
      }</div>
<div class="warn">Validation shown by ANDS Studio is ${esc(
        EVALIDATOR_DISCLAIMER
      )}.</div>

<h2>Journey snapshot — ${esc(view.title)}</h2>
<div>Filing checklist: ${view.readiness.done} of ${view.readiness.total}
steps complete (${view.readiness.percent}%) · status ${esc(
        view.readiness.status
      )}</div>
<table><tr><th>#</th><th>Step</th><th>Status</th><th>Regulatory anchor</th></tr>
${stages}</table>

<h2>Validation ruleset provenance</h2>
${rulesetBlock}

<h2>Session event ledger (append-only, from the first action)</h2>
<table><tr><th>Seq</th><th>At (UTC)</th><th>Event</th><th>Data</th></tr>
${ledger}</table>
${
        view.journey.dossier_id
          ? `<p class="mut">The dossier's own append-only Part-11 audit ledger
(document / signature / validation / transmission events) exports separately
from the in-app audit page for dossier ${esc(view.journey.dossier_id)}.</p>`
          : `<p class="mut">Once a Dossier ID exists, the dossier's append-only
Part-11 audit ledger exports separately from the in-app audit page.</p>`
      }

<h2>Plain-language glossary (${Object.keys(TERMS).length} terms)</h2>
<dl>${glossary}</dl>
<p class="noprint mut">Use your browser's Print dialog (Cmd/Ctrl-P) if
printing did not start automatically.</p>
</body></html>`;

      const w = window.open("", "_blank", "width=900,height=700");
      if (!w) return;
      w.document.write(html);
      w.document.close();
      w.focus();
      setTimeout(() => {
        try {
          w.print();
        } catch {
          /* user prints manually */
        }
      }, 250);
    } finally {
      setBusy(false);
    }
  }, [view]);

  return (
    <button
      className="ghost"
      style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 5 }}
      onClick={print}
      disabled={busy}
      title="Print a binder-ready one-pager: journey snapshot, ruleset version & sync date, the full glossary and the session audit ledger"
    >
      <Printer size={12} aria-hidden />
      {busy ? "Preparing…" : "Print one-pager"}
    </button>
  );
}

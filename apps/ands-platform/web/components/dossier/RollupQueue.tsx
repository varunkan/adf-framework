"use client";
// Round-9 ai_draft BLOCKER "No project-level roll-up of section states,
// owners and dates" (n=2): every section's state / owner / last-touched with
// counts + one-click CSV export for weekly status calls.
// Round-9 ai_draft MAJOR "Per-leaf attestation click-tax at dossier scale; no
// bulk attest" (n=6): the team-review queue — a list of AI-drafted sections
// awaiting confirmation where a reviewer OPENS each draft, then attests the
// reviewed set in one flow. A NAMED attestation is still recorded per leaf
// (one confirm call per section, server-side ledger event each).
import { useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { Disclosure } from "../Disclosure";
import { toast } from "sonner";
import { draftApi, type SectionsRollup } from "./draftApi";

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function RollupQueue({
  dossierId,
  onContent,
}: {
  dossierId: string;
  onContent: (c: any) => void;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SectionsRollup | null>(null);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // the review-first guardrail: a queue row can only be selected after the
  // reviewer has actually OPENED its draft document from this list.
  const [openedDocs, setOpenedDocs] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [credential, setCredential] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setData(await draftApi.sectionsRollup(dossierId));
      setErr("");
    } catch (e) {
      setErr(String(e));
    }
  }

  function exportCsv() {
    if (!data) return;
    const head = [
      "section", "module", "title", "state", "awaiting_review",
      "content_origin", "owner", "attested_by", "last_touched",
    ];
    const lines = [head.join(",")];
    for (const r of data.rows) {
      lines.push(
        [
          r.section, r.module, r.title,
          r.status, r.needs_review ? "yes" : "no",
          r.content_origin || "", r.owner, r.attested_by,
          r.updated_at,
        ].map((v) => csvEscape(String(v))).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${dossierId}-sections-rollup.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function bulkAttest() {
    if (!data || selected.size === 0 || !name.trim()) return;
    setBusy(true);
    let lastState: any = null;
    let ok = 0;
    for (const section of [...selected].sort()) {
      try {
        lastState = await draftApi.confirmContentAttested(dossierId, section, {
          attest_name: name.trim(),
          attest_credential: credential.trim(),
          attest_meaning: "I have reviewed this AI draft — it is my content",
        });
        ok += 1;
      } catch (e) {
        toast.error(`${section}: ${String(e)}`);
      }
    }
    if (ok > 0) {
      toast.success(
        `${ok} section${ok > 1 ? "s" : ""} attested by ${name.trim()} — ` +
        "a named attestation was recorded per leaf on the audit trail.");
      if (lastState) onContent(lastState);
      setSelected(new Set());
      await load();
    }
    setBusy(false);
  }

  const queue = data?.review_queue || [];
  return (
    <Disclosure
      className="rollup-queue"
      showLabel="Open"
      hideLabel="Close"
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o && !data) load();
      }}
      summary={
        <span style={{ fontSize: 13 }}>
          <b>Dossier-wide status &amp; review queue</b>
          <span className="mut"> — every section&apos;s state, owner and
          last-touched date; bulk-attest reviewed AI drafts</span>
        </span>
      }
    >
      {err && <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>}
      {!data && !err && (
        <div className="mut" style={{ fontSize: 12 }}>Loading roll-up…</div>
      )}
      {data && (
        <div style={{ display: "grid", gap: 10 }}>
          <div className="mut" style={{ fontSize: 12 }}>
            {data.counts.total} sections · {data.counts.complete || 0} complete
            · {data.counts.partial || 0} in progress ·{" "}
            {data.counts.needs_review || 0} awaiting review ·{" "}
            {data.counts.na || 0} N/A
            <button className="ghost" style={{ marginLeft: 10 }}
              onClick={exportCsv}>
              Export status CSV
            </button>
          </div>

          <div style={{ overflowX: "auto", maxHeight: 300, overflowY: "auto" }}>
            <table style={{ fontSize: 12, borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  {["Section", "Title", "State", "Origin", "Owner",
                    "Attested by", "Last touched"].map((h) => (
                    <th key={h} style={{ textAlign: "left", padding: "3px 8px",
                      position: "sticky", top: 0 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.section}>
                    <td style={{ padding: "2px 8px" }}><code>{r.section}</code></td>
                    <td style={{ padding: "2px 8px" }}>{r.title}</td>
                    <td style={{ padding: "2px 8px" }}>
                      {r.needs_review
                        ? <b style={{ color: "var(--warn)" }}>awaiting review</b>
                        : r.status}
                    </td>
                    <td style={{ padding: "2px 8px" }}>{r.content_origin || "—"}</td>
                    <td style={{ padding: "2px 8px" }}>{r.owner || "—"}</td>
                    <td style={{ padding: "2px 8px" }}>{r.attested_by || "—"}</td>
                    <td style={{ padding: "2px 8px" }}>
                      {r.updated_at ? r.updated_at.slice(0, 10) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="teach" style={{ fontSize: 12 }}>
            <b>Review queue — AI drafts awaiting confirmation ({queue.length})</b>
            {queue.length === 0 ? (
              <div className="mut" style={{ marginTop: 4 }}>
                No AI-drafted sections are awaiting review.
              </div>
            ) : (
              <>
                <div className="mut" style={{ margin: "4px 0 6px" }}>
                  Open each draft, review it against the Health Canada
                  guidance, then attest the reviewed set in one step. A row can
                  be selected only after its draft has been opened; a named
                  attestation is recorded per leaf.
                </div>
                {queue.map((q) => {
                  const doc = q.documents?.[0];
                  const opened = doc ? openedDocs.has(doc.doc_id) : false;
                  return (
                    <label key={q.section}
                      style={{ display: "flex", gap: 8, alignItems: "center",
                               marginBottom: 4 }}>
                      <input type="checkbox" style={{ width: "auto" }}
                        checked={selected.has(q.section)}
                        disabled={!opened || busy}
                        title={opened
                          ? "Include in this attestation"
                          : "Open the draft first — attest only what you have read"}
                        onChange={(e) => {
                          setSelected((s) => {
                            const next = new Set(s);
                            if (e.target.checked) next.add(q.section);
                            else next.delete(q.section);
                            return next;
                          });
                        }} />
                      <code>{q.section}</code> {q.title}
                      {doc && (
                        <a className="chip" style={{ fontSize: 11 }}
                          href={dossierApi.documentUrl(doc.doc_id)}
                          target="_blank" rel="noopener noreferrer"
                          onClick={() =>
                            setOpenedDocs((s) => new Set(s).add(doc.doc_id))}>
                          Open draft{opened ? " ✓" : ""}
                        </a>
                      )}
                    </label>
                  );
                })}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                              alignItems: "center", marginTop: 8 }}>
                  <input value={name} placeholder="Your full name (required)"
                    style={{ width: 200 }} disabled={busy}
                    onChange={(e) => setName(e.target.value)} />
                  <input value={credential}
                    placeholder="Credential / role (e.g. RAC)"
                    style={{ width: 180 }} disabled={busy}
                    onChange={(e) => setCredential(e.target.value)} />
                  <button onClick={bulkAttest}
                    disabled={busy || selected.size === 0 || !name.trim()}>
                    {busy
                      ? "Recording…"
                      : `Attest ${selected.size} reviewed section${selected.size === 1 ? "" : "s"}`}
                  </button>
                </div>
                <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
                  Each attestation means: &ldquo;I have reviewed this AI draft
                  — it is my content&rdquo; and is written to the append-only
                  Part-11 audit trail with your name, credential and a UTC
                  timestamp — one record per section.
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </Disclosure>
  );
}

"use client";
// Round-9 catalog minor — "No bulk create/import or keyboard-fast entry"
// (n=1; cdmo_ra_manager). CSV bulk-create for spinning up dozens of dossiers
// at once. Each row goes through the SAME server-side create gates as the
// form (format, uniqueness/collision, workspace ID convention) — a bulk
// import can't sneak past a single-create rule — and per-row failures are
// reported honestly, row by row, instead of a silent partial import.
import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { toast } from "sonner";
import { catalogApi, type CreateDossierBody } from "./catalogApi";

const HEADER = "dossier_id,title,title_fr,submission_type,cs_be_only,sponsor,owner,labelling_owner";

// Minimal CSV line splitter with double-quote support (no external dep —
// matches the simple artifacts our own exports produce).
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "", inQ = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQ) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') inQ = false;
      else cur += c;
    } else if (c === '"') inQ = true;
    else if (c === ",") { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

type RowResult = { line: number; dossier_id: string; ok: boolean; err?: string };

export function BulkDossierImport({ onDone }: { onDone: () => Promise<void> | void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<RowResult[] | null>(null);

  async function importFile(f: File) {
    setBusy(true);
    setResults(null);
    try {
      const text = await f.text();
      const lines = text.split(/\r?\n/).filter((l) => l.trim());
      if (!lines.length) throw new Error("empty file");
      const cols = splitCsvLine(lines[0]).map((c) => c.toLowerCase());
      if (!cols.includes("dossier_id")) {
        throw new Error(`first line must be a header including dossier_id ` +
          `(template: ${HEADER})`);
      }
      const idx = (name: string) => cols.indexOf(name);
      const out: RowResult[] = [];
      // sequential on purpose: preserves file order, keeps per-row errors
      // attributable, and avoids hammering the create endpoint
      for (let i = 1; i < lines.length; i++) {
        const v = splitCsvLine(lines[i]);
        const get = (name: string) => (idx(name) >= 0 ? v[idx(name)] || "" : "");
        const body: CreateDossierBody = {
          dossier_id: get("dossier_id"),
          title: get("title") || undefined,
          title_fr: get("title_fr") || undefined,
          submission_type: (get("submission_type") || "ANDS").toUpperCase(),
          cs_be_only: !/^(false|0|no)$/i.test(get("cs_be_only") || "true"),
          sponsor: get("sponsor") || undefined,
          owner: get("owner") || undefined,
          labelling_owner: get("labelling_owner") || undefined,
        };
        try {
          await catalogApi.createDossier(body);
          out.push({ line: i + 1, dossier_id: body.dossier_id, ok: true });
        } catch (e) {
          out.push({ line: i + 1, dossier_id: body.dossier_id, ok: false,
            err: String((e as Error)?.message || e) });
        }
      }
      setResults(out);
      const okN = out.filter((r) => r.ok).length;
      toast[okN === out.length ? "success" : "warning"](
        `Bulk import: ${okN}/${out.length} dossiers created`);
      await onDone();
    } catch (e) {
      toast.error(String((e as Error)?.message || e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function template() {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(
      [HEADER + "\ne123456,Drugazole 10 mg tablet,Drugazole comprimé de 10 mg,ANDS,true,Acme Pharma Inc.,j.smith@cro.example,m.tremblay@cro.example\n"],
      { type: "text/csv" }));
    a.download = "dossier-import-template.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center",
        flexWrap: "wrap" }}>
        <button className="ghost" disabled={busy}
          onClick={() => fileRef.current?.click()}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Upload size={14} aria-hidden />
          {busy ? "Importing…" : "Bulk import (CSV)"}
        </button>
        <button className="ghost" style={{ fontSize: 12 }} onClick={template}>
          Download template
        </button>
        <span className="mut" style={{ fontSize: 12 }}>
          each row passes the same format / uniqueness / convention checks as
          the form
        </span>
        <input ref={fileRef} type="file" accept=".csv,text/csv" hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importFile(f);
          }} />
      </div>
      {results && (
        <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0,
          display: "grid", gap: 2, maxHeight: 180, overflowY: "auto" }}>
          {results.map((r) => (
            <li key={r.line} style={{ fontSize: 12 }}
              className={r.ok ? "mut" : "bad-text"}>
              line {r.line} · {r.dossier_id || "(no id)"} —{" "}
              {r.ok ? "created" : r.err}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

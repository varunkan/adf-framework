"use client";
import { useEffect, useRef, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { DocMeta, FeesBlock, SectionNode } from "@/lib/dossierTypes";
import { DraftChat } from "./DraftChat";
import { useDossier } from "./DossierContext";

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function SectionPanel({ node }: { node: SectionNode }) {
  const { dossierId, content, setContent } = useDossier();
  const affs = node.affordances;
  const [tab, setTab] = useState<string>(affs[0] || "upload");
  const [err, setErr] = useState("");
  const [announce, setAnnounce] = useState("");

  useEffect(() => {
    setTab(node.affordances[0] || "upload");
    setErr("");
  }, [node.section]);

  const upload = async (file: File, lang?: string) => {
    setErr("");
    try {
      const c = await dossierApi.uploadDocument(dossierId, node.section, file, {
        lang,
        onProgress: () => {},
      });
      setContent(c);
      setAnnounce(`${file.name} placed in ${node.section}`);
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div className="card glass section-panel">
      <div className="sr-only" aria-live="polite">{announce}</div>
      <div className="eyebrow">
        Module {node.module} · Section {node.section} ·{" "}
        <span className={`applic ${node.applicability}`}>{node.applicability}</span>
      </div>
      <h2 className="step-title">{node.title}</h2>
      <p className="lede">{node.purpose}</p>

      <div className="teach">
        <b>What Health Canada needs here</b>
        <p style={{ margin: "6px 0 0" }}>{node.guidance}</p>
        <div className="guide-meta">
          {node.formats.length > 0 && (
            <span className="fmt">
              Format: {node.formats.map((f) => f.toUpperCase()).join(" + ")}
            </span>
          )}
          {node.bilingual && <span className="fmt">Bilingual: EN + FR</span>}
          <a href={node.source_url} target="_blank" rel="noopener noreferrer">
            Health Canada guidance ↗
          </a>
        </div>
      </div>

      {node.applicability === "na" || node.applicability === "suppressed" ? (
        <div className="notice">
          This section is not applicable for a generic ANDS on the comparative-BE
          pathway — nothing to file here.
        </div>
      ) : affs.length === 0 ? (
        <div className="notice">
          This section is generated automatically as part of the eCTD backbone
          (index.xml / ca-regional.xml) — there is nothing to upload. Open the{" "}
          <b>Application Viewer</b> to see it.
        </div>
      ) : (
        <>
          {/* 1.2.2 carries BOTH the fee status flags and the uploaded fee
              form document — the gate needs the document, so the widget
              renders above the normal upload affordances, not instead. */}
          {node.section === "1.2.2" && (
            <FeesWidget fees={content?.fees} dossierId={dossierId}
              onDone={setContent} />
          )}
          <AttachedDocs node={node} />

          <div className="affordance-bar" role="tablist" aria-label="Actions">
            {affs.includes("upload") && (
              <button role="tab" aria-selected={tab === "upload"}
                className={tab === "upload" ? "on" : ""}
                onClick={() => setTab("upload")}>⬆ Upload</button>
            )}
            {affs.includes("generate") && (
              <button role="tab" aria-selected={tab === "generate"}
                className={tab === "generate" ? "on" : ""}
                onClick={() => setTab("generate")}>✦ Author in-app</button>
            )}
            {affs.includes("mark_na") && (
              <button role="tab" aria-selected={tab === "mark_na"}
                className={tab === "mark_na" ? "on" : ""}
                onClick={() => setTab("mark_na")}>⊘ Mark N/A</button>
            )}
          </div>

          {err && <div className="notice bad">{err}</div>}

          {tab === "upload" &&
            (node.bilingual ? (
              <div className="field-row">
                <Dropzone label="English (EN)" formats={node.formats}
                  onFile={(f) => upload(f, "en")} />
                <Dropzone label="Français (FR)" formats={node.formats}
                  onFile={(f) => upload(f, "fr")} />
              </div>
            ) : (
              <Dropzone formats={node.formats} onFile={(f) => upload(f)} />
            ))}

          {tab === "generate" && (
            <AuthorForm node={node} onDone={(c, msg) => { setContent(c); setAnnounce(msg); }}
              onError={setErr} dossierId={dossierId} />
          )}

          {tab === "mark_na" && (
            <MarkNa node={node} dossierId={dossierId}
              onDone={(c) => { setContent(c); setAnnounce(`${node.section} marked N/A`); }}
              onError={setErr} />
          )}
        </>
      )}
    </div>
  );
}

function AttachedDocs({ node }: { node: SectionNode }) {
  const docs: { lang?: string; meta: DocMeta }[] = [];
  if (node.documents) {
    for (const [lang, meta] of Object.entries(node.documents)) docs.push({ lang, meta });
  } else if (node.document) {
    docs.push({ meta: node.document });
  }
  if (node.action === "na")
    return (
      <div className="notice ok">
        Marked <b>N/A</b>{node.na_reason ? ` — ${node.na_reason}` : ""}.
      </div>
    );
  if (docs.length === 0) return null;
  return (
    <div className="attached">
      {docs.map(({ lang, meta }) => (
        <div key={meta.doc_id} className="attached-doc">
          <span className="ad-icon" aria-hidden>
            {node.action === "generated" ? "✦" : "📄"}
          </span>
          <span className="ad-name">
            {lang ? <b className="ad-lang">{lang.toUpperCase()}</b> : null} {meta.filename}
          </span>
          <span className="ad-meta mut">
            {fmtSize(meta.size)} · md5 {meta.checksum.slice(0, 8)}…
            {node.action === "generated" ? " · authored" : ""}
          </span>
          <a className="ad-dl" href={dossierApi.documentUrl(meta.doc_id)}
            target="_blank" rel="noopener noreferrer">Download</a>
        </div>
      ))}
    </div>
  );
}

function Dropzone({
  label,
  formats,
  onFile,
}: {
  label?: string;
  formats: string[];
  onFile: (f: File) => void | Promise<void>;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const accept = formats.map((f) => `.${f}`).join(",");

  const handle = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true);
    try {
      await onFile(f);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ flex: 1 }}>
      {label && <label>{label}</label>}
      <div
        className={`dropzone ${over ? "over" : ""} ${busy ? "busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          handle(e.dataTransfer.files?.[0]);
        }}
        onClick={() => ref.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ref.current?.click(); }
        }}
      >
        <input ref={ref} type="file" accept={accept} className="sr-only"
          onChange={(e) => handle(e.target.files?.[0] || undefined)} />
        {busy ? "Uploading…" : (
          <>
            <b>Drop a file</b> or click to choose
            <div className="mut" style={{ fontSize: 12 }}>
              {formats.map((f) => f.toUpperCase()).join(" / ")}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function AuthorForm({
  node,
  dossierId,
  onDone,
  onError,
}: {
  node: SectionNode;
  dossierId: string;
  onDone: (c: any, msg: string) => void;
  onError: (e: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const set = (k: string, v: string) => setFields((f) => ({ ...f, [k]: v }));
  const aiDraftable = !!node.ai_draftable;
  const [mode, setMode] = useState<"ai" | "template">(aiDraftable ? "ai" : "template");

  // A few relevant inputs per generator; all optional (the doc also pulls from
  // the dossier's product/identity context).
  const EXTRA: Record<string, { key: string; label: string }[]> = {
    patent_form_iv: [
      { key: "crp_brand", label: "Reference product (brand)" },
      { key: "patents", label: "Patent / CSP numbers" },
    ],
    cs_be: [
      { key: "crp_brand", label: "Canadian Reference Product" },
      { key: "auc_ci", label: "AUC 90% CI (e.g. 92–108%)" },
      { key: "cmax", label: "Cmax 90% CI / point estimate" },
    ],
  };
  const extra = EXTRA[node.generator_key || ""] || [];

  async function go() {
    setBusy(true);
    try {
      const c = await dossierApi.generate(dossierId, node.section, fields);
      onDone(c, `${node.title} authored`);
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (aiDraftable) {
    return (
      <div className="author-form">
        <div className="affordance-bar" role="tablist" aria-label="Drafting mode">
          <button role="tab" aria-selected={mode === "ai"}
            className={mode === "ai" ? "on" : ""}
            onClick={() => setMode("ai")}>💬 Draft with AI</button>
          <button role="tab" aria-selected={mode === "template"}
            className={mode === "template" ? "on" : ""}
            onClick={() => setMode("template")}>✦ Quick template</button>
        </div>
        {mode === "ai" ? (
          <DraftChat node={node} dossierId={dossierId} onDone={onDone} onError={onError} />
        ) : (
          <>
            <p className="mut" style={{ fontSize: 13 }}>
              Generate a boilerplate draft from your dossier details. Missing
              fields show as "—" — review and finalise before filing.
            </p>
            {extra.map((f) => (
              <div key={f.key}>
                <label>{f.label}</label>
                <input value={fields[f.key] || ""}
                  onChange={(e) => set(f.key, e.target.value)} />
              </div>
            ))}
            <div className="cta-row">
              <button onClick={go} disabled={busy}>
                {busy ? "Authoring…" : `Author ${node.title} →`}
              </button>
            </div>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="author-form">
      <p className="mut" style={{ fontSize: 13 }}>
        Generate a draft of this document from your dossier details. Review and
        finalise it before signing/filing.
      </p>
      {extra.map((f) => (
        <div key={f.key}>
          <label>{f.label}</label>
          <input value={fields[f.key] || ""}
            onChange={(e) => set(f.key, e.target.value)} />
        </div>
      ))}
      <div className="cta-row">
        <button onClick={go} disabled={busy}>
          {busy ? "Authoring…" : `Author ${node.title} →`}
        </button>
      </div>
    </div>
  );
}

function FeesWidget({
  fees,
  dossierId,
  onDone,
}: {
  fees?: FeesBlock;
  dossierId: string;
  onDone: (c: any) => void;
}) {
  const [feePaid, setFeePaid] = useState(fees?.fee_paid || false);
  const [sme, setSme] = useState(fees?.sme_granted || false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setFeePaid(fees?.fee_paid || false);
    setSme(fees?.sme_granted || false);
  }, [fees?.fee_paid, fees?.sme_granted]);

  async function save(nextPaid: boolean, nextSme: boolean) {
    setBusy(true);
    try {
      onDone(await dossierApi.setFees(dossierId, nextPaid, nextSme));
    } finally {
      setBusy(false);
    }
  }
  if (!fees) return <div className="mut">Loading fee…</div>;
  const fee = fees.review_fee;
  const m = fees.mitigation;
  return (
    <div className="fees-widget">
      <div className="notice">
        Current ANDS review fee ({fee.fiscal_year}):{" "}
        <b>${fee.amount.toLocaleString()} {fee.currency}</b>
        {m.waived ? (
          <> — <b>waived</b> (first-ever submission).</>
        ) : m.reduction ? (
          // m.reduction is a DOLLAR amount (see fees.small_business_mitigation)
          <> — small-business payable{" "}
            <b>${m.payable.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</b>{" "}
            ({Math.round((m.reduction / fee.amount) * 100)}% reduction).</>
        ) : null}
        <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>{m.note}</div>
      </div>
      <div className="notice">
        Right to Sell (annual): ${fees.right_to_sell.amount.toLocaleString()} —
        due {fees.right_to_sell.due_date}.
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input type="checkbox" style={{ width: "auto" }} checked={sme}
          disabled={busy}
          onChange={(e) => { setSme(e.target.checked); save(feePaid, e.target.checked); }} />
        <span>Small-business status is <b>granted</b> (before filing)</span>
      </label>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
        <input type="checkbox" style={{ width: "auto" }} checked={feePaid}
          disabled={busy}
          onChange={(e) => { setFeePaid(e.target.checked); save(e.target.checked, sme); }} />
        <span>Fee payment is arranged</span>
      </label>
    </div>
  );
}

function MarkNa({
  node,
  dossierId,
  onDone,
  onError,
}: {
  node: SectionNode;
  dossierId: string;
  onDone: (c: any) => void;
  onError: (e: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      onDone(await dossierApi.markNa(dossierId, node.section, reason));
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <label>Why is this section not applicable? (optional)</label>
      <input value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder="e.g. no prior related applications" />
      <div className="cta-row">
        <button className="ghost" onClick={go} disabled={busy}>
          {busy ? "Saving…" : "Mark this section N/A"}
        </button>
      </div>
    </div>
  );
}

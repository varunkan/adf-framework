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
          {node.section === "1.3.1" && (
            <PmXmlPanel dossierId={dossierId} title={content?.dossier_id || ""} />
          )}
          <AttachedDocs
            node={node}
            dossierId={dossierId}
            onConfirm={(c) => {
              setContent(c);
              setAnnounce(`${node.section} confirmed as your reviewed content`);
            }}
            onError={setErr}
          />

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

// The honest AI provenance tooltip: what the chip means + where AI-processed
// dossier text goes and how per-sponsor isolation holds. md5 is NOT claimed as
// validation anywhere — it is only a content fingerprint.
const AI_PROVENANCE_TOOLTIP =
  "Drafted interactively with the AI assistant under your direction, and " +
  "recorded in the audit trail. Data residency: your dossier text is sent to " +
  "the configured AI provider for this draft only, isolated per sponsor — it " +
  "is never shared across clients or used to train models. This is assistance, " +
  "not a filing: review it against the Health Canada guidance and confirm it " +
  "as your own content before filing.";

function AttachedDocs({
  node,
  dossierId,
  onConfirm,
  onError,
}: {
  node: SectionNode;
  dossierId: string;
  onConfirm: (c: any) => void;
  onError: (e: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
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

  // WS2 SAFETY: a persistent, sighted-visible blocking banner on the saved
  // document card whenever this section holds an unconfirmed sample/AI draft.
  // This is NOT a screen-reader-only region — it must block the eye too.
  const needsReview = !!node.needs_review;
  const isAi = node.content_origin === "ai_draft";

  async function confirm() {
    setConfirming(true);
    try {
      onConfirm(await dossierApi.confirmContent(dossierId, node.section));
    } catch (e) {
      onError(String(e));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="attached">
      {needsReview && (
        <div className="notice bad" role="status"
          style={{ marginBottom: 10 }}>
          <b>⚠ Not yet filable — review required.</b>{" "}
          {isAi
            ? "This is an AI-assisted draft. It will "
            : "This section still shows worked-example (sample) values. It will "}
          <b>not</b> count as complete and the submission cannot be exported
          until{" "}
          {isAi ? (
            <>
              you review it against the Health Canada guidance and attest it as
              your own content:
              <div style={{ marginTop: 8 }}>
                <button onClick={confirm} disabled={confirming}>
                  {confirming
                    ? "Recording…"
                    : "I have reviewed this AI draft — it is my content"}
                </button>
              </div>
            </>
          ) : (
            <>
              you <b>replace every example value</b> in the form above with your
              product&apos;s real data and re-author. The example is detected
              server-side, so it clears automatically once no example values
              remain — there is nothing to &ldquo;confirm&rdquo; while the
              worked example is still in place.
            </>
          )}
        </div>
      )}
      {docs.map(({ lang, meta }) => (
        <div key={meta.doc_id} className="attached-doc">
          <span className="ad-icon" aria-hidden>
            {meta.origin === "ai_draft" ? "💬"
              : node.action === "generated" ? "✦" : "📄"}
          </span>
          <span className="ad-name">
            {lang ? <b className="ad-lang">{lang.toUpperCase()}</b> : null} {meta.filename}
          </span>
          <span className="ad-meta mut">
            {/* md5 is a content fingerprint (matches the placed leaf), NOT a
                validation or acceptance signal — labelled as such. */}
            {fmtSize(meta.size)} · fingerprint md5 {meta.checksum.slice(0, 8)}…
          </span>
          {/* provenance travels with every document — who/what produced it,
              and whether the filer has confirmed it as their own content. */}
          <span
            className={`chip ${needsReview ? "blocked" : "ready"}`}
            style={{ fontSize: 11 }}
            title={isAi
              ? AI_PROVENANCE_TOOLTIP
              : node.content_origin === "sample"
              ? "Filled from a worked example (sample) using a deterministic Health Canada template. Replace the sample values with your product's real data, then confirm it as your content before filing."
              : meta.origin === "generated"
              ? "Produced in-app from your entries by a deterministic Health Canada template."
              : "Uploaded by your team — content is exactly what you provided."}>
            {needsReview
              ? (isAi ? "AI draft — review & confirm" : "sample — review & confirm")
              : node.content_confirmed && (isAi || node.content_origin === "sample")
              ? (isAi ? "AI-assisted · confirmed" : "authored in-app · confirmed")
              : meta.origin === "generated" ? "authored in-app"
              : "uploaded"}
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

// human labels for the sample/editable fields (any extra keys fall back to a
// prettified key name)
const FIELD_LABELS: Record<string, string> = {
  drug_product: "Drug product", dossier_id: "Dossier ID",
  company_id: "Health Canada Company ID", sponsor: "Sponsor company",
  din: "DIN (assigned at NOC)", sequence: "Sequence", activity_type: "Activity type",
  contact_name: "Regulatory contact", contact_email: "Contact email",
  sequence_description: "Sequence description", dossier_type: "Dossier type",
  crp_brand: "Canadian Reference Product (brand)", crp_din: "Reference product DIN",
  patents: "Patent / CSP numbers on the Register", patent_expiry: "Expiry (per patent)",
  allegation: "s.5 statement (per patent)", signer: "Authorised signer",
  signer_title: "Signer title", dosage_form: "Dosage form", strength: "Strength",
  study_design: "BE study design", auc_ci: "AUC 90% CI",
  cmax: "Cmax 90% CI / point estimate", ruleset: "BE ruleset",
  manufacturer: "Manufacturer", shelf_life: "Proposed shelf life", storage: "Storage",
};
const prettyLabel = (k: string) =>
  FIELD_LABELS[k] || k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

function ReviewPanel({ review }: { review: any }) {
  if (!review) return null;
  const f = review.findings || [];
  return (
    <div className={`notice ${review.passed ? "ok" : "bad"}`} style={{ marginTop: 10 }}>
      <b>Health Canada review:</b>{" "}
      {review.passed
        ? "no blocking content gaps."
        : `${review.error_count} to fix, ${review.warning_count} to check.`}
      {f.length > 0 && (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          {f.map((x: any, i: number) => (
            <li key={i} style={{ marginBottom: 6, fontSize: 12 }}>
              <b>{x.severity === "error" ? "✗" : "⚠"} {x.message}</b>
              <div className="mut">↳ {x.suggested_edit}{" "}
                {x.hc_url && (
                  <a href={x.hc_url} target="_blank" rel="noopener noreferrer">
                    HC guidance ↗
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
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
  // real dossier facts pre-fill as saved values; sample keys start EMPTY and
  // show the worked example only as a ghost placeholder (never saved content).
  const [fields, setFields] = useState<Record<string, string>>({});
  const [ghosts, setGhosts] = useState<Record<string, string>>({});
  const [order, setOrder] = useState<string[]>([]);
  const [sampleKeys, setSampleKeys] = useState<Set<string>>(new Set());
  const [review, setReview] = useState<any>(null);
  const set = (k: string, v: string) => setFields((f) => ({ ...f, [k]: v }));
  const aiDraftable = !!node.ai_draftable;
  const [mode, setMode] = useState<"ai" | "template">(aiDraftable ? "ai" : "template");

  // pull the realistic sample. Real dossier facts become editable values; each
  // sample/example key becomes a GHOST placeholder on an empty field, so the
  // example is not saved content the filer can forget to replace.
  useEffect(() => {
    let live = true;
    setReview(null);
    dossierApi.formSample(dossierId, node.section).then((s) => {
      if (!live) return;
      const sk = new Set(s.sample_keys || []);
      const all = s.fields || {};
      const real: Record<string, string> = {};
      const ghost: Record<string, string> = {};
      for (const [k, v] of Object.entries(all)) {
        if (sk.has(k)) ghost[k] = v;   // worked example → ghost placeholder
        else real[k] = v;              // dossier's own fact → editable value
      }
      setFields(real);
      setGhosts(ghost);
      setOrder(Object.keys(all));
      setSampleKeys(sk);
    }).catch(() => {});
    return () => { live = false; };
  }, [dossierId, node.section]);

  // Any sample-key field the filer left blank falls back to the ghost example
  // on author. Whether the fill still carries worked-example values is decided
  // SERVER-SIDE (it re-derives which fields equal the example and blocks until
  // confirmed) — the client does not send, and the server does not trust, a
  // sample-origin flag. So an unreplaced example is always caught.
  function payload(): Record<string, any> {
    const merged: Record<string, string> = { ...fields };
    for (const k of sampleKeys) {
      if (!((merged[k] || "").trim()) && ghosts[k]) merged[k] = ghosts[k];
    }
    return merged;
  }

  async function runReview(): Promise<boolean> {
    try {
      const r = await dossierApi.formReview(dossierId, node.section, payload());
      setReview(r);
      return r.passed;
    } catch (e) {
      onError(String(e));
      return false;
    }
  }

  async function go() {
    setBusy(true);
    try {
      const p = payload();
      const c = await dossierApi.generate(dossierId, node.section, p);
      onDone(c, p.sample_origin
        ? `${node.title} drafted from the sample — review it against the ` +
          "Health Canada guidance and confirm it as your content before filing."
        : `${node.title} authored`);
      await runReview();   // surface HC content review right after authoring
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const formBody = (
    <>
      <p className="mut" style={{ fontSize: 13 }}>
        <b>Author in-app</b> produces a PDF/A leaf placed at this section's eCTD
        position (lifecycle operation: <i>new</i>). Your dossier's known facts
        are pre-filled; fields marked <i>sample</i> show a <b>ghost example</b>{" "}
        you must replace with your product's real data — the example is never
        saved as your content, and any left unreplaced keeps this section
        blocked until you confirm it.
      </p>
      {order.map((k) => {
        const multiline = k === "allegation" || k === "study_design";
        const isSample = sampleKeys.has(k);
        const ph = isSample ? `e.g. ${ghosts[k] || ""}` : undefined;
        return (
          <div key={k}>
            <label>
              {prettyLabel(k)}{" "}
              {isSample && <span className="applic optional">sample — replace</span>}
            </label>
            {multiline ? (
              <textarea rows={2} value={fields[k] || ""} placeholder={ph}
                onChange={(e) => set(k, e.target.value)} />
            ) : (
              <input value={fields[k] || ""} placeholder={ph}
                onChange={(e) => set(k, e.target.value)} />
            )}
          </div>
        );
      })}
      <div className="cta-row">
        <button onClick={go} disabled={busy}>
          {busy ? "Authoring…" : `Author ${node.title} →`}
        </button>
        <button className="ghost" onClick={runReview} disabled={busy}>
          Review vs Health Canada
        </button>
      </div>
      <ReviewPanel review={review} />
    </>
  );

  if (aiDraftable) {
    return (
      <div className="author-form">
        {/* Two ways to draft the SAME leaf; each keeps its own Review action so
            the filer reviews in the mode they drafted in. Both save an
            unconfirmed draft that the review/confirm banner (on the saved-doc
            card above) then blocks until confirmed. */}
        <div className="affordance-bar" role="tablist" aria-label="How to draft this section">
          <button role="tab" aria-selected={mode === "ai"}
            className={mode === "ai" ? "on" : ""}
            onClick={() => setMode("ai")}>💬 Draft with AI</button>
          <button role="tab" aria-selected={mode === "template"}
            className={mode === "template" ? "on" : ""}
            onClick={() => setMode("template")}>✦ Fill the form</button>
        </div>
        {mode === "ai" ? (
          <DraftChat node={node} dossierId={dossierId} onDone={onDone} onError={onError} />
        ) : (
          formBody
        )}
      </div>
    );
  }

  return <div className="author-form">{formBody}</div>;
}

function PmXmlPanel({ dossierId }: { dossierId: string; title?: string }) {
  const { index } = useDossier();
  const [lang, setLang] = useState<"en" | "fr">("en");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ xml: string; validation: any } | null>(null);

  async function build() {
    setBusy(true);
    try {
      setResult(await dossierApi.buildPmXml({
        dossier_id: dossierId, lang,
        product_name: index?.title || dossierId, din: index?.din || "",
        sections: [
          { code: "indications", title: "Indications",
            text: "See the attached Product Monograph." },
          { code: "contraindications", title: "Contraindications",
            text: "See the attached Product Monograph." },
          { code: "dosage", title: "Dosage and Administration",
            text: "See the attached Product Monograph." },
        ],
      }));
    } finally {
      setBusy(false);
    }
  }

  const findings = result?.validation?.findings || [];
  return (
    <details className="teach" style={{ marginTop: 8 }}>
      <summary><b>XML Product Monograph</b> — build &amp; validate (HC mandate
        is phasing in for generics)</summary>
      <div className="cta-row" style={{ marginTop: 8 }}>
        <select value={lang} onChange={(e) => setLang(e.target.value as any)}
          style={{ width: "auto" }} aria-label="XML PM language">
          <option value="en">EN</option>
          <option value="fr">FR</option>
        </select>
        <button onClick={build} disabled={busy}>
          {busy ? "Building…" : "Build & validate XML PM"}
        </button>
        {result && (
          <a className="chip" download={`pm-${lang}.xml`}
            href={`data:application/xml;charset=utf-8,${encodeURIComponent(result.xml)}`}>
            ⬇ pm-{lang}.xml
          </a>
        )}
      </div>
      {result && (
        <div className={`notice ${result.validation?.valid ? "ok" : "bad"}`}
          style={{ marginTop: 8 }}>
          {result.validation?.valid
            ? "✓ XML PM validates against the stylesheet package."
            : `✗ ${findings.length} finding(s): ` + findings.slice(0, 3)
                .map((f: any) => f.rule).join(", ")}
        </div>
      )}
    </details>
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

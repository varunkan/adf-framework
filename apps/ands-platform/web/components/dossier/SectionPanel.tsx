"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import type { CurrentViewLeaf, DocMeta, FeesBlock, SectionNode } from "@/lib/dossierTypes";
import { DraftChat } from "./DraftChat";
import { FormFill } from "./FormFill";
import { EctdPrimer } from "./EctdPrimer";
import { useDossier } from "./DossierContext";
import { Disclosure } from "../Disclosure";
import { Upload, Sparkles, Ban, AlertTriangle, FileSearch } from "lucide-react";
import { toast } from "sonner";
import { MODULE_4_NOTE, citeLine } from "@/lib/regCitations";
import { opMeta } from "@/lib/leafStatus";

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function SectionPanel({ node, op }: { node: SectionNode; op?: string }) {
  const { dossierId, content, setContent } = useDossier();
  const affs = node.affordances;
  const [tab, setTab] = useState<string>(affs[0] || "upload");
  const [err, setErr] = useState("");
  const [announce, setAnnounce] = useState("");
  const stepTitleRef = useRef<HTMLHeadingElement>(null);

  // P2-4: pull keyboard focus into the panel when the selected leaf changes so
  // a keyboard user is not left back on the tree row — BUT never steal focus
  // while the user is arrow-scanning the tree itself (that would break the
  // continuous top-to-bottom scan). Only grab focus when it currently sits
  // outside the section tree (e.g. after a click, or a programmatic select).
  useEffect(() => {
    const inTree = document.activeElement?.closest?.(".section-tree");
    if (!inTree) stepTitleRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.section]);

  // Route every failure through a toast as well as the inline notice (P1-3).
  function fail(e: unknown) {
    const msg = String(e);
    setErr(msg);
    toast.error(msg);
  }

  useEffect(() => {
    // Reset the active tab to the section's first affordance ONLY when the
    // section changes — not on every render (node.affordances is a fresh array
    // reference each render, so depending on it would clobber the user's tab).
    setTab(node.affordances[0] || "upload");
    setErr("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.section]);

  const upload = async (file: File, lang?: string) => {
    setErr("");
    try {
      const c = await dossierApi.uploadDocument(dossierId, node.section, file, {
        lang,
        onProgress: () => {},
      });
      setContent(c);
      const msg = `${file.name} placed at leaf ${node.section}`;
      setAnnounce(msg);
      toast.success(msg);
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div className="card glass section-panel">
      <div className="sr-only" aria-live="polite">{announce}</div>
      <div className="eyebrow">
        Module {node.module} · Section {node.section} ·{" "}
        <span className={`applic ${node.applicability}`}>{node.applicability}</span>
        {/* R9 DENSITY: the concrete eCTD placement (folder / leaf id) is real
            substance but not first-view chrome — it moved down into the "eCTD
            placement" expander (Node placement + Leaf id rows), so the eyebrow
            reads calm and the leaf/folder detail is one click away. */}
      </div>
      <h2 className="step-title" ref={stepTitleRef} tabIndex={-1}>
        {node.title}
      </h2>
      <p className="lede">{node.purpose}</p>

      <div className="teach">
        <b>What Health Canada needs here</b>
        <p style={{ margin: "6px 0 0" }}>{node.guidance}</p>
        {/* Round-6 WS-A (density reduction): the format / bilingual / source
            reference chips are secondary detail — collapse them so the primary
            guidance reads clean. The safety/review banner and the actionable
            affordances below are never collapsed. */}
        <Disclosure
          showLabel="Format & source"
          hideLabel="Hide format & source"
          summary={
            <span>
              {node.formats.length > 0
                ? `${node.formats.map((f) => f.toUpperCase()).join(" + ")}`
                : "Reference"}
              {node.bilingual ? " · bilingual EN + FR" : ""}
            </span>
          }
        >
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
        </Disclosure>
        <EctdPrimer compact dossierId={dossierId} />
      </div>

      {node.applicability === "na" || node.applicability === "suppressed" ? (
        <div className="notice">
          This section is not applicable for a generic ANDS on the comparative-BE
          pathway — nothing to file here.
          {String(node.module) === "4" && (
            <div className="mut" style={{ fontSize: 12, marginTop: 6 }}>
              {MODULE_4_NOTE.conditional} {MODULE_4_NOTE.exception}
              <div style={{ marginTop: 4 }}>{citeLine(MODULE_4_NOTE)}</div>
            </div>
          )}
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
              const msg = `${node.section} confirmed as your content`;
              setAnnounce(msg);
              toast.success(msg);
            }}
            onError={fail}
          />

          {/* P1-8 — real toggle-button group (not a false tablist): the panel
              below is switched in place, so `aria-pressed` matches the keyboard
              behaviour where `role=tab` would have promised arrow-key roving. */}
          <div className="affordance-bar" role="group" aria-label="Choose how to complete this section">
            {affs.includes("upload") && (
              <button type="button" aria-pressed={tab === "upload"}
                className={tab === "upload" ? "on" : ""}
                onClick={() => setTab("upload")}><Upload size={14} aria-hidden /> Upload</button>
            )}
            {affs.includes("generate") && (
              <button type="button" aria-pressed={tab === "generate"}
                className={tab === "generate" ? "on" : ""}
                onClick={() => setTab("generate")}><Sparkles size={14} aria-hidden /> Author in-app</button>
            )}
            {affs.includes("mark_na") && (
              <button type="button" aria-pressed={tab === "mark_na"}
                className={tab === "mark_na" ? "on" : ""}
                onClick={() => setTab("mark_na")}><Ban size={14} aria-hidden /> Mark N/A</button>
            )}
          </div>

          {err && <div className="notice bad" role="alert">{err}</div>}

          {tab === "upload" &&
            (node.bilingual ? (
              <div className="field-row">
                <Dropzone label="English (EN)" formats={node.formats}
                  ariaLabel={`Upload English (EN) document for section ${node.section} — ${node.formats.map((f) => f.toUpperCase()).join("/")}`}
                  onFile={(f) => upload(f, "en")} />
                <Dropzone label="Français (FR)" formats={node.formats}
                  ariaLabel={`Upload French (FR) document for section ${node.section} — ${node.formats.map((f) => f.toUpperCase()).join("/")}`}
                  onFile={(f) => upload(f, "fr")} />
              </div>
            ) : (
              <Dropzone formats={node.formats}
                ariaLabel={`Upload document for section ${node.section} — ${node.formats.map((f) => f.toUpperCase()).join("/")}`}
                onFile={(f) => upload(f)} />
            ))}

          {tab === "generate" && (
            <AuthorForm node={node} op={op}
              onDone={(c, msg) => { setContent(c); setAnnounce(msg); toast.success(msg); }}
              onError={fail} dossierId={dossierId} />
          )}

          {tab === "mark_na" && (
            <MarkNa node={node} dossierId={dossierId}
              onDone={(c) => {
                setContent(c);
                const msg = `${node.section} marked N/A`;
                setAnnounce(msg); toast.success(msg);
              }}
              onError={fail} />
          )}
        </>
      )}

      {/* R9 DENSITY (builder_forms ease/trust regression): the real eCTD
          substance — leaf id, href, node placement, lifecycle operation written
          to the backbone XML, plus the honest PDF/A scope note — is kept in full
          but sits BELOW the task and behind a collapsed "eCTD placement"
          expander (closed by default). The first view now shows the task
          (upload / author / mark N/A + the one-line purpose) first; the depth is
          one click away. MAJOR (n=8) wants real eCTD, not eye-candy — it is all
          still here, just not forced into the first view. Lazily loaded on
          expand so it never slows the primary form. */}
      {node.leaf_id && (
        <EctdPlacement node={node} op={op} dossierId={dossierId} />
      )}
    </div>
  );
}

// one label/value row inside the eCTD placement grid.
function PlaceRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="mut" style={{ margin: 0 }}>{label}</dt>
      <dd style={{ margin: 0, wordBreak: "break-all" }}>{children}</dd>
    </>
  );
}

// MAJOR (n=8): real eCTD substance in the builder — the leaf id, href, and
// lifecycle operation as WRITTEN TO THE BACKBONE XML for this section, plus an
// explicit statement of the operation against the prior active sequence. Also
// carries the honest PDF/A scope note (MAJOR): what the tool checks vs. what it
// does NOT. Loaded lazily on expand from the live current-view so it reflects
// the same operators the eValidator handoff / Application Viewer show.
function EctdPlacement({
  node,
  op,
  dossierId,
}: {
  node: SectionNode;
  op?: string;
  dossierId: string;
}) {
  const [open, setOpen] = useState(false);
  const [leaf, setLeaf] = useState<CurrentViewLeaf | null>(null);
  const [history, setHistory] = useState<CurrentViewLeaf[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || loaded) return;
    let live = true;
    dossierApi
      .currentView(dossierId)
      .then((cv) => {
        if (!live) return;
        setLeaf(cv.live.find((l) => l.leaf_id === node.leaf_id) || null);
        setHistory(cv.history.filter((l) => l.leaf_id === node.leaf_id));
        setLoaded(true);
      })
      .catch((e) => {
        if (!live) return;
        setErr(String(e));
        setLoaded(true);
      });
    return () => {
      live = false;
    };
  }, [open, loaded, dossierId, node.leaf_id]);

  // The operation this leaf carries (from the live view once loaded, else the
  // parent-supplied hint). replace/append/delete act against a prior active
  // sequence — spell that out explicitly (MAJOR: replace/append clarity).
  const operation = leaf?.operation || op || "new";
  const om = opMeta(operation);
  const actsOnPrior = operation === "replace" || operation === "append" || operation === "delete";

  return (
    <Disclosure
      className="ectd-placement"
      showLabel="Show eCTD placement & lifecycle"
      hideLabel="Hide eCTD placement & lifecycle"
      open={open}
      onOpenChange={setOpen}
      summary={
        <span>
          <FileSearch size={13} aria-hidden style={{ verticalAlign: "-2px", marginRight: 5 }} />
          <b>eCTD placement</b> — leaf, href &amp; lifecycle operation
          {om ? (
            <span className={om.risk ? "t-op warn" : "t-op"} style={{ marginLeft: 8 }}>
              {om.label}
            </span>
          ) : null}
        </span>
      }
    >
      {!loaded ? (
        <div className="mut" style={{ fontSize: 12 }}>Loading placement…</div>
      ) : err ? (
        <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>
      ) : (
        <div className="ectd-place-body">
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: "4px 12px",
              margin: 0,
              fontSize: 12,
              alignItems: "baseline",
            }}
          >
            <PlaceRow label="Leaf id"><code>{node.leaf_id}</code></PlaceRow>
            <PlaceRow label="Node placement">{node.folder || "—"}</PlaceRow>
            <PlaceRow label="href (path in package)">
              {leaf?.href ? (
                <code>{leaf.href}</code>
              ) : (
                <span className="mut">
                  not written yet — placed into the backbone once a document is
                  attached at this leaf
                </span>
              )}
            </PlaceRow>
            <PlaceRow label="Sequence">
              <code>{leaf?.sequence || "0000"}</code>{" "}
              <span className="mut">
                {(leaf?.sequence || "0000") === "0000"
                  ? "(original working sequence)"
                  : "(amendment / response sequence)"}
              </span>
            </PlaceRow>
            <PlaceRow label="Lifecycle operation">
              <span className={om?.risk ? "t-op warn" : "t-op"}>{om?.label || operation.toUpperCase()}</span>{" "}
              <b>{om?.word || operation}</b>
            </PlaceRow>
            <PlaceRow label="File fingerprint (md5)">
              {leaf?.checksum ? (
                <code title="md5 is a content fingerprint that matches the placed leaf — document control, NOT validation or acceptance.">
                  {leaf.checksum.slice(0, 12)}…
                </code>
              ) : (
                <span className="mut">—</span>
              )}
            </PlaceRow>
          </dl>

          {/* MAJOR: make the operation against a prior active sequence explicit
              per leaf — new (nothing to supersede) vs replace/append/delete
              acting on an earlier transmitted document. */}
          <div className={`notice ${actsOnPrior ? "warn" : ""}`} style={{ fontSize: 12, marginTop: 8 }}>
            {operation === "new" && (
              <>This leaf is filed <b>new</b> — there is no prior active
              sequence it supersedes.</>
            )}
            {operation === "replace" && (
              <><b>Replace</b> — this leaf supersedes an earlier document
              already transmitted in an active sequence. The backbone XML records
              the replace operation so Health Canada&apos;s reviewer sees the new
              document in place of the old one.
              {leaf?.modified_leaf ? (
                <> Replaces leaf <code>{leaf.modified_leaf}</code>.</>
              ) : null}</>
            )}
            {operation === "append" && (
              <><b>Append</b> — this leaf is added <i>alongside</i> a prior
              active leaf, not replacing it; both remain part of the record.
              {leaf?.modified_leaf ? (
                <> Appends to leaf <code>{leaf.modified_leaf}</code>.</>
              ) : null}</>
            )}
            {operation === "delete" && (
              <><b>Delete</b> — this withdraws a document from a prior active
              sequence. It stays in the audit history but is removed from the
              current view.
              {leaf?.modified_leaf ? (
                <> Withdraws leaf <code>{leaf.modified_leaf}</code>.</>
              ) : null}</>
            )}
          </div>

          {history.length > 0 && (
            <div className="mut" style={{ fontSize: 12, marginTop: 6 }}>
              Prior versions of this leaf in the lifecycle history:{" "}
              {history.map((h) => (
                <code key={`${h.sequence}-${h.leaf_id}`} style={{ marginRight: 6 }}>
                  {h.operation}@{h.sequence}
                </code>
              ))}
            </div>
          )}

          {/* MAJOR (PDF/A honesty): state EXACTLY what is checked vs. not. This
              mirrors the server-side rule (CA-E-7001 %PDF header, CA-E-7002 not
              /Encrypt) and never claims full PDF/A-1b conformance. */}
          <div className="teach" style={{ fontSize: 12, marginTop: 8 }}>
            <b>PDF/A — what this tool actually checks</b>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              <li>
                ✓ the file really is a PDF (starts with the <code>%PDF</code>{" "}
                header)
              </li>
              <li>
                ✓ the PDF is <b>not encrypted / password-protected</b> (Health
                Canada rejects <code>/Encrypt</code>)
              </li>
              <li>
                ✗ <b>Full PDF/A-1b conformance is NOT verified here.</b> Font
                embedding, colour profiles and the rest of the archival profile
                are checked by HC eValidator and your publisher — not by ANDS
                Studio. Run eValidator before you transmit.
              </li>
            </ul>
          </div>

          <div style={{ marginTop: 8 }}>
            <Link
              href={`/dossiers/${encodeURIComponent(dossierId)}/viewer`}
              className="chip"
              title="Open the read-only Application Viewer: index.xml / ca-regional.xml backbone and every leaf at its href with checksums."
            >
              Inspect the backbone &amp; XML — Application Viewer
            </Link>
          </div>
        </div>
      )}
    </Disclosure>
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
      toast.success(`${node.section} confirmed as your reviewed content`);
    } catch (e) {
      onError(String(e));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="attached">
      {needsReview && (
        <div className="notice bad review-banner" role="status"
          style={{ marginBottom: 10 }}>
          <AlertTriangle size={16} aria-hidden className="review-banner-ic" />
          <span>
          <b>Not yet filable — review required.</b>{" "}
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
          </span>
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
            style={{ fontSize: 12 }}
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
  ariaLabel,
}: {
  label?: string;
  formats: string[];
  onFile: (f: File) => void | Promise<void>;
  ariaLabel?: string;
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
        aria-label={ariaLabel}
        aria-busy={busy}
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

// The "Author in-app" panel. Every content section is now form-fillable: the
// schema-driven FormFill component renders each field by type, offers per-prose-
// field AI drafting, and generates the document into the eCTD leaf. For a whole-
// document AI-draftable prose doc (e.g. the cover letter / Form V), the filer can
// ALSO draft the entire document conversationally — the "Draft with AI" (chat)
// vs "Fill the form" toggle. Both save an unconfirmed draft the review/confirm
// gate on the saved-doc card then blocks until confirmed.
function AuthorForm({
  node,
  op,
  dossierId,
  onDone,
  onError,
}: {
  node: SectionNode;
  op?: string;
  dossierId: string;
  onDone: (c: any, msg: string) => void;
  onError: (e: string) => void;
}) {
  const aiDraftable = !!node.ai_draftable;
  const [mode, setMode] = useState<"ai" | "template">(aiDraftable ? "ai" : "template");

  // reset to the section's default mode when the section changes.
  useEffect(() => {
    setMode(aiDraftable ? "ai" : "template");
  }, [node.section, aiDraftable]);

  const formFill = (
    <FormFill node={node} op={op} dossierId={dossierId}
      onDone={onDone} onError={onError} />
  );

  if (aiDraftable) {
    return (
      <div className="author-form">
        {/* Two ways to author the SAME leaf: a conversational whole-document AI
            draft, or the structured form (with per-field AI drafting). */}
        <div className="affordance-bar" role="group" aria-label="How to author this section">
          <button type="button" aria-pressed={mode === "ai"}
            className={mode === "ai" ? "on" : ""}
            onClick={() => setMode("ai")}>💬 Draft with AI</button>
          <button type="button" aria-pressed={mode === "template"}
            className={mode === "template" ? "on" : ""}
            onClick={() => setMode("template")}><Sparkles size={14} aria-hidden /> Fill the form</button>
        </div>
        {mode === "ai" ? (
          <DraftChat node={node} dossierId={dossierId} onDone={onDone}
            onError={onError} onFallback={() => setMode("template")} />
        ) : (
          formFill
        )}
      </div>
    );
  }

  return formFill;
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
      toast.success(
        `Fee status saved${nextPaid ? " — payment arranged" : ""}${
          nextSme ? " · small-business granted" : ""
        }`
      );
    } catch (e) {
      toast.error(`Could not save fee status — ${String(e)}`);
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

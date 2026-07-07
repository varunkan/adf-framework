"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import type { CurrentView, CurrentViewLeaf, DocMeta, FeesBlock, SectionNode } from "@/lib/dossierTypes";
import { DraftChat } from "./DraftChat";
import { FormFill } from "./FormFill";
import { EctdPrimer } from "./EctdPrimer";
import { useDossier } from "./DossierContext";
import { Disclosure } from "../Disclosure";
import { Upload, Sparkles, Ban, AlertTriangle, FileSearch, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { MODULE_4_NOTE, citeLine, LAST_VERIFIED } from "@/lib/regCitations";
import { opMeta, applicabilityHelp } from "@/lib/leafStatus";
import { TERMS } from "@/lib/terms";
import { draftApi, type SectionNodeR9 } from "./draftApi";
import { RollupQueue } from "./RollupQueue";
import { openPrintWindow, escapeHtml } from "./printView";

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// Round-9 ai_draft MAJOR "Key info buried under nested toggles" (n=13):
// ONE level of authoring choice — Upload / Draft with AI / Fill the form /
// Mark N/A side by side, no toggles-inside-toggles (the old Author-in-app →
// AI-vs-form second layer is gone).
type AuthorTab = "upload" | "ai" | "form" | "mark_na";

function authorTabs(node: SectionNode): AuthorTab[] {
  const affs = node.affordances;
  const out: AuthorTab[] = [];
  if (affs.includes("upload")) out.push("upload");
  if (affs.includes("generate") && node.ai_draftable) out.push("ai");
  if (affs.includes("generate")) out.push("form");
  if (affs.includes("mark_na")) out.push("mark_na");
  return out;
}

// After switching to the form tab, focus the named field once FormFill has
// rendered it (schema loads async — retry briefly, then give up quietly).
function focusFormField(name: string, attempt = 0): void {
  const el = document.getElementById(name);
  if (el) {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    (el as HTMLElement).focus();
    return;
  }
  if (attempt < 12) setTimeout(() => focusFormField(name, attempt + 1), 200);
}

export function SectionPanel({ node, op }: { node: SectionNode; op?: string }) {
  const { dossierId, content, setContent } = useDossier();
  const nodeR9 = node as SectionNodeR9;
  const tabs = authorTabs(node);
  const [tab, setTab] = useState<AuthorTab>(tabs[0] || "upload");
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
    setTab(authorTabs(node)[0] || "upload");
    setErr("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.section]);

  // Round-9 builder_forms "Leaf placement details hidden behind collapsed
  // expander" (n=1) + ai_draft "Leaf metadata … not visible" (n=3): the live
  // current-view is fetched ONCE per section here (not lazily inside the
  // expander) so placement facts can show by default AND on the saved-doc
  // card. Refetches when the placed content changes (checksums change).
  const docChecksums = [
    ...(node.documents
      ? Object.values(node.documents).map((d) => d.checksum)
      : node.document
      ? [node.document.checksum]
      : []),
  ].join("|");
  const [cv, setCv] = useState<CurrentView | null>(null);
  const [cvErr, setCvErr] = useState("");
  useEffect(() => {
    if (!node.leaf_id) {
      setCv(null);
      return;
    }
    let live = true;
    dossierApi
      .currentView(dossierId)
      .then((v) => {
        if (!live) return;
        setCv(v);
        setCvErr("");
      })
      .catch((e) => {
        if (!live) return;
        setCvErr(String(e));
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dossierId, node.leaf_id, docChecksums]);

  const leafFor = (lang?: string): CurrentViewLeaf | null =>
    cv?.live.find(
      (l) => l.leaf_id === node.leaf_id + (lang ? `-${lang}` : "")
    ) || null;
  const leaf = leafFor() || leafFor("en") || leafFor("fr");
  const leafHistory =
    cv?.history.filter((l) => l.leaf_id === leaf?.leaf_id) || [];
  // Round-9 builder_forms MAJOR "Lifecycle operator lineage" (n=2): the
  // specific PRIOR sequence number a REPL/APP/DEL acts on — resolved from the
  // tracked back-pointer (modified_leaf) against the real lifecycle history.
  const priorTarget = leaf?.modified_leaf
    ? [...(cv?.history || []), ...(cv?.live || [])]
        .reverse()
        .find((l) => l.leaf_id === leaf.modified_leaf) || null
    : null;

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

  const authorDone = (c: any, msg: string) => {
    setContent(c);
    setAnnounce(msg);
    toast.success(msg);
  };

  return (
    <div className="card glass section-panel">
      <div className="sr-only" aria-live="polite">{announce}</div>
      <div className="eyebrow">
        Module {node.module} · Section {node.section} ·{" "}
        {/* Round-9 ai_draft MAJOR "eCTD jargon undefined" (n=9): the
            applicability badge now explains itself on hover/focus, in the
            same plain words as the glossary. */}
        <span
          className={`applic ${node.applicability}`}
          tabIndex={0}
          title={`${applicabilityHelp(node.applicability)} — ${TERMS["applicability badge"]}`}
        >
          {node.applicability}
        </span>
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
            </a>{" "}
            {/* Round-9 builder_forms BLOCKER "Target HC submission model /
                M1 backbone version not visible or dated" (n=3): the guidance
                link carries its verification stamp instead of dangling
                undated. */}
            <span className="mut" style={{ fontSize: 11 }}>
              (guidance set verified {LAST_VERIFIED})
            </span>
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
      ) : tabs.length === 0 ? (
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

          {/* Round-9 ai_draft minor "No list-view checker for unreplaced
              'example' placeholders" (n=2): every still-example field by
              name, one click from its form input. */}
          <ExampleFieldChecker
            node={nodeR9}
            onJump={(field) => {
              setTab("form");
              focusFormField(field);
            }}
          />

          <AttachedDocs
            node={node}
            dossierId={dossierId}
            leafFor={leafFor}
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
              behaviour where `role=tab` would have promised arrow-key roving.
              Round-9 ai_draft MAJOR (n=13): ONE level of choice — Draft with AI
              and Fill the form are first-class options here, not a second
              toggle nested under "Author in-app". */}
          <div className="affordance-bar" role="group" aria-label="Choose how to complete this section">
            {tabs.includes("upload") && (
              <button type="button" aria-pressed={tab === "upload"}
                className={tab === "upload" ? "on" : ""}
                onClick={() => setTab("upload")}><Upload size={14} aria-hidden /> Upload</button>
            )}
            {tabs.includes("ai") && (
              <button type="button" aria-pressed={tab === "ai"}
                className={tab === "ai" ? "on" : ""}
                title={nodeR9.ai_disabled
                  ? "AI drafting is disabled for this section (client filing policy)."
                  : undefined}
                onClick={() => setTab("ai")}><MessageSquare size={14} aria-hidden /> Draft with AI{nodeR9.ai_disabled ? " (off)" : ""}</button>
            )}
            {tabs.includes("form") && (
              <button type="button" aria-pressed={tab === "form"}
                className={tab === "form" ? "on" : ""}
                onClick={() => setTab("form")}><Sparkles size={14} aria-hidden /> Fill the form</button>
            )}
            {tabs.includes("mark_na") && (
              <button type="button" aria-pressed={tab === "mark_na"}
                className={tab === "mark_na" ? "on" : ""}
                onClick={() => setTab("mark_na")}><Ban size={14} aria-hidden /> Mark N/A</button>
            )}
          </div>

          {/* Round-9 builder_forms MAJOR "AI drafting lacks … per-section
              off-switch" (n=3, ask 2): the per-section AI policy, enforced
              server-side on BOTH draft paths — chat drafting AND the form's
              per-field "Draft with AI" — so it shows on form sections too. */}
          {(tabs.includes("ai") || tabs.includes("form")) && (
            <AiPolicyRow
              node={nodeR9}
              dossierId={dossierId}
              onChange={(c, disabled) => {
                setContent(c);
                if (disabled && tab === "ai") setTab("form");
              }}
              onError={fail}
            />
          )}

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

          {tab === "ai" &&
            (nodeR9.ai_disabled ? (
              <div className="notice" role="status">
                <b>AI drafting is disabled for this section</b> (client filing
                policy) — the server refuses both chat and per-field drafts.
                Author it by upload or the form instead, or re-enable AI above.
              </div>
            ) : (
              <DraftChat node={node} dossierId={dossierId} onDone={authorDone}
                onError={fail} onFallback={() => setTab("form")} />
            ))}

          {tab === "form" && (
            <FormFill node={node} op={op} dossierId={dossierId}
              onDone={authorDone} onError={fail} />
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

      {/* Round-9 builder_forms "Workspace density" (n=22, remaining ask) +
          "Leaf placement details hidden" (n=1) + ai_draft "Key info buried"
          (n=13): the eCTD placement panel — leaf id, href, node placement,
          lifecycle operation and the honest PDF/A scope note — is now OPEN BY
          DEFAULT (a critical-caveat panel, per-user collapsible with the
          preference persisted), and its collapsed summary line still shows
          leaf id · sequence · operation so nothing is ever fully hidden. */}
      {node.leaf_id && (
        <EctdPlacement
          node={node}
          op={op}
          dossierId={dossierId}
          leaf={leaf}
          history={leafHistory}
          priorTarget={priorTarget}
          loaded={cv !== null || !!cvErr}
          err={cvErr}
        />
      )}

      {/* Round-9 ai_draft BLOCKER "No project-level roll-up" (n=2) + MAJOR
          "no bulk attest" (n=6): the dossier-wide roll-up + team-review
          queue, reachable from every section panel (one collapsed line). */}
      <RollupQueue dossierId={dossierId} onContent={setContent} />
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
// does NOT. Round-9: data comes from the panel-level current-view fetch (so the
// saved-doc card shares it) and the panel is open by default — the per-user
// collapse preference persists in localStorage.
function EctdPlacement({
  node,
  op,
  dossierId,
  leaf,
  history,
  priorTarget,
  loaded,
  err,
}: {
  node: SectionNode;
  op?: string;
  dossierId: string;
  leaf: CurrentViewLeaf | null;
  history: CurrentViewLeaf[];
  priorTarget: CurrentViewLeaf | null;
  loaded: boolean;
  err: string;
}) {
  const [open, setOpen] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try {
      return window.localStorage.getItem("ands.placement.open") !== "0";
    } catch {
      return true;
    }
  });
  const toggle = (o: boolean) => {
    setOpen(o);
    try {
      window.localStorage.setItem("ands.placement.open", o ? "1" : "0");
    } catch {}
  };

  // The operation this leaf carries (from the live view once loaded, else the
  // parent-supplied hint). replace/append/delete act against a prior active
  // sequence — spell that out explicitly (MAJOR: replace/append clarity).
  const operation = leaf?.operation || op || "new";
  const om = opMeta(operation);
  const actsOnPrior = operation === "replace" || operation === "append" || operation === "delete";
  const ext = leaf?.href ? leaf.href.split(".").pop() || "" : "";

  return (
    <Disclosure
      className="ectd-placement"
      showLabel="Show eCTD placement & lifecycle"
      hideLabel="Hide eCTD placement & lifecycle"
      open={open}
      onOpenChange={toggle}
      summary={
        <span title={TERMS["eCTD placement"]}>
          <FileSearch size={13} aria-hidden style={{ verticalAlign: "-2px", marginRight: 5 }} />
          <b>eCTD placement</b> — leaf <code>{node.leaf_id}</code> · seq{" "}
          <code>{leaf?.sequence || "0000"}</code>
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
            {/* Round-9 ai_draft MAJOR "Leaf metadata … STF/file-format details"
                (n=3): the honest file-format + STF answer, on the face. */}
            <PlaceRow label="File format / STF">
              {leaf?.href ? <b>{ext.toUpperCase()}</b> : <span className="mut">—</span>}
              {" · "}
              <span className="mut" title={TERMS.STF}>
                no STF — Health Canada&apos;s eCTD does not use Study Tagging
                Files (FDA/PMDA constructs); this leaf sits directly at its CTD
                heading
              </span>
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
              acting on an earlier transmitted document. Round-9 builder_forms
              "Lifecycle operator lineage" (n=2): the specific prior sequence
              number the operation acts on, from the tracked back-pointer. */}
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
                <> Replaces leaf <code>{leaf.modified_leaf}</code>
                {priorTarget ? <> placed in sequence <code>{priorTarget.sequence}</code></> : null}.</>
              ) : null}</>
            )}
            {operation === "append" && (
              <><b>Append</b> — this leaf is added <i>alongside</i> a prior
              active leaf, not replacing it; both remain part of the record.
              {leaf?.modified_leaf ? (
                <> Appends to leaf <code>{leaf.modified_leaf}</code>
                {priorTarget ? <> placed in sequence <code>{priorTarget.sequence}</code></> : null}.</>
              ) : null}</>
            )}
            {operation === "delete" && (
              <><b>Delete</b> — this withdraws a document from a prior active
              sequence. It stays in the audit history but is removed from the
              current view.
              {leaf?.modified_leaf ? (
                <> Withdraws leaf <code>{leaf.modified_leaf}</code>
                {priorTarget ? <> placed in sequence <code>{priorTarget.sequence}</code></> : null}.</>
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
// Round-9 ai_draft MAJOR "'Confirmed' state can be misread as validated" (n=6):
// the tooltip now states explicitly that confirmed is NOT validated.
const AI_PROVENANCE_TOOLTIP =
  "Drafted interactively with the AI assistant under your direction, and " +
  "recorded in the audit trail. Data residency: your dossier text is sent to " +
  "the configured AI provider for this draft only, isolated per sponsor — it " +
  "is never shared across clients or used to train models. This is assistance, " +
  "not a filing: review it against the Health Canada guidance and confirm it " +
  "as your own content before filing. Confirmed is NOT validated — Health " +
  "Canada eValidator conformance must still be run before you transmit.";

// Round-9 ai_draft minor (n=2): the list-view checker for unreplaced
// worked-example fields — enumerated by label, one-click jump-to-fix.
function ExampleFieldChecker({
  node,
  onJump,
}: {
  node: SectionNodeR9;
  onJump: (field: string) => void;
}) {
  const fields = node.sample_fields || [];
  const show =
    fields.length > 0 && !!node.needs_review && node.content_origin === "sample";
  const [labels, setLabels] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!show) return;
    let live = true;
    dossierApi
      .sectionFormSchema(node.section)
      .then((s) => {
        if (!live) return;
        setLabels(
          Object.fromEntries(s.schema.fields.map((f) => [f.name, f.label]))
        );
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [node.section, show]);
  if (!show) return null;
  return (
    <div className="notice warn" role="status" style={{ fontSize: 12 }}>
      <AlertTriangle size={14} aria-hidden style={{ verticalAlign: "-2px", marginRight: 4 }} />
      <b>{fields.length} field{fields.length > 1 ? "s" : ""} still carr{fields.length > 1 ? "y" : "ies"} the worked example</b>{" "}
      — the section stays <b>not filable</b> and export is blocked until every
      one is replaced with your product&apos;s real data:
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {fields.map((f) => (
          <li key={f}>
            <button
              type="button"
              className="ghost"
              style={{ fontSize: 12, padding: "1px 6px" }}
              title="Open the form and jump to this field"
              onClick={() => onJump(f)}
            >
              {labels[f] || f} →
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Round-9 builder_forms MAJOR (n=3, ask 2): the per-section AI off-switch row.
function AiPolicyRow({
  node,
  dossierId,
  onChange,
  onError,
}: {
  node: SectionNodeR9;
  dossierId: string;
  onChange: (c: any, disabled: boolean) => void;
  onError: (e: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const disabled = !!node.ai_disabled;
  async function toggle() {
    setBusy(true);
    try {
      const c = await draftApi.setAiPolicy(
        dossierId, node.section, !disabled,
        disabled ? "re-enabled from section panel" : "client filing policy");
      onChange(c, !disabled);
      toast.success(
        !disabled
          ? `AI drafting disabled for ${node.section} — recorded to the audit trail`
          : `AI drafting re-enabled for ${node.section} — recorded to the audit trail`);
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="mut" style={{ fontSize: 12, display: "flex", gap: 8, alignItems: "center" }}>
      {disabled ? (
        <>AI drafting is <b style={{ color: "var(--warn)" }}>off</b> for this
        section (client filing policy — enforced server-side on chat and
        per-field drafts, recorded to the audit trail).</>
      ) : (
        <>AI drafting is allowed for this section.</>
      )}
      <button type="button" className="ghost" style={{ fontSize: 12 }}
        onClick={toggle} disabled={busy}>
        {busy ? "Saving…" : disabled ? "Re-enable AI drafting" : "Disable AI for this section"}
      </button>
    </div>
  );
}

// Round-9 builder_forms MAJOR "…harder attestation" (n=3, ask 3): the full
// draft must actually be read — the box tracks scroll-to-end (a draft short
// enough to need no scrolling counts as read once rendered).
function ScrollGate({
  text,
  onRead,
}: {
  text: string;
  onRead: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el && el.scrollHeight <= el.clientHeight + 4) onRead();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return (
    <div
      ref={ref}
      className="teach"
      tabIndex={0}
      aria-label="The full AI draft — scroll to the end before attesting"
      style={{ maxHeight: 180, overflowY: "auto", whiteSpace: "pre-wrap", fontSize: 12 }}
      onScroll={(e) => {
        const el = e.currentTarget;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 4) onRead();
      }}
    >
      {text}
    </div>
  );
}

// Round-9 ai_draft BLOCKER "Attestation is a button click, not an inspection-
// grade e-signature with exportable audit record" (n=4) + builder_forms MAJOR
// (n=3, ask 3): the attest step now (a) requires the FULL draft scrolled,
// (b) records the reviewer's typed name + credential with a UTC timestamp on
// the Part-11 ledger, and (c) offers the printable side-by-side review before
// the button. HONEST LIMIT stated in-UI: identity-stamped attestation, not a
// cryptographic signature — the transmit-gate Part-11 e-sign covers that.
function AiAttest({
  node,
  dossierId,
  onConfirm,
  onError,
}: {
  node: SectionNodeR9;
  dossierId: string;
  onConfirm: (c: any) => void;
  onError: (e: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [name, setName] = useState("");
  const [credential, setCredential] = useState("");
  const [scrolled, setScrolled] = useState(false);
  const [readLegacy, setReadLegacy] = useState(false);
  const draft = node.draft_text || "";
  const readOk = draft ? scrolled : readLegacy;

  function printSideBySide() {
    openPrintWindow(
      `Side-by-side review — ${node.section} ${node.title}`,
      `<h1>Side-by-side review — ${escapeHtml(node.section)} ${escapeHtml(node.title)}</h1>
       <div class="mut">The saved AI draft (left) against the Health Canada
       guidance this section is checked against (right). Guidance set verified
       ${escapeHtml(LAST_VERIFIED)}. The whole document is AI-assisted; it
       becomes your reviewed content only on the named attestation.</div>
       <div class="cols" style="margin-top:12px">
         <div class="col"><h2>AI draft (unreviewed)</h2>
           <div class="box">${escapeHtml(draft)}</div></div>
         <div class="col"><h2>What Health Canada needs here</h2>
           <div class="box">${escapeHtml(node.guidance)}</div>
           <div class="mut" style="margin-top:6px">Source: ${escapeHtml(node.source_url)}</div></div>
       </div>`
    );
  }

  async function confirm() {
    setConfirming(true);
    try {
      onConfirm(
        await draftApi.confirmContentAttested(dossierId, node.section, {
          attest_name: name.trim(),
          attest_credential: credential.trim(),
          attest_meaning: "I have reviewed this AI draft — it is my content",
        })
      );
      toast.success(`${node.section} confirmed as your reviewed content`);
    } catch (e) {
      onError(String(e));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
      {draft ? (
        <>
          <div className="mut" style={{ fontSize: 12 }}>
            Read the <b>full draft</b> below (scroll to the end), then attest
            by name:
          </div>
          <ScrollGate text={draft} onRead={() => setScrolled(true)} />
        </>
      ) : (
        // drafts saved before draft-text capture: an explicit read
        // acknowledgement replaces the scroll gate — never a free pass.
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12 }}>
          <input type="checkbox" style={{ width: "auto" }} checked={readLegacy}
            onChange={(e) => setReadLegacy(e.target.checked)} />
          <span>I opened the saved draft document and read it in full.</span>
        </label>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input value={name} placeholder="Your full name (required)"
          style={{ width: 200 }} disabled={confirming}
          aria-label="Attesting reviewer's full name"
          onChange={(e) => setName(e.target.value)} />
        <input value={credential} placeholder="Credential / role (e.g. RAC)"
          style={{ width: 180 }} disabled={confirming}
          aria-label="Attesting reviewer's credential"
          onChange={(e) => setCredential(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={confirm}
          disabled={confirming || !readOk || !name.trim()}
          title={!readOk
            ? "Read the full draft first — the button enables once you reach the end."
            : !name.trim()
            ? "Type your full name — the attestation is recorded by name."
            : undefined}>
          {confirming
            ? "Recording…"
            : "I have reviewed this AI draft — it is my content"}
        </button>
        {draft && (
          <button type="button" className="ghost" onClick={printSideBySide}
            title="Print the draft next to the Health Canada guidance — paper review before you attest.">
            Print side-by-side review
          </button>
        )}
      </div>
      <div className="mut" style={{ fontSize: 11 }}>
        Recorded with your name, credential and a UTC timestamp on the
        append-only Part-11 audit trail — an identity-stamped attestation (the
        cryptographic e-signature happens at the transmit gate). Attesting does{" "}
        <b>not</b> validate the section: run Health Canada&apos;s eValidator
        before you transmit.
      </div>
    </div>
  );
}

// Round-9 ai_draft MAJOR "'Confirmed' can be misread as validated" (n=6): the
// states legend — what each state and action actually commits you to.
function StatesLegend() {
  return (
    <Disclosure
      showLabel="Show"
      hideLabel="Hide"
      summary={
        <span className="mut" style={{ fontSize: 12 }}>
          <b>What these states commit you to</b> — not filable / confirmed /
          export-ready
        </span>
      }
    >
      <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12, display: "grid", gap: 5 }}>
        <li>
          <b>Not yet filable — review required:</b> the section holds an
          unconfirmed AI draft or worked-example content. It cannot count as
          complete and export is blocked.
        </li>
        <li>
          <b>&ldquo;Use this draft&rdquo;</b> commits nothing — it only saves
          an UNCONFIRMED AI draft into the section; the section stays not
          filable until attested.
        </li>
        <li>
          <b>Confirmed (AI-assisted · confirmed):</b> a named attestation that
          YOU reviewed the draft as your own content, recorded on the audit
          trail. <b>Confirmed is NOT validated</b> — Health Canada eValidator
          conformance must still be run before filing; the structural check
          here is not HC&apos;s eValidator.
        </li>
        <li>
          <b>Export-ready:</b> the gate (documents · fee · structural check)
          passes, so a sequence can be exported — you still run HC&apos;s
          official eValidator on the exported package before transmit.
        </li>
        <li>
          <b>Review-vs-HC findings</b> are advisory content-completeness
          heuristics, not a screening clearance — act on them per your
          organisation&apos;s review SOP (senior review where it requires it).
        </li>
      </ul>
    </Disclosure>
  );
}

function AttachedDocs({
  node,
  dossierId,
  leafFor,
  onConfirm,
  onError,
}: {
  node: SectionNode;
  dossierId: string;
  leafFor: (lang?: string) => CurrentViewLeaf | null;
  onConfirm: (c: any) => void;
  onError: (e: string) => void;
}) {
  const nodeR9 = node as SectionNodeR9;
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
  const att = nodeR9.attestation;

  // Round-9 ai_draft BLOCKER (n=4): the one-click per-section audit record —
  // who drafted, who reviewed, when, md5, provider path — as a JSON download.
  async function exportAuditRecord() {
    try {
      const rec = await draftApi.sectionAuditRecord(dossierId, node.section);
      const blob = new Blob([JSON.stringify(rec, null, 2)],
        { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${dossierId}-${node.section}-audit-record.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success(`Audit record for ${node.section} exported`);
    } catch (e) {
      onError(String(e));
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
              <AiAttest node={nodeR9} dossierId={dossierId}
                onConfirm={onConfirm} onError={onError} />
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
      {docs.map(({ lang, meta }) => {
        const leaf = leafFor(lang);
        return (
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
            {fmtSize(meta.size)} ·{" "}
            <span title={TERMS["md5 fingerprint"]}>
              fingerprint md5 {meta.checksum.slice(0, 8)}…
            </span>
            {/* Round-9 ai_draft MAJOR "Leaf metadata … not visible" (n=3):
                the real leaf metadata ON the saved-document card — operation,
                sequence and href from the live current-view. */}
            {leaf && (
              <> · {opMeta(leaf.operation)?.label || leaf.operation.toUpperCase()}{" "}
              @ seq {leaf.sequence} · <code style={{ fontSize: 10 }}>{leaf.href}</code></>
            )}
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
        );
      })}
      {/* Round-9 ai_draft MAJOR (n=6): confirmed ≠ validated, stated in
          always-visible text right where the confirmed chip renders — plus
          the recorded named attestation for the inspection record. */}
      {!needsReview && node.content_confirmed && isAi && (
        <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
          {att ? (
            <>Attested by <b>{att.name}</b>
            {att.credential ? `, ${att.credential}` : ""} · {att.attested_at} —
            recorded on the audit trail. </>
          ) : null}
          <b>Confirmed ≠ validated</b> — run Health Canada&apos;s eValidator on
          the exported package before you transmit.
        </div>
      )}
      <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
        <div>
          <button type="button" className="ghost" style={{ fontSize: 12 }}
            onClick={exportAuditRecord}
            title="Download this section's audit record: who drafted, who reviewed/attested, when, md5 fingerprints and every ledger event for the section.">
            Export audit record (JSON)
          </button>
        </div>
        <div className="mut" style={{ fontSize: 11 }}>
          This record and the full dossier trail are stored in the append-only,
          actor-stamped Part-11 ledger — exportable for inspection at any time.
        </div>
        <StatesLegend />
      </div>
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

// Round-9 builder_forms BLOCKER "Bilingual/XML Product Monograph handling
// unclear" (n=4) + ai_draft BLOCKER "No bilingual French / XML PM support
// signals" (n=2): promoted to a FIRST-CLASS block at 1.3.1 (no longer a
// collapsed <details>) with an explicit XML-PM-vs-PDF/A-leaf scope statement
// and the named HC template/stylesheet package the build maps to. HONEST:
// the XML built here starts from placeholder sections — it is not yet
// generated from the AI/form draft content, and the panel says so.
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
    <div className="teach" style={{ marginTop: 8 }}>
      <b>XML Product Monograph — build &amp; validate</b>{" "}
      <span className="mut">(HC mandate is phasing in for generics)</span>
      <div style={{ fontSize: 12, marginTop: 6 }}>
        <b>Scope — what this tool produces at 1.3.1:</b> it places your
        reviewed PM document as a <b>PDF/A leaf</b>, and it separately{" "}
        <b>builds &amp; validates a structured XML PM</b> (pm-en.xml /
        pm-fr.xml) against Health Canada&apos;s stylesheet package{" "}
        (<code>pharmabio_stylesheets</code>, published 2025-09-10 — controlled
        PM section codes, EN/FR editions).
      </div>
      <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
        Honest limit: the XML below starts from placeholder sections — it is{" "}
        <b>not yet generated from your AI/form draft content</b>. Align the
        final XML PM with your reviewed PM before filing.
      </div>
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

"use client";
import { useRef, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { EctdPrimer } from "./EctdPrimer";
import { Disclosure } from "../Disclosure";
import { ShieldCheck, AlertTriangle } from "lucide-react";
import { LAST_VERIFIED } from "@/lib/regCitations";
import type { SectionNode } from "@/lib/dossierTypes";
import { draftApi, type DraftContext, type ProviderDisclosure } from "./draftApi";
import { diffWords, diffCounts, type DiffOp } from "./textDiff";
import { openPrintWindow, escapeHtml } from "./printView";

type Msg = { role: "user" | "assistant"; content: string };

// The no-key fallback copy is single-sourced here so the plain-language message
// never leaks a variable name (WS-AIDRAFT MAJOR: graceful no-AI). An error is
// a "no key / not configured" case when the backend raised LlmNotConfigured
// ("GROQ_API_KEY is not set") — matched on shape, not shown to the user.
function isNoKeyError(err: string): boolean {
  return /GROQ_API_KEY|not configured|not set|not turned on/i.test(err);
}

export function DraftChat({
  node,
  dossierId,
  onDone,
  onError,
  onFallback,
}: {
  node: SectionNode;
  dossierId: string;
  onDone: (c: any, msg: string) => void;
  onError: (e: string) => void;
  // WS-AIDRAFT (graceful no-AI): when the AI is not configured, offer a real
  // one-click switch to "Fill the form" instead of a dead-end error. Optional
  // so DraftChat still works when rendered standalone.
  onFallback?: () => void;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [chatErr, setChatErr] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  // Round-9 ai_draft minor "No diff of AI draft vs user edits" (n=2): the
  // completed assistant drafts, oldest→newest — a chat-directed edit produces
  // a NEW draft version, so the version-to-version diff IS the edit diff.
  const draftVersions = messages
    .filter((m) => m.role === "assistant" && m.content.trim())
    .map((m) => m.content);

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setChatErr("");
    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setStreaming(true);
    setMessages((m) => [...m, { role: "assistant", content: "" }]);
    try {
      for await (const chunk of dossierApi.streamDraftChat(dossierId, node.section, next)) {
        if (chunk.error) {
          setChatErr(chunk.error);
          break;
        }
        if (chunk.delta) {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = {
              role: "assistant",
              content: copy[copy.length - 1].content + chunk.delta,
            };
            return copy;
          });
          listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
        }
      }
    } catch (e) {
      setChatErr(String(e));
    } finally {
      setStreaming(false);
    }
  }

  async function useDraft() {
    if (!lastAssistant?.content) return;
    setSaving(true);
    try {
      const c = await dossierApi.generate(dossierId, node.section, {
        llm_draft: lastAssistant.content,
      });
      onDone(c, `${node.title} saved as an AI-assisted draft — provenance is ` +
        "recorded in the audit trail. It is NOT filable yet: review it against " +
        "the Health Canada guidance, then confirm it as your own content using " +
        "the review banner on the saved-document card above.");
    } catch (e) {
      onError(String(e));
    } finally {
      setSaving(false);
    }
  }

  // Round-9 ai_draft MAJOR "side-by-side comparison … printable" (n=9): the
  // current draft next to the section's cited HC guidance, on paper.
  function printSideBySide() {
    if (!lastAssistant?.content) return;
    openPrintWindow(
      `Side-by-side review — ${node.section} ${node.title}`,
      `<h1>Side-by-side review — ${escapeHtml(node.section)} ${escapeHtml(node.title)}</h1>
       <div class="mut">AI draft (left) against the Health Canada guidance this
       section is checked against (right). Checker criteria last verified
       against HC guidance ${escapeHtml(LAST_VERIFIED)}. The checker is modeled
       on HC criteria — it is NOT Health Canada's eValidator.</div>
       <div class="cols" style="margin-top:12px">
         <div class="col"><h2>AI draft (unreviewed)</h2>
           <div class="box">${escapeHtml(lastAssistant.content)}</div></div>
         <div class="col"><h2>What Health Canada needs here</h2>
           <div class="box">${escapeHtml(node.guidance)}</div>
           <div class="mut" style="margin-top:6px">Source: Health Canada
           guidance for this section — ${escapeHtml(node.source_url)}
           (guidance set verified ${escapeHtml(LAST_VERIFIED)}).</div></div>
       </div>`
    );
  }

  return (
    <div className="chat-panel">
      {/* WS-AIDRAFT MAJOR — the control/guardrails. Round-9 DENSITY REDUCTION:
          the always-visible note is ONE compact line; the four detail points
          plus the AI-skeptic reassurance live behind the expander (closed by
          default). No substance removed, no guardrail weakened — only the
          first-view verbosity is reduced. */}
      <div className="notice" role="note" style={{ padding: "12px 15px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13 }}>
          <ShieldCheck size={16} aria-hidden style={{ color: "var(--ok)", flex: "0 0 auto", marginTop: 1 }} />
          <span>
            AI drafts are <b>not filable on their own</b> — you sign off by name;
            modeled on HC criteria, <b>not</b> HC&apos;s eValidator.
          </span>
        </div>
        {/* Round-9 ai_draft BLOCKER "Criteria 'last verified' date and HC
            guidance version are buried" (n=13): the verification stamp is now
            an ALWAYS-VISIBLE line here (and beside every Review-vs-HC result
            in ReviewPanel) — no longer muted text inside the expander. */}
        <div style={{ fontSize: 12, marginTop: 6 }}>
          Checker criteria last verified against Health Canada guidance:{" "}
          <b>{LAST_VERIFIED}</b> · criteria for this section map to{" "}
          <a href={node.source_url} target="_blank" rel="noopener noreferrer">
            its named HC guidance ↗
          </a>{" "}
          <span className="mut">
            (each Review-vs-HC finding cites the guidance document by name)
          </span>
        </div>
        {/* Depth is one click away: the four control facts + the AI-skeptic
            reassurance, collapsed by default. */}
        <Disclosure
          showLabel="More on how the AI is kept accountable"
          hideLabel="Hide"
          summary={
            <span className="mut" style={{ fontSize: 12 }}>
              Skeptical of AI in a regulated filing? Read this.
            </span>
          }
        >
          <ul style={{ margin: "4px 0 0", paddingLeft: 20, display: "grid", gap: 5, fontSize: 13 }}>
            <li>
              <b>Not filable on its own.</b> Every AI draft stays{" "}
              <b>&ldquo;not yet filable — review required&rdquo;</b> and the
              submission cannot be exported until a person signs off.
            </li>
            <li>
              <b>You sign off, by name.</b> Nothing counts as complete until you
              click <b>&ldquo;I have reviewed this AI draft — it is my
              content&rdquo;</b> on the saved-document card. The AI never
              auto-submits.
            </li>
            <li>
              <b>Provenance is recorded.</b> The draft is tagged as
              AI-assisted and written to the audit trail with a file fingerprint —
              who/what produced it travels with the document.
            </li>
            <li>
              <b>Modeled on HC criteria — not HC&apos;s eValidator.</b> ANDS
              Studio&apos;s structural completeness check is a technical checker{" "}
              <b>modeled on Health Canada criteria</b>; it is <b>not</b> Health
              Canada&apos;s official eValidator. Run eValidator before you
              transmit.
            </li>
          </ul>
          {/* WS-AIDRAFT MINOR (AI-skeptic reassurance, veteran_contractor). */}
          <ul style={{ margin: "8px 0 0", paddingLeft: 20, display: "grid", gap: 5, fontSize: 12 }}>
            <li>
              <b>It never auto-submits.</b> The AI only proposes text into this
              chat. Nothing reaches Health Canada — filing happens only through
              the separate, human-driven transmit step.
            </li>
            <li>
              <b>Every draft is human-owned on sign-off.</b> Until you attest it
              as your content, the draft is flagged AI-assisted and blocks
              export; once you attest, it becomes <i>your</i> reviewed content
              on the record — the accountability is yours, not the model&apos;s.
            </li>
            <li>
              <b>Any regulatory claim is traceable.</b> The
              &ldquo;What Health Canada needs here&rdquo; guidance links to the
              primary Health Canada source, and the structural check reports
              which criteria it did and did not evaluate — no invented rules.
            </li>
          </ul>
        </Disclosure>
      </div>

      {/* Round-9 ai_draft BLOCKER "AI provider identity, data residency and
          DPA not verifiable" (n=8): the inspectable provider disclosure — a
          quotable panel + downloadable document, replacing hover-tooltip-only
          data-residency copy. */}
      <ProviderPanel />

      {/* Round-9 builder_forms MAJOR "AI drafting lacks source transparency"
          (n=3, ask 1): exactly what a draft for THIS section is generated
          from — sources, dossier facts, and what is excluded. */}
      <DraftSourcesPanel dossierId={dossierId} section={node.section} />

      <p className="mut" style={{ fontSize: 13 }}>
        Chat with the AI assistant to draft this document — it asks for any
        details it needs instead of leaving blanks. Nothing is saved until you
        click <b>Use this draft</b>.
      </p>
      <EctdPrimer compact />

      {/* Round-9 ai_draft minor "Novices lack a worked example" (n=2): a
          sample what-to-type prompt + an illustrative completed section,
          viewable from the chat panel. */}
      <WorkedExample dossierId={dossierId} node={node} onFallback={onFallback} />

      <div className="chat-thread" ref={listRef}>
        {messages.length === 0 && (
          <div className="mut" style={{ fontSize: 13, padding: "8px 0" }}>
            Tell it about the submission to get started — it knows what
            {" "}{node.title} needs.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.content}
          </div>
        ))}
        {/* Round-9 ai_draft minor "'Thinking…' chat bubbles feel consumer-
            grade" (n=1): a neutral, professional progress status line — no
            conversational filler. */}
        {streaming && (
          <div className="mut" role="status" style={{ fontSize: 12, padding: "4px 0" }}>
            Generating draft…
          </div>
        )}
      </div>
      {chatErr && (
        isNoKeyError(chatErr) ? (
          // WS-AIDRAFT MAJOR (graceful no-AI): plain language, NO variable
          // name, and a real one-click path to "Fill the form" instead of a
          // dead end. The template form authors the SAME leaf, so no work
          // is lost by not having AI configured.
          <div className="notice" role="status" style={{ display: "grid", gap: 8 }}>
            <div>
              <b>AI drafting isn&apos;t turned on yet.</b> You can author this
              section by hand instead — the form fills the same eCTD leaf, so
              nothing is lost. To enable AI drafting, contact your administrator.
            </div>
            {onFallback && (
              <div>
                <button type="button" onClick={onFallback}>
                  Fill the form instead →
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="notice bad" role="alert">
            <AlertTriangle size={14} aria-hidden style={{ verticalAlign: "-2px", marginRight: 5 }} />
            {chatErr}
          </div>
        )
      )}
      <div className="chat-input-row">
        <textarea
          rows={2}
          value={input}
          placeholder="e.g. Sponsor is Acme Pharma Inc., contact regulatory@acme.example"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button onClick={send} disabled={streaming || !input.trim()}>
          {streaming ? "Generating…" : "Send"}
        </button>
      </div>

      {/* Round-9 ai_draft minor "No diff of AI draft vs user edits" (n=2):
          chat-directed edits produce a new draft version — the diff between
          versions shows exactly which passages changed, printable. */}
      {draftVersions.length >= 2 && !streaming && (
        <DraftDiff versions={draftVersions} sectionLabel={`${node.section} ${node.title}`} />
      )}

      {lastAssistant?.content && !streaming && (
        <div className="cta-row">
          <button className="ghost" onClick={useDraft} disabled={saving}>
            {saving ? "Saving…" : "Use this draft →"}
          </button>
          <button className="ghost" type="button" onClick={printSideBySide}
            title="Print the draft next to the Health Canada guidance it is checked against — for paper review before you attest.">
            Print side-by-side review
          </button>
        </div>
      )}
    </div>
  );
}

// -- Round-9 ai_draft BLOCKER (n=8): the inspectable AI-provider disclosure --
function ProviderPanel() {
  const [d, setD] = useState<ProviderDisclosure | null>(null);
  const [err, setErr] = useState("");

  return (
    <Disclosure
      showLabel="Show"
      hideLabel="Hide"
      onOpenChange={(o) => {
        if (o && !d) draftApi.aiProvider().then(setD).catch((e) => setErr(String(e)));
      }}
      summary={
        <span style={{ fontSize: 12 }}>
          <b>AI provider &amp; data handling</b>
          <span className="mut"> — named provider, hosting region, retention,
          downloadable data-processing disclosure</span>
        </span>
      }
    >
      {err && <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>}
      {!d && !err && <div className="mut" style={{ fontSize: 12 }}>Loading…</div>}
      {d && (
        <div style={{ fontSize: 12, display: "grid", gap: 6 }}>
          <div>
            <b>Provider:</b> {d.provider}
            {d.model ? <> · model <code>{d.model}</code></> : null}
            {" · "}
            <a href={d.policy_url} target="_blank" rel="noopener noreferrer">
              provider data policy ↗
            </a>
          </div>
          <div>
            <b>Hosting region:</b> {d.hosting_region} —{" "}
            {d.leaves_canada ? (
              <b>drafting data leaves Canada for the duration of each request.</b>
            ) : (
              "drafting data stays in Canada."
            )}
          </div>
          <div className="mut">{d.data_residency}</div>
          <div><b>Retention:</b> <span className="mut">{d.retention}</span></div>
          <div><b>Per-sponsor isolation:</b> <span className="mut">{d.isolation}</span></div>
          <div><b>Training:</b> <span className="mut">{d.training}</span></div>
          <div>
            <a
              className="chip"
              download="ands-ai-data-processing-disclosure.txt"
              href={`data:text/plain;charset=utf-8,${encodeURIComponent(d.dpa_text)}`}
            >
              ⬇ Download data-processing disclosure (for client auditors)
            </a>
          </div>
          {/* HONESTY: this is our disclosure of the AI data path — it is NOT
              a countersigned DPA with the provider, and it says so. */}
          <div className="mut">{d.dpa_note}</div>
        </div>
      )}
    </Disclosure>
  );
}

// -- Round-9 builder_forms MAJOR (n=3, ask 1): per-draft source disclosure ---
function DraftSourcesPanel({ dossierId, section }: { dossierId: string; section: string }) {
  const [ctx, setCtx] = useState<DraftContext | null>(null);
  const [err, setErr] = useState("");

  return (
    <Disclosure
      showLabel="Show"
      hideLabel="Hide"
      onOpenChange={(o) => {
        if (o && !ctx)
          draftApi.draftContext(dossierId, section).then(setCtx).catch((e) => setErr(String(e)));
      }}
      summary={
        <span style={{ fontSize: 12 }}>
          <b>What each draft is generated from</b>
          <span className="mut"> — the exact sources and dossier facts sent,
          and what is excluded</span>
        </span>
      }
    >
      {err && <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>}
      {!ctx && !err && <div className="mut" style={{ fontSize: 12 }}>Loading…</div>}
      {ctx && (
        <div style={{ fontSize: 12, display: "grid", gap: 6 }}>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {ctx.sources.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
          {Object.keys(ctx.facts).length > 0 && (
            <div>
              <b>Dossier facts sent:</b>{" "}
              {Object.entries(ctx.facts).map(([k, v]) => (
                <code key={k} style={{ marginRight: 8 }}>{k}={String(v)}</code>
              ))}
            </div>
          )}
          <div className="mut">{ctx.excluded}</div>
        </div>
      )}
    </Disclosure>
  );
}

// -- Round-9 ai_draft minor (n=2): the per-section worked example ------------
function WorkedExample({
  dossierId,
  node,
  onFallback,
}: {
  dossierId: string;
  node: SectionNode;
  onFallback?: () => void;
}) {
  const [ex, setEx] = useState<{ prompt: string;
    fields: { label: string; value: string }[] } | null>(null);
  const [err, setErr] = useState("");

  async function load() {
    try {
      const [s, sample] = await Promise.all([
        dossierApi.sectionFormSchema(node.section),
        dossierApi.formSample(dossierId, node.section),
      ]);
      const labels = new Map(s.schema.fields.map((f) => [f.name, f.label]));
      const rows = Object.entries(sample.fields || {})
        .filter(([, v]) => String(v || "").trim())
        .map(([k, v]) => ({ label: labels.get(k) || k, value: String(v) }));
      const prompt = rows.slice(0, 6)
        .map((r) => `${r.label}: ${r.value}`).join("; ");
      setEx({ prompt, fields: rows });
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <Disclosure
      showLabel="Show"
      hideLabel="Hide"
      onOpenChange={(o) => { if (o && !ex && !err) load(); }}
      summary={
        <span style={{ fontSize: 12 }}>
          <b>See a worked example</b>
          <span className="mut"> — what to type, and what a completed section
          looks like</span>
        </span>
      }
    >
      {err && <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>}
      {!ex && !err && <div className="mut" style={{ fontSize: 12 }}>Loading…</div>}
      {ex && (
        <div style={{ fontSize: 12, display: "grid", gap: 6 }}>
          <div>
            <b>Example of a good input</b> — the details the AI needs for{" "}
            {node.title}:
            <div className="teach" style={{ marginTop: 4 }}>
              <i>{ex.prompt || "State your sponsor, product and submission facts."}</i>
            </div>
          </div>
          <div>
            <b>An illustrative completed section</b>{" "}
            <span className="mut">
              (a worked example — NOT your content; anything left as example
              text keeps the section not filable):
            </span>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {ex.fields.map((f, i) => (
                <li key={i}><b>{f.label}:</b> <i>{f.value}</i></li>
              ))}
            </ul>
          </div>
          {onFallback && (
            <div>
              <button type="button" className="ghost" onClick={onFallback}>
                Open this worked example in the form →
              </button>
            </div>
          )}
        </div>
      )}
    </Disclosure>
  );
}

// -- Round-9 ai_draft minor (n=2): draft-version diff + printable summary ----
function DraftDiff({
  versions,
  sectionLabel,
}: {
  versions: string[];
  sectionLabel: string;
}) {
  // default: previous vs latest — every chat-directed edit lands here
  const [baseIdx, setBaseIdx] = useState(-1); // -1 = previous version
  const latest = versions[versions.length - 1];
  const base = versions[baseIdx === -1 ? versions.length - 2 : baseIdx];
  const ops = diffWords(base, latest);
  const { added, removed } = diffCounts(ops);

  function printSummary() {
    const body = ops
      .map((op: DiffOp) =>
        op.kind === "ins"
          ? `<ins>${escapeHtml(op.text)}</ins>`
          : op.kind === "del"
          ? `<del>${escapeHtml(op.text)}</del>`
          : escapeHtml(op.text))
      .join("");
    openPrintWindow(
      `Draft revision summary — ${sectionLabel}`,
      `<h1>Draft revision summary — ${escapeHtml(sectionLabel)}</h1>
       <div class="mut">Marked passages changed between AI draft versions
       (edits are made by directing the AI in chat; the saved document is
       exactly the draft you accept). Added: ${added} word(s) · removed:
       ${removed} word(s). The whole document is AI-assisted and remains so
       on the record until attested by name.</div>
       <div class="box" style="margin-top:12px">${body}</div>`
    );
  }

  return (
    <Disclosure
      showLabel="Show"
      hideLabel="Hide"
      summary={
        <span style={{ fontSize: 12 }}>
          <b>Compare draft versions</b>
          <span className="mut"> — see exactly what changed before you accept
          ({added} added · {removed} removed vs latest)</span>
        </span>
      }
    >
      <div style={{ fontSize: 12, display: "grid", gap: 6 }}>
        {versions.length > 2 && (
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            Compare latest against:
            <select
              style={{ width: "auto" }}
              value={baseIdx}
              onChange={(e) => setBaseIdx(Number(e.target.value))}
            >
              <option value={-1}>previous version</option>
              {versions.slice(0, -1).map((_, i) => (
                <option key={i} value={i}>version {i + 1}</option>
              ))}
            </select>
          </label>
        )}
        <div
          className="teach"
          style={{ whiteSpace: "pre-wrap", maxHeight: 220, overflowY: "auto" }}
        >
          {ops.map((op, i) =>
            op.kind === "ins" ? (
              <ins key={i} style={{ background: "rgba(64,180,96,.25)", textDecoration: "none" }}>
                {op.text}
              </ins>
            ) : op.kind === "del" ? (
              <del key={i} style={{ background: "rgba(220,80,80,.25)" }}>{op.text}</del>
            ) : (
              <span key={i}>{op.text}</span>
            )
          )}
        </div>
        <div>
          <button type="button" className="ghost" onClick={printSummary}>
            Print revision summary
          </button>
        </div>
      </div>
    </Disclosure>
  );
}

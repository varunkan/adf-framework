"use client";
import { useRef, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { EctdPrimer } from "./EctdPrimer";
import { Disclosure } from "../Disclosure";
import { ShieldCheck, AlertTriangle } from "lucide-react";
import { LAST_VERIFIED } from "@/lib/regCitations";
import type { SectionNode } from "@/lib/dossierTypes";

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

  return (
    <div className="chat-panel">
      {/* WS-AIDRAFT MAJOR — the control/guardrails, stated plainly and kept
          UNMISSABLE above the chat (not buried in a paragraph). These four
          facts are the trust foundation the panel praised; each is one line. */}
      <div className="notice" role="note" style={{ padding: "12px 15px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700 }}>
          <ShieldCheck size={16} aria-hidden style={{ color: "var(--ok)", flex: "0 0 auto" }} />
          How this AI draft is controlled
        </div>
        <ul style={{ margin: "8px 0 0", paddingLeft: 20, display: "grid", gap: 5, fontSize: 13 }}>
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
            transmit.{" "}
            <span className="mut" style={{ fontSize: 12 }}>
              (Criteria last verified against HC guidance {LAST_VERIFIED}.)
            </span>
          </li>
        </ul>
        {/* WS-AIDRAFT MINOR (AI-skeptic reassurance, veteran_contractor):
            stated plainly and kept quiet behind an expander so it adds
            reassurance without density. */}
        <Disclosure
          showLabel="More on how the AI is kept accountable"
          hideLabel="Hide"
          summary={
            <span className="mut" style={{ fontSize: 12 }}>
              Skeptical of AI in a regulated filing? Read this.
            </span>
          }
        >
          <ul style={{ margin: "4px 0 0", paddingLeft: 20, display: "grid", gap: 5, fontSize: 12 }}>
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
      <p className="mut" style={{ fontSize: 13 }}>
        Chat with the AI assistant to draft this document — it asks for any
        details it needs instead of leaving blanks. Nothing is saved until you
        click <b>Use this draft</b>.
      </p>
      <EctdPrimer compact />

      <div className="chat-thread" ref={listRef}>
        {messages.length === 0 && (
          <div className="mut" style={{ fontSize: 13, padding: "8px 0" }}>
            Tell it about the submission to get started — it knows what
            {" "}{node.title} needs.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.content || (streaming && i === messages.length - 1 ? "…" : "")}
          </div>
        ))}
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
          {streaming ? "Thinking…" : "Send"}
        </button>
      </div>
      {lastAssistant?.content && !streaming && (
        <div className="cta-row">
          <button className="ghost" onClick={useDraft} disabled={saving}>
            {saving ? "Saving…" : "Use this draft →"}
          </button>
        </div>
      )}
    </div>
  );
}

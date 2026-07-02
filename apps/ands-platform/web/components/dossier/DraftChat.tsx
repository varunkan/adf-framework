"use client";
import { useRef, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { SectionNode } from "@/lib/dossierTypes";

type Msg = { role: "user" | "assistant"; content: string };

export function DraftChat({
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
        "recorded in the audit trail. Use “Review vs Health Canada” under " +
        "✦ Sample & edit to check the required elements before filing.");
    } catch (e) {
      onError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="chat-panel">
      <p className="mut" style={{ fontSize: 13 }}>
        Chat with an AI assistant to draft this document — it will ask for any
        details it needs instead of leaving blanks. Nothing is saved until you
        click <b>Use this draft</b>.
      </p>
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
        <div className="notice bad">
          {chatErr.includes("GROQ_API_KEY") || chatErr.includes("not configured")
            ? "AI drafting isn't set up yet (no GROQ_API_KEY). Use the standard \"Author\" button below instead, or ask an admin to configure it."
            : chatErr}
        </div>
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

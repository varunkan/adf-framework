"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ContentView, JourneyView, Slot } from "@/lib/types";

// The document tray — generic eCTD documents, each with the Module slot it
// belongs in. Click a document (accessible) or drag it onto a slot; the slot
// fills and the 3D tower's module lights up.
const TRAY: { label: string; slot: string; lang?: string }[] = [
  { label: "Cover letter.pdf", slot: "m1_cover_letter" },
  { label: "Administrative forms.pdf", slot: "m1_administrative" },
  { label: "Product Monograph — English.pdf", slot: "m1_product_monograph", lang: "en" },
  { label: "Product Monograph — Français.pdf", slot: "m1_product_monograph", lang: "fr" },
  { label: "Quality Overall Summary.pdf", slot: "m2_3" },
  { label: "Module 3 — CMC dossier.pdf", slot: "m3" },
  { label: "Bioequivalence study report.pdf", slot: "m5" },
];

export function ContentSlots({
  sessionId,
  content,
  onUpdate,
}: {
  sessionId: string;
  content: ContentView;
  onUpdate: (v: JourneyView) => void;
}) {
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const slotsByKey = Object.fromEntries(content.slots.map((s) => [s.key, s]));

  async function place(slotKey: string, doc: string, lang?: string) {
    const slot = slotsByKey[slotKey];
    if (!slot) return;
    let languages: string[] | undefined;
    if (slot.bilingual) {
      const set = new Set(slot.languages || []);
      if (lang) set.add(lang);
      languages = [...set];
    }
    setBusy(true);
    try {
      onUpdate(await api.placeDoc(sessionId, slotKey, doc, languages));
    } finally {
      setBusy(false);
    }
  }

  // a tray doc is "done" when its target slot reflects it
  function trayDone(t: { slot: string; lang?: string }) {
    const s = slotsByKey[t.slot];
    if (!s) return false;
    if (t.lang) return (s.languages || []).includes(t.lang);
    return s.state === "filled";
  }

  const required = content.slots.filter((s) => s.required && s.applicable);
  const optional = content.slots.filter((s) => !(s.required && s.applicable));

  return (
    <div className="content-slots">
      <div className="slot-tray" role="list" aria-label="Documents to place">
        {TRAY.map((t) => {
          const done = trayDone(t);
          return (
            <button
              key={t.label}
              role="listitem"
              className={`doc-chip ${done ? "placed" : ""}`}
              draggable={!done}
              onDragStart={(e) => {
                setDragKey(t.slot);
                e.dataTransfer.setData("text/plain", JSON.stringify(t));
              }}
              onDragEnd={() => setDragKey(null)}
              disabled={done || busy}
              onClick={() => place(t.slot, t.label, t.lang)}
              title={done ? "Placed" : `Place into the right Module slot`}
            >
              {done ? "✓ " : "📄 "}
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="slot-grid">
        {required.map((s) => (
          <SlotCard
            key={s.key}
            slot={s}
            active={dragKey === s.key}
            onDropDoc={(t) => place(s.key, t.label, t.lang)}
          />
        ))}
      </div>

      {optional.length > 0 && (
        <details className="optional-slots">
          <summary>
            Not required for this generic ({optional.length} modules)
          </summary>
          <div className="slot-grid">
            {optional.map((s) => (
              <div key={s.key} className="slot na" title={s.title}>
                <span className="slot-mod">M{s.module}</span>
                <span className="slot-title">{s.title}</span>
                <span className="slot-state">
                  {s.applicable ? "optional" : "not applicable"}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function SlotCard({
  slot,
  active,
  onDropDoc,
}: {
  slot: Slot;
  active: boolean;
  onDropDoc: (t: { label: string; lang?: string }) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`slot ${slot.state} ${active || over ? "drop-active" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        try {
          onDropDoc(JSON.parse(e.dataTransfer.getData("text/plain")));
        } catch {
          /* ignore */
        }
      }}
    >
      <span className="slot-mod">M{slot.module}</span>
      <span className="slot-title">
        {slot.title}
        {slot.bilingual && slot.state === "partial" && (
          <em className="mut"> — needs both EN + FR</em>
        )}
      </span>
      <span className="slot-state">
        {slot.state === "filled"
          ? "✓ placed"
          : slot.state === "partial"
          ? `${(slot.languages || []).join("/").toUpperCase()} ✓`
          : "drop here"}
      </span>
    </div>
  );
}

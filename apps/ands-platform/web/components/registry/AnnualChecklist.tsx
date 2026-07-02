"use client";
// Annual notification checklist — a LOCAL REMINDER only. The registry
// service has no annual-notification endpoint yet, so nothing here is
// filed or tracked server-side; ticks live in this browser (localStorage).
import { useEffect, useState } from "react";

const KEY = "ands_registry_annual_checklist";

const ITEMS = [
  "Confirm each DIN's marketed / dormant status is current in the registry",
  "File the Annual Drug Notification (ADN) with Health Canada for every DIN",
  "Pay the annual Right-to-Sell fee by October 1 (see deadlines above)",
  "Report any discontinuation of sale within the required window",
];

export function AnnualChecklist() {
  const [done, setDone] = useState<boolean[]>(() => ITEMS.map(() => false));

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        if (Array.isArray(saved)) {
          setDone(ITEMS.map((_, i) => Boolean(saved[i])));
        }
      }
    } catch {}
  }, []);

  function toggle(i: number) {
    setDone((prev) => {
      const next = prev.map((v, k) => (k === i ? !v : v));
      try {
        window.localStorage.setItem(KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }

  return (
    <div className="card glass" style={{ marginTop: 20, maxWidth: 720 }}>
      <h2 style={{ margin: "0 0 2px", fontSize: 15, fontWeight: 700 }}>
        Annual notification checklist
      </h2>
      <div className="notice warn" style={{ margin: "10px 0", fontSize: 12 }}>
        Reminder only — this checklist is stored in your browser and is NOT
        filed with Health Canada or tracked by the registry service.
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0,
        display: "flex", flexDirection: "column", gap: 8 }}>
        {ITEMS.map((label, i) => (
          <li key={label}>
            <label style={{ display: "flex", gap: 10, alignItems: "baseline",
              cursor: "pointer", fontSize: 13 }}>
              <input type="checkbox" checked={done[i]}
                onChange={() => toggle(i)} />
              <span className={done[i] ? "mut" : undefined}
                style={done[i] ? { textDecoration: "line-through" } : undefined}>
                {label}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

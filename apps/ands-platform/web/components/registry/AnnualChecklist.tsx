"use client";
// Annual notification checklist — SERVER-tracked per workspace and year.
// Every tick is a recorded sign-off (who + when, on the registry service and
// its event stream), so it survives any browser and is visible to the whole
// team. Round-4 panel fix: the old localStorage version was unanimously
// rejected ("worthless to an MAH").
import { useEffect, useState } from "react";
import { registryApi, type ChecklistItem } from "./registryApi";

function signedLine(item: ChecklistItem): string {
  if (!item.done || !item.signed_at) return "";
  const when = item.signed_at.slice(0, 16).replace("T", " ");
  return `signed by ${item.signed_by || "unrecorded"} · ${when} UTC`;
}

export function AnnualChecklist() {
  const [year, setYear] = useState(0);
  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    registryApi.annualChecklist()
      .then((r) => { setYear(r.year); setItems(r.items); })
      .catch((e) => setErr(String(e)));
  }, []);

  async function toggle(item: ChecklistItem) {
    setSaving(item.item_key);
    setErr("");
    try {
      const r = await registryApi.setAnnualItem(
        item.item_key, !item.done, year);
      setItems((prev) => (prev || []).map(
        (i) => (i.item_key === item.item_key ? r.item : i)));
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="card glass" style={{ marginTop: 24, maxWidth: 720 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>
        Annual notification checklist{year ? ` — ${year}` : ""}
      </h2>
      <p className="mut" style={{ margin: "8px 0 14px", fontSize: 12 }}>
        Tracked on the registry service for this workspace: each tick records
        who signed it and when, and lands on the audit event stream. (The
        filings themselves still happen with Health Canada — sources in
        Help.)
      </p>
      {err && <div className="notice bad" style={{ fontSize: 12,
        marginBottom: 8 }}>{err}</div>}
      {items === null && !err ? (
        <div className="mut" style={{ fontSize: 13 }}>Loading…</div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0,
          display: "flex", flexDirection: "column", gap: 8 }}>
          {(items || []).map((item) => (
            <li key={item.item_key}>
              <label style={{ display: "flex", gap: 10,
                alignItems: "baseline", cursor: "pointer", fontSize: 13 }}>
                <input type="checkbox" checked={item.done}
                  disabled={saving === item.item_key}
                  onChange={() => toggle(item)} />
                <span>
                  <span className={item.done ? "mut" : undefined}
                    style={item.done
                      ? { textDecoration: "line-through" } : undefined}>
                    {item.label}
                  </span>
                  {item.done && (
                    <small className="mut" style={{ display: "block",
                      fontSize: 11 }}>
                      ✓ {signedLine(item)}
                    </small>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

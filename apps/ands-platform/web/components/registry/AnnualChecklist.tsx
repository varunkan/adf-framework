"use client";
// Annual notification checklist — SERVER-tracked per workspace and year.
// Round-9 (qa_manager BLOCKER): every tick is a CONTROLLED e-signature —
// you re-enter your password at the moment of signing, a meaning-of-signature
// attestation is captured with the tick, and the append-only signing record
// is viewable right here. "A name + UTC stamp … is just decoration."
import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { ProvenancePopover } from "@/components/ProvenancePopover";
import {
  registryApi,
  type ChecklistItem,
  type SigningLogEntry,
} from "./registryApi";

// Round-9 (operations BLOCKER, n=15): "the annual-notification checklist has
// no cited clock at all." The statutory anchor for the ADN / Right-to-Sell
// cycle is October 1 of the fiscal year — same fiscal-year rule the registry
// service applies (month >= April ⇒ this year's Oct 1, else last year's).
function adnClock(now: Date = new Date()) {
  const fyStart =
    now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  const due = new Date(Date.UTC(fyStart, 9, 1)); // October 1 (month idx 9)
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((due.getTime() - today) / 86400000);
  return { iso: due.toISOString().slice(0, 10), days, overdue: days < 0,
           fy: `${fyStart}-${(fyStart + 1) % 100}` };
}

function signedLine(item: ChecklistItem): string {
  if (!item.done || !item.signed_at) return "";
  const when = item.signed_at.slice(0, 16).replace("T", " ");
  return `e-signed by ${item.signed_by || "unrecorded"} · ${when} UTC` +
    (item.reauthenticated ? " · credentials re-verified at signing" : "");
}

const DEFAULT_MEANING = (label: string, year: number) =>
  `I attest that "${label}" is completed for ${year}.`;

export function AnnualChecklist() {
  const [year, setYear] = useState(0);
  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  // the item currently in the signing flow (password prompt open)
  const [signing, setSigning] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [meaning, setMeaning] = useState("");
  const [needMfa, setNeedMfa] = useState(false);
  // signing record viewer
  const [log, setLog] = useState<SigningLogEntry[] | null>(null);
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    registryApi.annualChecklist()
      .then((r) => { setYear(r.year); setItems(r.items); })
      .catch((e) => setErr(String(e)));
    auth.me().then((p) => setEmail(p.email)).catch(() => {});
  }, []);

  function beginSign(item: ChecklistItem) {
    setSigning(item.item_key);
    setMeaning(DEFAULT_MEANING(item.label, year));
    setPassword("");
    setMfaCode("");
    setNeedMfa(false);
    setErr("");
  }

  async function commit(item: ChecklistItem, done: boolean) {
    setSaving(item.item_key);
    setErr("");
    try {
      const r = await registryApi.setAnnualItem(
        item.item_key, done, year,
        done ? { email, password, mfaCode, meaning } : undefined);
      setItems((prev) => (prev || []).map(
        (i) => (i.item_key === item.item_key ? r.item : i)));
      setSigning(null);
      setPassword("");
      if (showLog) refreshLog();
    } catch (e) {
      const msg = String(e);
      if (/mfa|authenticator/i.test(msg)) setNeedMfa(true);
      setErr(msg);
    } finally {
      setSaving(null);
    }
  }

  function refreshLog() {
    registryApi.signingLog(year)
      .then((r) => setLog(r.entries))
      .catch(() => setLog([]));
  }

  return (
    <div className="card glass" style={{ marginTop: 24, maxWidth: 720 }}>
      <h2 style={{ margin: 0, fontSize: 16 }}>
        Annual notification checklist{year ? ` — ${year}` : ""}
      </h2>
      <p className="mut" style={{ margin: "8px 0 8px", fontSize: 12 }}>
        Tracked on the registry service for this workspace. Each tick is a
        controlled e-signature: your password is re-verified at the moment of
        signing and a meaning-of-signature is recorded on the append-only
        signing record below. (The filings themselves still happen with
        Health Canada — sources in Help.)
      </p>
      {/* Round-9 (n=15): the checklist's cited statutory clock, on the face —
          regulation + day-count basis + input date, calculated-aid stamped. */}
      {(() => {
        const c = adnClock();
        return (
          <p style={{ margin: "0 0 14px", fontSize: 12, display: "flex",
            alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span className={`notice ${c.overdue ? "" : c.days <= 30 ? "warn" : ""}`}
              style={{ padding: "4px 10px", fontSize: 12 }}>
              ⏱ {c.overdue
                ? <><b>{-c.days}</b> day{c.days === -1 ? "" : "s"} past</>
                : <><b>{c.days}</b> day{c.days === 1 ? "" : "s"} until</>}{" "}
              the October 1 annual cycle (FY {c.fy}, due {c.iso})
              <span className="mut" style={{ marginLeft: 6, fontSize: 10 }}
                title="Calculated aid — verify against the HC record">
                · calculated aid
              </span>
            </span>
            <ProvenancePopover
              prov={{
                anchorLabel: `Annual notification / Right-to-Sell cycle (FY ${c.fy})`,
                anchorDate: c.iso,
                anchorSource: "ingested",
                basis: "calendar",
                rule:
                  "The Annual Drug Notification and Right-to-Sell fee cycle " +
                  "anchors on October 1 of the fiscal year (April–March); " +
                  "this is a fixed statutory calendar date, not a business-" +
                  "day count.",
                citation:
                  "Food and Drug Regulations — Annual Drug Notification / " +
                  "annual Right-to-Sell (statutory October 1)",
                asOf: null,
              }}
            />
            <span className="mut" style={{ fontSize: 10.5 }}>
              Basis: Food and Drug Regulations · fixed calendar date (no
              day-counting) · input: today&apos;s date — verify against the HC
              record.
            </span>
          </p>
        );
      })()}
      {err && <div className="notice bad" style={{ fontSize: 12,
        marginBottom: 8 }}>{err}</div>}
      {items === null && !err ? (
        <div className="mut" style={{ fontSize: 13 }}>Loading…</div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0,
          display: "flex", flexDirection: "column", gap: 10 }}>
          {(items || []).map((item) => (
            <li key={item.item_key}>
              <label style={{ display: "flex", gap: 10,
                alignItems: "baseline", cursor: "pointer", fontSize: 13 }}>
                <input type="checkbox" checked={item.done}
                  disabled={saving === item.item_key}
                  onChange={() =>
                    item.done ? commit(item, false) : beginSign(item)} />
                <span>
                  <span className={item.done ? "mut" : undefined}
                    style={item.done
                      ? { textDecoration: "line-through" } : undefined}>
                    {item.label}
                  </span>
                  {item.done && (
                    <small className="mut" style={{ display: "block",
                      fontSize: 11 }} title={item.meaning || undefined}>
                      ✓ {signedLine(item)}
                    </small>
                  )}
                </span>
              </label>

              {signing === item.item_key && !item.done && (
                <div className="notice" style={{ marginTop: 8, fontSize: 12,
                  display: "grid", gap: 8, padding: "10px 12px" }}>
                  <b>Sign this item as {email || "…"} </b>
                  <label style={{ display: "grid", gap: 3 }}>
                    <span className="mut">Meaning of signature (recorded
                      verbatim on the signing record)</span>
                    <textarea value={meaning} rows={2}
                      onChange={(e) => setMeaning(e.target.value)} />
                  </label>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input type="password" placeholder="Your password"
                      autoComplete="current-password" value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      style={{ maxWidth: 200 }} />
                    {needMfa && (
                      <input inputMode="numeric" placeholder="6-digit code"
                        value={mfaCode} style={{ maxWidth: 120 }}
                        onChange={(e) => setMfaCode(e.target.value)} />
                    )}
                    <button disabled={!password || !meaning.trim() ||
                        saving === item.item_key}
                      onClick={() => commit(item, true)}>
                      {saving === item.item_key ? "Signing…" : "E-sign →"}
                    </button>
                    <button className="ghost"
                      onClick={() => setSigning(null)}>
                      Cancel
                    </button>
                  </div>
                  <span className="mut" style={{ fontSize: 11 }}>
                    Nothing is recorded until your credentials verify — a
                    failed check signs nothing.
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <button className="ghost" style={{ marginTop: 12, fontSize: 12 }}
        onClick={() => { const v = !showLog; setShowLog(v); if (v) refreshLog(); }}>
        {showLog ? "Hide signing record" : "View signing record"}
      </button>
      {showLog && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          {log === null ? (
            <span className="mut">Loading record…</span>
          ) : log.length === 0 ? (
            <span className="mut">No signatures recorded for {year} yet.</span>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 16, display: "grid", gap: 4 }}>
              {log.map((e, i) => (
                <li key={i}>
                  <code>{e.action}</code> {e.item_key} —{" "}
                  {e.signed_by || "unrecorded"} ·{" "}
                  {e.signed_at.slice(0, 16).replace("T", " ")} UTC
                  {e.reauthenticated ? " · re-authenticated" : ""}
                  {e.meaning && (
                    <div className="mut" style={{ fontSize: 11 }}>
                      “{e.meaning}”
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

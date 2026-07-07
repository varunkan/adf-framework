"use client";
// Form V / NOA register (PM(NOC) Regulations) — one allegation per patent,
// with the two statutory clocks surfaced live: the innovator's 45-day s.6
// action window after NOA service, and the 24-month stay once an action is
// commenced. Serve/action buttons drive the real lifecycle endpoints.
import { useCallback, useEffect, useState } from "react";
import { ALLEGATIONS, lifecycleApi, today, type NoaRecord } from "./api";
import { ProvenancePopover, type Provenance } from "@/components/ProvenancePopover";
import { Term } from "@/components/Term";
import { actionProvenance, stayProvenance } from "@/lib/noaProvenance";

// WS-OPS-PROV (Round-8 BLOCKER, n=14): the base provenance helpers already carry
// the counting rule + citation; here we enrich them, per clock, with (a) the
// governing INSTRUMENT and (b) the source CORRESPONDENCE/date the value derives
// from — read straight off the NOA record (served_date, action_date, court_file).
// Nothing is fabricated: absent a date, the field is simply omitted.
const PMNOC_INSTRUMENT =
  "Patented Medicines (Notice of Compliance) Regulations (SOR/93-133)";

// The 45-day s.6 action window derives from the NOA the sponsor served on the
// innovator (operator-recorded on /noa/{id}/serve).
function actionProvenanceFull(n: NoaRecord): Provenance {
  return {
    ...actionProvenance(n),
    instrument: PMNOC_INSTRUMENT,
    derivedFrom: {
      label: "Notice of Allegation served on the innovator",
      date: n.served_date ?? null,
      source: "operator-recorded service (Serve NOA) — not transmitted to HC",
    },
  };
}

// The 24-month stay derives from the s.6 action the sponsor recorded as
// commenced (with its court file, if entered).
function stayProvenanceFull(n: NoaRecord): Provenance {
  return {
    ...stayProvenance(n),
    instrument: PMNOC_INSTRUMENT,
    derivedFrom: {
      label:
        "s.6 action recorded as commenced" +
        (n.court_file ? ` (court file ${n.court_file})` : ""),
      date: n.action_date ?? n.stay_start ?? null,
      source: "operator-recorded action (Record s.6 action) — not transmitted to HC",
    },
  };
}

const STATUS_LABEL: Record<NoaRecord["status"], string> = {
  draft: "Draft — NOA not yet served",
  served: "NOA served — 45-day action window open",
  action_commenced: "s.6 action commenced",
  clear: "Clear — no s.6 action within 45 days",
  stay_running: "24-month stay running",
  resolved: "Resolved",
};
const STATUS_CHIP: Record<NoaRecord["status"], string> = {
  draft: "",
  served: "blocked",
  action_commenced: "blocked",
  clear: "ready",
  stay_running: "blocked",
  resolved: "ready",
};

function Clock({ label, days, end, prov }: {
  label: string;
  days: number | null | undefined;
  end: string | null;
  // WS3: the provenance of THIS displayed day-count (anchor date + source +
  // counting rule + citation), attached as an inline popover.
  prov: Provenance;
}) {
  if (days == null || !end) return null;
  const tone = days === 0 ? "ok" : days <= 10 ? "warn" : "";
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        <span className={`notice ${tone}`} style={{ padding: "4px 10px", fontSize: 12 }}>
          <b>{days}</b> day{days === 1 ? "" : "s"} left · {label} ends {end}
          {/* WS-OPS-PROV: the calculated-aid caveat, stamped on the clock face
              itself — the full source citation + derivation are in the popover. */}
          <span
            className="mut"
            style={{ marginLeft: 6, fontSize: 10 }}
            title="Calculated aid — verify against the HC record"
          >
            · calculated aid
          </span>
        </span>
        <ProvenancePopover prov={prov} />
      </span>
      {/* Round-9 (operations BLOCKER, n=15): the statutory basis on the ROW
          FACE, not only inside the popover — regulation section, day-count
          convention, and the input date the count runs from. All fields come
          off the provenance record; nothing is fabricated. */}
      <span className="mut" style={{ fontSize: 10.5, paddingLeft: 2 }}>
        {prov.citation} ·{" "}
        {prov.basis === "calendar"
          ? "calendar days (weekends & holidays counted)"
          : "business days"}{" "}
        · from {prov.anchorLabel} {prov.anchorDate || "(not yet set)"}
      </span>
    </span>
  );
}

// Round-9 (operations BLOCKER, n=6): "statutory clocks are not an advanced
// afterthought, they're the whole point, and hiding them is how a deadline
// gets missed." Every LIVE clock on the dossier renders in this prominent
// strip at the top of the page by default — management actions stay in the
// register below. Same Clock + provenance renderers: one source of truth.
export function StatutoryClockStrip({ dossierId, onUrgent }: {
  dossierId: string;
  // fires (once per load) when any clock is at/inside 10 days — the page uses
  // it to auto-open the register so the actionable controls are one glance away
  onUrgent?: () => void;
}) {
  const [items, setItems] = useState<NoaRecord[]>([]);
  useEffect(() => {
    let alive = true;
    lifecycleApi.listNoa(dossierId)
      .then((r) => { if (alive) setItems(r.allegations); })
      .catch(() => {});           // strip is additive — absent on error
    return () => { alive = false; };
  }, [dossierId]);

  const live = items.filter(
    (n) =>
      (n.status === "served" && n.action_days_remaining != null && n.action_window_end) ||
      (n.status === "stay_running" && n.stay_days_remaining != null && n.stay_end)
  );
  const urgent = live.some((n) =>
    Math.min(n.action_days_remaining ?? 99999, n.stay_days_remaining ?? 99999) <= 10);
  useEffect(() => { if (urgent) onUrgent?.(); }, [urgent, onUrgent]);

  if (!live.length) return null;
  return (
    <div className="card glass" style={{ padding: "14px 18px" }}>
      <h2 style={{ margin: "0 0 8px", fontSize: 15 }}>
        ⏱ Statutory clocks — live on this dossier
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {live
          .sort((a, b) =>
            Math.min(a.action_days_remaining ?? 99999, a.stay_days_remaining ?? 99999) -
            Math.min(b.action_days_remaining ?? 99999, b.stay_days_remaining ?? 99999))
          .map((n) => (
            <div key={n.id} style={{ display: "flex", gap: 10,
              alignItems: "baseline", flexWrap: "wrap", fontSize: 13 }}>
              <span style={{ minWidth: 130 }}>
                Patent <b>{n.patent_number}</b>
              </span>
              {n.status === "served" ? (
                <Clock label="45-day action window"
                  days={n.action_days_remaining} end={n.action_window_end}
                  prov={actionProvenanceFull(n)} />
              ) : (
                <Clock label="24-month stay"
                  days={n.stay_days_remaining} end={n.stay_end}
                  prov={stayProvenanceFull(n)} />
              )}
            </div>
          ))}
      </div>
    </div>
  );
}

export function NoaRegister({ dossierId }: { dossierId: string }) {
  const [items, setItems] = useState<NoaRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState("");
  // create form
  const [patent, setPatent] = useState("");
  const [allegation, setAllegation] = useState("not_infringed");
  const [formVDate, setFormVDate] = useState(today());
  // per-row transition inputs
  const [dates, setDates] = useState<Record<string, string>>({});
  const [courtFiles, setCourtFiles] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      setItems((await lifecycleApi.listNoa(dossierId)).allegations);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);
  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    setBusyId("new");
    setErr("");
    try {
      await lifecycleApi.createNoa({
        dossier_id: dossierId,
        patent_number: patent,
        allegation,
        form_v_date: formVDate,
      });
      setPatent("");
      setAdding(false);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusyId("");
    }
  }

  async function transition(n: NoaRecord, kind: "serve" | "action") {
    const date = dates[n.id] || today();
    setBusyId(n.id);
    setErr("");
    try {
      if (kind === "serve") await lifecycleApi.serveNoa(n.id, date);
      else await lifecycleApi.actionNoa(n.id, date, courtFiles[n.id] || "");
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="card glass" style={{ padding: 22 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Form V / NOA register</h2>
        <span className="mut" style={{ fontSize: 12 }}>
          {items.length} allegation{items.length === 1 ? "" : "s"}
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "File Form V +"}
        </button>
      </div>
      <p className="mut" style={{ margin: "6px 0 0", maxWidth: "70ch" }}>
        One <Term k="Form V" /> allegation per patent/CSP on the Patent
        Register. Non-infringement and invalidity allegations require a{" "}
        <Term k="NOA">Notice of Allegation</Term> served on the innovator —
        service opens their 45-day window to sue; a commenced{" "}
        <Term k="s.6" /> action triggers the <Term k="24-month stay" />.
      </p>
      <p className="mut" style={{ margin: "6px 0 0", fontSize: 12, maxWidth: "70ch" }}>
        Record only — <b>Serve NOA</b> and <b>Record s.6 action</b> log what has
        already happened out in the world and start the tracking clocks. They do
        not serve, file or transmit anything with Health Canada or the courts.
      </p>

      {adding && (
        <div className="card" style={{ marginTop: 14, padding: 16 }}>
          <div className="field-row">
            <div>
              <label>Patent / CSP number</label>
              <input
                value={patent}
                onChange={(e) => setPatent(e.target.value)}
                placeholder="e.g. CA2534789"
              />
            </div>
            <div>
              <label>Allegation</label>
              <select
                value={allegation}
                onChange={(e) => setAllegation(e.target.value)}
              >
                {Object.entries(ALLEGATIONS).map(([k, label]) => (
                  <option key={k} value={k}>{label}</option>
                ))}
              </select>
            </div>
            <div>
              <label>Form V date</label>
              <input
                type="date"
                value={formVDate}
                onChange={(e) => setFormVDate(e.target.value)}
              />
            </div>
          </div>
          <div className="cta-row">
            <button onClick={create} disabled={busyId === "new" || !patent.trim()}>
              {busyId === "new" ? "Filing…" : "File allegation"}
            </button>
          </div>
        </div>
      )}

      {err && <div className="notice bad" style={{ marginTop: 12 }}>{err}</div>}

      {loading ? (
        <div className="mut" style={{ marginTop: 14 }}>Loading NOA register…</div>
      ) : items.length === 0 ? (
        <div className="notice" style={{ marginTop: 14 }}>
          No Form V allegations on file. If no patents are listed against the
          reference product, none are needed.
        </div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: "14px 0 0",
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {items.map((n) => (
            <li key={n.id} className="card" style={{ padding: "12px 16px" }}>
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "baseline",
                  flexWrap: "wrap",
                }}
              >
                <span style={{ fontWeight: 700 }}>{n.patent_number}</span>
                <span className="mut" style={{ fontSize: 13 }}>
                  {n.allegation_label}
                </span>
                <span className="spacer" style={{ marginLeft: "auto" }} />
                <span className={`chip ${STATUS_CHIP[n.status] || ""}`}>
                  {STATUS_LABEL[n.status] || n.status}
                </span>
              </div>
              <div
                className="mut"
                style={{
                  display: "flex",
                  gap: 14,
                  flexWrap: "wrap",
                  fontSize: 12,
                  marginTop: 6,
                }}
              >
                <span>Form V {n.form_v_date}</span>
                {n.served_date && <span>served {n.served_date}</span>}
                {n.action_date && (
                  <span>
                    action {n.action_date}
                    {n.court_file ? ` (${n.court_file})` : ""}
                  </span>
                )}
                {!n.noa_required && <span>no NOA service required</span>}
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  flexWrap: "wrap",
                  marginTop: 8,
                }}
              >
                {n.status === "served" && (
                  <Clock
                    label="45-day action window"
                    days={n.action_days_remaining}
                    end={n.action_window_end}
                    prov={actionProvenanceFull(n)}
                  />
                )}
                {(n.status === "stay_running" ||
                  n.status === "action_commenced") && (
                  <Clock
                    label="24-month stay"
                    days={n.stay_days_remaining}
                    end={n.stay_end}
                    prov={stayProvenanceFull(n)}
                  />
                )}
                {n.status === "draft" && n.noa_required && (
                  <>
                    <input
                      type="date"
                      aria-label={`Service date for ${n.patent_number}`}
                      style={{ width: "auto" }}
                      value={dates[n.id] || today()}
                      onChange={(e) =>
                        setDates((m) => ({ ...m, [n.id]: e.target.value }))
                      }
                    />
                    <button
                      onClick={() => transition(n, "serve")}
                      disabled={busyId === n.id}
                    >
                      {busyId === n.id ? "Serving…" : "Serve NOA"}
                    </button>
                  </>
                )}
                {n.status === "served" && (
                  <>
                    <input
                      type="date"
                      aria-label={`Action date for ${n.patent_number}`}
                      style={{ width: "auto" }}
                      value={dates[n.id] || today()}
                      onChange={(e) =>
                        setDates((m) => ({ ...m, [n.id]: e.target.value }))
                      }
                    />
                    <input
                      aria-label={`Court file for ${n.patent_number}`}
                      style={{ width: 180 }}
                      placeholder="Court file (optional)"
                      value={courtFiles[n.id] || ""}
                      onChange={(e) =>
                        setCourtFiles((m) => ({ ...m, [n.id]: e.target.value }))
                      }
                    />
                    <button
                      className="ghost"
                      onClick={() => transition(n, "action")}
                      disabled={busyId === n.id}
                    >
                      {busyId === n.id ? "Recording…" : "Record s.6 action"}
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

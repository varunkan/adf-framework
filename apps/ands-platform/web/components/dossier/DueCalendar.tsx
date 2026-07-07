"use client";
// Round-9 catalog MAJOR — "No portfolio-level rollup or exportable status
// reporting" (n=2; cro_pm): the one missing piece was a DUE-DATE CALENDAR
// (the Portfolio page already ships the rollup cards, blocked flags, deadline
// strip and one-click CSV status export). This cross-dossier month calendar
// renders every dossier's named-clock target date; it is mounted on the
// catalog (Monday-morning view over ALL dossiers) and links each entry to its
// dossier.
//
// HONEST: entries are the same client-set targets the "Soonest due" column
// shows (named clock; stored on content-plan items) — never an invented HC
// statutory date.
import { useMemo, useState } from "react";
import Link from "next/link";
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import type { CatalogListItem } from "./catalogApi";

const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ym(d: Date): [number, number] { return [d.getFullYear(), d.getMonth()]; }

export function DueCalendar({ items }: { items: CatalogListItem[] }) {
  const [open, setOpen] = useState(false);
  const [[year, month], setYm] = useState<[number, number]>(ym(new Date()));

  // due entries bucketed by ISO date (YYYY-MM-DD)
  const byDate = useMemo(() => {
    const m = new Map<string, CatalogListItem[]>();
    for (const d of items) {
      if (!d.soonest_due) continue;
      m.set(d.soonest_due, [...(m.get(d.soonest_due) || []), d]);
    }
    return m;
  }, [items]);

  const withDates = useMemo(
    () => items.filter((d) => !!d.soonest_due).length, [items]);

  // calendar cells for the shown month, Monday-first
  const cells = useMemo(() => {
    const first = new Date(year, month, 1);
    const lead = (first.getDay() + 6) % 7; // Mon=0
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const out: (number | null)[] = [];
    for (let i = 0; i < lead; i++) out.push(null);
    for (let d = 1; d <= daysInMonth; d++) out.push(d);
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, [year, month]);

  const todayIso = new Date().toISOString().slice(0, 10);
  const iso = (day: number) =>
    `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

  function shift(delta: number) {
    const d = new Date(year, month + delta, 1);
    setYm(ym(d));
  }

  return (
    <section className="card glass" aria-label="Due-date calendar"
      style={{ padding: "12px 16px", marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        flexWrap: "wrap" }}>
        <CalendarDays size={15} aria-hidden />
        <b style={{ fontSize: 14 }}>Due-date calendar</b>
        <span className="mut" style={{ fontSize: 12 }}>
          {withDates} dossier{withDates === 1 ? "" : "s"} with a target date ·
          client-set targets (named clocks), never invented HC dates
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          style={{ fontSize: 12, display: "inline-flex", alignItems: "center",
            gap: 4 }}>
          {open ? <ChevronDown size={14} aria-hidden />
            : <ChevronRight size={14} aria-hidden />}
          {open ? "Hide calendar" : "Show calendar"}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button className="ghost" aria-label="Previous month"
              style={{ padding: "2px 8px" }} onClick={() => shift(-1)}>
              <ChevronLeft size={14} aria-hidden />
            </button>
            <b style={{ fontSize: 13 }}>{MONTHS[month]} {year}</b>
            <button className="ghost" aria-label="Next month"
              style={{ padding: "2px 8px" }} onClick={() => shift(1)}>
              <ChevronRight size={14} aria-hidden />
            </button>
          </div>
          <div style={{ overflowX: "auto", marginTop: 8 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(84px, 1fr))",
              gap: 4, minWidth: 620 }}>
              {DOW.map((d) => (
                <div key={d} className="mut" style={{ fontSize: 11,
                  textAlign: "center" }}>{d}</div>
              ))}
              {cells.map((day, i) => {
                const dateIso = day ? iso(day) : "";
                const due = day ? byDate.get(dateIso) || [] : [];
                const overdue = !!day && dateIso < todayIso && due.length > 0;
                return (
                  <div key={i} className={day ? "card" : ""}
                    style={{ minHeight: 56, padding: day ? "4px 6px" : 0,
                      opacity: day ? 1 : 0,
                      outline: dateIso === todayIso
                        ? "1px solid var(--line)" : undefined }}>
                    {day && (
                      <>
                        <div className="mut" style={{ fontSize: 11 }}>{day}</div>
                        {due.map((d) => (
                          <Link key={d.dossier_id}
                            href={`/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`}
                            className={`chip ${overdue ? "blocked" : ""}`}
                            title={`${d.dossier_id} · ${d.title} — ` +
                              `${d.soonest_due_meta?.clock_type || "client-set target"}` +
                              (d.soonest_due_meta?.item_title
                                ? ` · ${d.soonest_due_meta.item_title}` : "")}
                            style={{ display: "block", fontSize: 10.5,
                              padding: "1px 6px", marginTop: 2,
                              overflow: "hidden", textOverflow: "ellipsis",
                              whiteSpace: "nowrap" }}>
                            {d.dossier_id}
                          </Link>
                        ))}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

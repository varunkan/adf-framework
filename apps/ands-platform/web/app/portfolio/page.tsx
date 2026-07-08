"use client";
// CRO portfolio dashboard — every dossier in the tenant on one screen.
// List payload gives id/title/type/tower/gate; fee state needs per-dossier
// content, fetched in parallel after first paint so rows land immediately.
import { useEffect, useState } from "react";
import { withIntegrityManifest } from "@/lib/csvIntegrity";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import type { ContentState, DossierListItem } from "@/lib/dossierTypes";
import { PortfolioRow, missingInfoOf, type FeeState, type NoaClock,
  type ValState } from "@/components/portfolio/PortfolioRow";
import type { M1Labelling } from "@/components/portfolio/MiniTower";
import { SummaryCards } from "@/components/portfolio/SummaryCards";
import { SponsorRollup } from "@/components/portfolio/SponsorRollup";
import { StartHereTour } from "@/components/portfolio/StartHereTour";
import { BilingualNote } from "@/components/portfolio/BilingualNote";
import { noaClockFrom } from "@/lib/noaProvenance";
import { collabApi, type DossierTaskSummary } from "@/lib/collabApi";
import { dueMeta } from "@/lib/deadline";
import {
  SponsorScope,
  ALL_SPONSORS,
  UNASSIGNED_SPONSOR,
  matchesSponsor,
} from "@/components/SponsorScope";

// Round-9 (operations MAJOR, n=2; labelling_specialist): Module 1 labelling
// completeness + missing-FR flag, derived from the dossier's REAL section
// state (1.3.x documents) — same content payload the fee chip already loads.
function labellingOf(c: ContentState): M1Labelling | undefined {
  const m1 = c.modules?.find((m) => m.module === "1");
  if (!m1) return undefined;
  const nodes = m1.nodes.filter(
    (n) => n.kind === "document" && n.section.startsWith("1.3") &&
           n.applicability !== "na" && n.applicability !== "suppressed");
  if (!nodes.length) return undefined;
  return {
    total: nodes.length,
    filled: nodes.filter((n) => n.status === "complete").length,
    // FR flagged missing when the EN document exists but no FR counterpart
    frMissing: nodes
      .filter((n) => n.bilingual && (n.languages || []).includes("en") &&
                     !(n.languages || []).includes("fr"))
      .map((n) => n.section),
  };
}

// Round-9 (operations MAJOR, n=3): the grid's one-click quick filters.
type QuickFilter = "all" | "attention" | "missing";

export default function PortfolioPage() {
  const [allItems, setAllItems] = useState<DossierListItem[]>([]);
  const [fees, setFees] = useState<Record<string, FeeState>>({});
  const [noas, setNoas] = useState<Record<string, NoaClock>>({});
  // Round-9: per-dossier structural-validation state + M1 labelling, filled
  // from the same per-dossier content fetch the fee chips use.
  const [vals, setVals] = useState<Record<string, ValState>>({});
  const [labs, setLabs] = useState<Record<string, M1Labelling>>({});
  // Round-9 (n=3): 'Blocked / due soon' quick filter; (n=1) 'missing info'.
  const [quick, setQuick] = useState<QuickFilter>("all");
  // Round-9 (n=1; cdmo_ra_manager): keep the grid scannable at 60+ dossiers —
  // paginate instead of rendering every row at once.
  const [visible, setVisible] = useState(20);
  // Round-9 (n=3): date-range + category filters on the status export.
  const [expFrom, setExpFrom] = useState("");
  const [expTo, setExpTo] = useState("");
  const [expCat, setExpCat] = useState<"all" | "ready" | "blocked">("all");
  // WS7: open-task roll-up by dossier (assignees + blocked), one aggregate call.
  const [collab, setCollab] = useState<Record<string, DossierTaskSummary>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  // WS-OPS-TENANT: per-client/sponsor scope is the FIRST control on Portfolio.
  const [sponsor, setSponsor] = useState<string>(ALL_SPONSORS);
  // WS-OPS-TENANT (density): the dossier list can be a wall. Collapse it behind
  // a progressive-disclosure toggle so the scope, totals and the deadline strip
  // read first; the full grid opens on demand. Defaults open when the scope is
  // small (≤ 6) so a focused sponsor view isn't hidden.
  const [showList, setShowList] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { dossiers } = await dossierApi.listDossiers();
        if (!alive) return;
        setAllItems(dossiers);
        setLoading(false);
        // WS7: one aggregate call for the whole portfolio's open tasks →
        // assignees + blocked status per dossier (collaboration service).
        collabApi
          .taskSummary()
          .then((s) => {
            if (alive) setCollab(s.by_dossier);
          })
          .catch(() => {
            /* collaboration offline — rows simply show no assignees */
          });
        // fee state lives on per-dossier content — fill rows as each lands
        dossiers.forEach(async (d) => {
          try {
            const c = await dossierApi.getContent(d.dossier_id);
            if (!alive) return;
            const f = c.fees;
            const feeAmount = f?.mitigation?.payable ?? f?.review_fee?.amount;
            const state: FeeState = f?.fee_paid
              ? { kind: "paid" }
              : f?.mitigation?.waived
                ? { kind: "waived" }
                // non-ANDS type: fee not auto-computed (amount null) → Schedule 1,
                // never a misleading "$0 due"
                : feeAmount == null
                  ? { kind: "schedule1" }
                  : {
                      kind: "due",
                      amount: feeAmount,
                      currency: f?.review_fee?.currency || "CAD",
                    };
            setFees((m) => ({ ...m, [d.dossier_id]: state }));
            // Round-9 (n=1; regops_publisher): technical-validation status on
            // the row — from the same content payload, no extra request.
            if (c.validation) {
              const v: ValState = {
                passed: Boolean(c.validation.passed),
                errors: c.validation.errors?.length ?? 0,
                evalCleared: Boolean(c.evalidator?.cleared),
              };
              setVals((m) => ({ ...m, [d.dossier_id]: v }));
            }
            // Round-9 (n=2; labelling_specialist): M1 labelling + FR flag.
            const lab = labellingOf(c);
            if (lab) setLabs((m) => ({ ...m, [d.dossier_id]: lab }));
          } catch {
            if (alive)
              setFees((m) => ({ ...m, [d.dossier_id]: { kind: "unknown" } }));
          }
        });
        // live PM(NOC) clocks — a served NOA / running stay is the deadline
        // a regulatory PM most needs to see coming
        dossiers.forEach(async (d) => {
          try {
            const r = await fetch(
              `/api/lifecycle/noa?dossier_id=${encodeURIComponent(d.dossier_id)}`,
              { cache: "no-store" });
            if (!r.ok || !alive) return;
            const { allegations: recs = [] } = await r.json();
            // WS3: derive the clock AND its provenance from the raw records —
            // the anchor date/source/basis travel to the row's popover.
            const clock = noaClockFrom(recs);
            if (clock.kind !== "none")
              setNoas((m) => ({ ...m, [d.dossier_id]: clock }));
          } catch { /* lifecycle offline — row simply shows no clock */ }
        });
      } catch (e) {
        if (alive) {
          setErr(String(e));
          setLoading(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // WS-OPS-TENANT: everything below the scope selector operates on the dossiers
  // in the chosen sponsor scope only — totals, deadline strip, grid and the CSV
  // export all honor it, so a PM reports on exactly one client at a time.
  const items = allItems.filter((d) => matchesSponsor(d, sponsor));

  const ready = items.filter((d) => d.gate?.complete).length;
  const blocked = items.length - ready;

  // WS6 deadline rollup: dossiers with a content-plan deadline in the next
  // 30 days (or already overdue), soonest first — the PM's "who is blocked on
  // what" strip. Derived purely from the soonest_due each row already carries.
  const upcoming = items
    .map((d) => ({ d, dm: dueMeta(d.soonest_due) }))
    .filter((x) => x.dm && (x.dm.overdue || x.dm.soon))
    .sort((a, b) => a.dm!.days - b.dm!.days);
  const overdueCount = upcoming.filter((x) => x.dm!.overdue).length;

  // Round-9 (operations MAJOR, n=3): one-click 'Blocked / due soon' quick
  // filter — an at-risk row is collab-blocked OR overdue/due within 30 days.
  const needsAttention = (d: DossierListItem) => {
    const dm = dueMeta(d.soonest_due);
    return Boolean(collab[d.dossier_id]?.blocked) ||
           Boolean(dm && (dm.overdue || dm.soon));
  };
  // Round-9 (operations minor, n=1; cro_pm): 'missing info' quick filter.
  const attentionCount = items.filter(needsAttention).length;
  const missingCount = items.filter((d) => missingInfoOf(d).length > 0).length;
  const gridItems =
    quick === "attention" ? items.filter(needsAttention)
    : quick === "missing" ? items.filter((d) => missingInfoOf(d).length > 0)
    : items;
  // Round-9 (n=1; cdmo_ra_manager): paginate the grid — scannable at 60+.
  const shown = gridItems.slice(0, visible);

  // reset pagination whenever the scope or quick filter changes
  useEffect(() => { setVisible(20); }, [sponsor, quick]);

  // Round-9 (operations minor, n=1; quality_director_newcomer): "the deadline
  // card [should] email or alert me, not just show on a page I have to
  // remember to open." Largest HONEST subset: a real alert path that works
  // today — an .ics calendar file with built-in 7-day and 1-day reminders for
  // every upcoming/overdue deadline, so the user's own calendar alerts them.
  // In-app email alerts are NOT built; that is stated plainly beside the
  // button rather than implied.
  function exportDeadlinesIcs() {
    const escIcs = (s: string) =>
      s.replace(/\\/g, "\\\\").replace(/[,;]/g, "\\$&").replace(/\n/g, "\\n");
    const stamp =
      new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
    const lines = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//ANDS Studio//portfolio deadlines//EN",
      ...upcoming.flatMap(({ d, dm }) => [
        "BEGIN:VEVENT",
        `UID:${d.dossier_id}-${dm!.iso}@ands-studio`,
        `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${dm!.iso.replace(/-/g, "")}`,
        `SUMMARY:${escIcs(`${d.dossier_id} content-plan deadline — ${d.title}`)}`,
        `DESCRIPTION:${escIcs(
          `ANDS Studio portfolio deadline (calculated aid — verify against ` +
          `your plan). Owner: ${d.owner || "unassigned"}. Client: ${
            d.sponsor || "unassigned"}.`)}`,
        "BEGIN:VALARM",
        "TRIGGER:-P7D",
        "ACTION:DISPLAY",
        `DESCRIPTION:${escIcs(`${d.dossier_id} deadline in 7 days`)}`,
        "END:VALARM",
        "BEGIN:VALARM",
        "TRIGGER:-P1D",
        "ACTION:DISPLAY",
        `DESCRIPTION:${escIcs(`${d.dossier_id} deadline tomorrow`)}`,
        "END:VALARM",
        "END:VEVENT",
      ]),
      "END:VCALENDAR",
    ];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
      new Blob([lines.join("\r\n") + "\r\n"], { type: "text/calendar" }));
    a.download = "ands-deadlines.ics";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // client-facing status export — PMs report to sponsors in spreadsheets
  async function exportStatus() {
    const esc = (s: unknown) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    // Round-9 (operations MAJOR, n=3): optional date-range + category export
    // filters — when a due-date range is set, rows without a due date are
    // excluded (stated on the control).
    const exportItems = items.filter((d) => {
      if (expCat === "ready" && !d.gate?.complete) return false;
      if (expCat === "blocked" && d.gate?.complete) return false;
      if (expFrom || expTo) {
        if (!d.soonest_due) return false;
        if (expFrom && d.soonest_due < expFrom) return false;
        if (expTo && d.soonest_due > expTo) return false;
      }
      return true;
    });
    const rows = [
      // WS6: owner / client / soonest due travel to the client status report —
      // a PM reports ownership, client segregation and deadlines to sponsors.
      ["dossier_id", "product", "owner", "client", "soonest_due",
       "submission_type", "modules_passed", "modules_applicable",
       "filing_gate", "fee_status"],
      ...exportItems.map((d) => {
        const passed = d.tower.filter((t) => t.state === "pass").length;
        const applic = d.tower.filter((t) => t.state !== "na").length;
        const fee = fees[d.dossier_id];
        return [d.dossier_id, d.title, d.owner || "", d.sponsor || "",
                d.soonest_due || "", d.submission_type, passed, applic,
                d.gate?.complete ? "READY" : "in progress",
                fee?.kind === "due"
                  ? `due ${(fee as any).amount} ${(fee as any).currency}`
                  : fee?.kind === "schedule1"
                    ? "see HC Schedule 1"
                    : fee?.kind || ""];
      }),
    ];
    // Round-9 (n=5): versioned schema + all-UTC + SHA-256 manifest — the
    // client status report is evidence a PM forwards; make edits detectable.
    const csv = await withIntegrityManifest(
      rows.map((r) => r.map(esc).join(",")).join("\n"),
      "ands.portfolio-status", "1");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download =
      sponsor === ALL_SPONSORS
        ? "portfolio-status.csv"
        : `portfolio-status-${sponsor.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <>
      <TopNav subtitle="portfolio" />
      <main className="dossier-home">
        <header style={{ marginBottom: 8 }}>
          <div className="eyebrow">Operations</div>
          <h1>Portfolio</h1>
          <p className="lede">
            Every product dossier in your organisation — module progress, filing
            gate and fee status at a glance.
          </p>
          <p className="mut" style={{ maxWidth: "72ch" }}>
            Every change on this page is captured in the dossier’s append-only
            audit trail — actor and workspace stamped, sequence-numbered,
            exportable for inspections (open a dossier → Audit).
          </p>
          {/* Round-9 (operations MAJOR, n=2): explicit FR-coverage statement */}
          <BilingualNote />
        </header>

        {/* Round-9 (operations MAJOR, n=15): the dismissible, re-launchable
            'Start here' guided tour across the four operations pages. */}
        <StartHereTour page="portfolio" />

        {/* WS-OPS-TENANT: per-client/sponsor scope + isolation statement — the
            FIRST control on Portfolio, before the roll-up and grid. */}
        {!loading && allItems.length > 0 && (
          <section style={{ marginTop: 20 }}>
            <SponsorScope
              items={allItems}
              value={sponsor}
              onChange={setSponsor}
              count={items.length}
            />
            {items.length > 0 && (
              <div className="affordance-bar" style={{ flexWrap: "wrap",
                alignItems: "baseline" }}>
                <button className="ghost" onClick={exportStatus}>
                  Export client status report (CSV)
                  {sponsor !== ALL_SPONSORS ? " — this client only" : ""}
                </button>
                {/* Round-9 (operations MAJOR, n=3): date-range + category
                    filters on the status export — not only a flat CSV. */}
                <details style={{ fontSize: 12 }}>
                  <summary className="mut" style={{ cursor: "pointer" }}>
                    Export filters (date range · category)
                  </summary>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                    alignItems: "center", marginTop: 6 }}>
                    <label style={{ margin: 0 }}>Due from{" "}
                      <input type="date" value={expFrom} style={{ width: "auto" }}
                        onChange={(e) => setExpFrom(e.target.value)} />
                    </label>
                    <label style={{ margin: 0 }}>to{" "}
                      <input type="date" value={expTo} style={{ width: "auto" }}
                        onChange={(e) => setExpTo(e.target.value)} />
                    </label>
                    <label style={{ margin: 0 }}>Status{" "}
                      <select value={expCat} style={{ width: "auto" }}
                        onChange={(e) =>
                          setExpCat(e.target.value as typeof expCat)}>
                        <option value="all">all</option>
                        <option value="ready">ready to file</option>
                        <option value="blocked">blocked / in progress</option>
                      </select>
                    </label>
                    <span className="mut">
                      A due-date range excludes dossiers with no due date set.
                    </span>
                  </div>
                </details>
                {/* Round-9 (operations MAJOR, n=5): official-record status of
                    the export, stated in-app beside the button. */}
                <span className="mut" style={{ fontSize: 11.5,
                  flexBasis: "100%" }}>
                  Exports are hash-manifested <b>convenience copies</b> (all
                  timestamps UTC) — the append-only server-side audit trail
                  remains the official record.
                </span>
              </div>
            )}
          </section>
        )}

        {err && <div className="notice bad" style={{ marginTop: 16 }}>{err}</div>}

        {loading ? (
          <div className="mut" style={{ marginTop: 20 }}>Loading portfolio…</div>
        ) : allItems.length === 0 ? (
          <div className="notice" style={{ marginTop: 16 }}>
            No dossiers yet.{" "}
            <Link href="/dossiers">Create one in the dossier manager →</Link>
          </div>
        ) : items.length === 0 ? (
          <div className="notice" style={{ marginTop: 16 }}>
            No dossiers for the selected client / sponsor. Choose a different
            scope above, or “All sponsors in this workspace”.
          </div>
        ) : (
          <>
            <SummaryCards
              total={items.length}
              ready={ready}
              blocked={blocked}
              scopeLabel={
                sponsor === ALL_SPONSORS
                  ? undefined
                  : sponsor === UNASSIGNED_SPONSOR
                    ? "Unassigned (no REP sponsor set)"
                    : sponsor
              }
            />

            {/* Round-9 (operations MAJOR, n=3): the cross-sponsor roll-up —
                always computed over EVERY dossier in the workspace, so it
                survives the scope filter above. */}
            <SponsorRollup items={allItems} collab={collab} />

            {upcoming.length > 0 && (
              <section className="card glass" style={{ marginTop: 20, padding: "16px 18px" }}
                aria-label="Upcoming deadlines">
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                  <h2 style={{ margin: 0, fontSize: 16 }}>
                    ⏳ {upcoming.length} dossier{upcoming.length === 1 ? "" : "s"} with a deadline in the next 30 days
                  </h2>
                  {overdueCount > 0 && (
                    <span className="chip blocked">
                      {overdueCount} overdue
                    </span>
                  )}
                  <span className="mut" style={{ fontSize: 12 }}>soonest first</span>
                  <span style={{ marginLeft: "auto" }} />
                  {/* Round-9 (n=1): a working alert path today — calendar
                      reminders; email alerts honestly stated as not built. */}
                  <button className="ghost" style={{ fontSize: 12 }}
                    onClick={exportDeadlinesIcs}
                    title="Downloads an .ics file with a 7-day and a 1-day reminder per deadline — your own calendar alerts you.">
                    Add reminders to my calendar (.ics)
                  </button>
                </div>
                <p className="mut" style={{ margin: "6px 0 0", fontSize: 11.5 }}>
                  In-app email alerts are <b>not built yet</b> — stated plainly.
                  The calendar file above gives you real reminders today.
                </p>
                <ul style={{ listStyle: "none", margin: "12px 0 0", padding: 0,
                  display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {upcoming.slice(0, 8).map(({ d, dm }) => (
                    <li key={d.dossier_id}>
                      <Link className={`chip ${dm!.overdue || dm!.days <= 7 ? "blocked" : ""}`}
                        href={`/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`}
                        title={`${d.title}${d.owner ? ` · owner ${d.owner}` : ""}${d.sponsor ? ` · client ${d.sponsor}` : ""}`}>
                        {d.dossier_id} · {dm!.iso} ({dm!.label})
                        {d.owner ? ` · ${d.owner}` : ""}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* WS-OPS-TENANT (density / progressive disclosure): scope, totals
                and the deadline strip read first; the full dossier grid opens
                on demand so the four operations surfaces aren't a wall at once.
                Nothing is removed — the grid is one click away and stays open. */}
            <div style={{ margin: "20px 0 0", display: "flex", gap: 8,
              flexWrap: "wrap", alignItems: "center" }}>
              <button
                className="ghost"
                aria-expanded={showList}
                aria-controls="portfolio-grid"
                onClick={() => setShowList((v) => !v)}
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span>{showList ? "▾" : "▸"}</span>
                {showList ? "Hide" : "Show"} dossier grid ({items.length})
              </button>
              {/* Round-9 (operations MAJOR, n=3 + minor, n=1): the default
                  quick filters — 'Blocked / due soon' and 'missing info'. */}
              <span role="group" aria-label="Quick filters"
                style={{ display: "inline-flex", gap: 6 }}>
                <button className={`chip ${quick === "all" ? "ready" : ""}`}
                  aria-pressed={quick === "all"}
                  onClick={() => setQuick("all")}>
                  All ({items.length})
                </button>
                <button className={`chip ${quick === "attention" ? "blocked" : ""}`}
                  aria-pressed={quick === "attention"}
                  title="Dossiers blocked by an overdue task, past a deadline, or due within 30 days"
                  onClick={() => setQuick("attention")}>
                  Blocked / due soon ({attentionCount})
                </button>
                <button className={`chip ${quick === "missing" ? "blocked" : ""}`}
                  aria-pressed={quick === "missing"}
                  title="Dossiers with a blank owner, client or due date — chase these before exporting a client status report"
                  onClick={() => setQuick("missing")}>
                  Missing info ({missingCount})
                </button>
              </span>
            </div>

            {showList && (
              <>
              <ul
                id="portfolio-grid"
                aria-label="Product dossiers"
                style={{
                  listStyle: "none",
                  margin: "12px 0 0",
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                {shown.map((d) => (
                  <li key={d.dossier_id}>
                    <PortfolioRow
                      d={d}
                      fee={fees[d.dossier_id] ?? { kind: "loading" }}
                      noa={noas[d.dossier_id]}
                      collab={collab[d.dossier_id]}
                      val={vals[d.dossier_id]}
                      labelling={labs[d.dossier_id]}
                    />
                  </li>
                ))}
              </ul>
              {/* Round-9 (n=1; cdmo_ra_manager): pagination keeps the grid
                  fast and scannable at realistic (60+) portfolio scale. */}
              {gridItems.length > visible && (
                <div style={{ margin: "12px 0 0", display: "flex", gap: 8 }}>
                  <button className="ghost" style={{ fontSize: 12 }}
                    onClick={() => setVisible((v) => v + 20)}>
                    Show 20 more ({gridItems.length - visible} remaining)
                  </button>
                  <button className="ghost" style={{ fontSize: 12 }}
                    onClick={() => setVisible(gridItems.length)}>
                    Show all {gridItems.length}
                  </button>
                </div>
              )}
              {gridItems.length === 0 && (
                <div className="notice" style={{ marginTop: 12 }}>
                  No dossiers match the “{quick === "attention"
                    ? "Blocked / due soon" : "Missing info"}” quick filter in
                  this scope.
                </div>
              )}
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}

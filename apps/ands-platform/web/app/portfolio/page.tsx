"use client";
// CRO portfolio dashboard — every dossier in the tenant on one screen.
// List payload gives id/title/type/tower/gate; fee state needs per-dossier
// content, fetched in parallel after first paint so rows land immediately.
import { useEffect, useState } from "react";
import { withIntegrityManifest } from "@/lib/csvIntegrity";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import type { DossierListItem } from "@/lib/dossierTypes";
import { PortfolioRow, type FeeState, type NoaClock } from "@/components/portfolio/PortfolioRow";
import { SummaryCards } from "@/components/portfolio/SummaryCards";
import { noaClockFrom } from "@/lib/noaProvenance";
import { collabApi, type DossierTaskSummary } from "@/lib/collabApi";
import { dueMeta } from "@/lib/deadline";
import {
  SponsorScope,
  ALL_SPONSORS,
  UNASSIGNED_SPONSOR,
  matchesSponsor,
} from "@/components/SponsorScope";

export default function PortfolioPage() {
  const [allItems, setAllItems] = useState<DossierListItem[]>([]);
  const [fees, setFees] = useState<Record<string, FeeState>>({});
  const [noas, setNoas] = useState<Record<string, NoaClock>>({});
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
            const state: FeeState = f?.fee_paid
              ? { kind: "paid" }
              : f?.mitigation?.waived
                ? { kind: "waived" }
                : {
                    kind: "due",
                    amount: f?.mitigation?.payable ?? f?.review_fee?.amount ?? 0,
                    currency: f?.review_fee?.currency || "CAD",
                  };
            setFees((m) => ({ ...m, [d.dossier_id]: state }));
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

  // client-facing status export — PMs report to sponsors in spreadsheets
  async function exportStatus() {
    const esc = (s: unknown) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const rows = [
      // WS6: owner / client / soonest due travel to the client status report —
      // a PM reports ownership, client segregation and deadlines to sponsors.
      ["dossier_id", "product", "owner", "client", "soonest_due",
       "submission_type", "modules_passed", "modules_applicable",
       "filing_gate", "fee_status"],
      ...items.map((d) => {
        const passed = d.tower.filter((t) => t.state === "pass").length;
        const applic = d.tower.filter((t) => t.state !== "na").length;
        const fee = fees[d.dossier_id];
        return [d.dossier_id, d.title, d.owner || "", d.sponsor || "",
                d.soonest_due || "", d.submission_type, passed, applic,
                d.gate?.complete ? "READY" : "in progress",
                fee?.kind === "due"
                  ? `due ${(fee as any).amount} ${(fee as any).currency}`
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
        </header>

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
              <div className="affordance-bar">
                <button className="ghost" onClick={exportStatus}>
                  Export client status report (CSV)
                  {sponsor !== ALL_SPONSORS ? " — this client only" : ""}
                </button>
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
                </div>
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
            <div style={{ margin: "20px 0 0" }}>
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
            </div>

            {showList && (
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
                {items.map((d) => (
                  <li key={d.dossier_id}>
                    <PortfolioRow
                      d={d}
                      fee={fees[d.dossier_id] ?? { kind: "loading" }}
                      noa={noas[d.dossier_id]}
                      collab={collab[d.dossier_id]}
                    />
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </main>
    </>
  );
}

"use client";
// CRO portfolio dashboard — every dossier in the tenant on one screen.
// List payload gives id/title/type/tower/gate; fee state needs per-dossier
// content, fetched in parallel after first paint so rows land immediately.
import { useEffect, useState } from "react";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import type { DossierListItem } from "@/lib/dossierTypes";
import { UserChip } from "@/components/UserChip";
import { PortfolioRow, type FeeState } from "@/components/portfolio/PortfolioRow";
import { SummaryCards } from "@/components/portfolio/SummaryCards";

export default function PortfolioPage() {
  const [items, setItems] = useState<DossierListItem[]>([]);
  const [fees, setFees] = useState<Record<string, FeeState>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { dossiers } = await dossierApi.listDossiers();
        if (!alive) return;
        setItems(dossiers);
        setLoading(false);
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

  const ready = items.filter((d) => d.gate?.complete).length;
  const blocked = items.length - ready;

  // client-facing status export — PMs report to sponsors in spreadsheets
  function exportStatus() {
    const esc = (s: unknown) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const rows = [
      ["dossier_id", "product", "submission_type", "modules_passed",
       "modules_applicable", "filing_gate", "fee_status"],
      ...items.map((d) => {
        const passed = d.tower.filter((t) => t.state === "pass").length;
        const applic = d.tower.filter((t) => t.state !== "na").length;
        const fee = fees[d.dossier_id];
        return [d.dossier_id, d.title, d.submission_type, passed, applic,
                d.gate?.complete ? "READY" : "in progress",
                fee?.kind === "due"
                  ? `due ${(fee as any).amount} ${(fee as any).currency}`
                  : fee?.kind || ""];
      }),
    ];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(
      [rows.map((r) => r.map(esc).join(",")).join("\n")],
      { type: "text/csv" }));
    a.download = "portfolio-status.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <>
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio <small>· portfolio</small>
        </span>
        <span className="spacer" />
        <UserChip />
        <Link className="chip" href="/dossiers">Dossier manager</Link>
        <Link className="chip" href="/">Guided journey →</Link>
      </header>
      <main className="dossier-home">
        <h1>Portfolio</h1>
        <p className="mut" style={{ maxWidth: "64ch" }}>
          Every product dossier in your organisation — module progress, filing
          gate and fee status at a glance.
        </p>
        {items.length > 0 && (
          <div className="affordance-bar">
            <button className="ghost" onClick={exportStatus}>
              Export client status report (CSV)
            </button>
          </div>
        )}

        {err && <div className="notice bad">{err}</div>}

        {loading ? (
          <div className="mut" style={{ marginTop: 20 }}>Loading portfolio…</div>
        ) : items.length === 0 ? (
          <div className="notice" style={{ marginTop: 16 }}>
            No dossiers yet.{" "}
            <Link href="/dossiers">Create one in the dossier manager →</Link>
          </div>
        ) : (
          <>
            <SummaryCards total={items.length} ready={ready} blocked={blocked} />
            <ul
              aria-label="Product dossiers"
              style={{
                listStyle: "none",
                margin: "20px 0 0",
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
                  />
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </>
  );
}

"use client";
// Right-to-Sell due dates for every marketable registration, straight from
// the registry service's /right-to-sell endpoint (statutory October 1).
import { useEffect, useState } from "react";
import {
  RTS_STATUSES,
  registryApi,
  type Registration,
  type RightToSell,
} from "./registryApi";
import { ProvenancePopover } from "@/components/ProvenancePopover";

export function DeadlinesStrip({ regs }: { regs: Registration[] }) {
  const [rts, setRts] = useState<Record<string, RightToSell>>({});
  const marketable = regs.filter((r) => RTS_STATUSES.includes(r.status));

  useEffect(() => {
    let alive = true;
    const asOf = new Date().toISOString().slice(0, 10);
    marketable.forEach(async (r) => {
      try {
        const o = await registryApi.rightToSell(r.id, asOf);
        if (alive) setRts((m) => ({ ...m, [r.id]: o }));
      } catch {
        /* row simply shows no deadline — service is the source of truth */
      }
    });
    return () => {
      alive = false;
    };
    // refetch when the set of marketable registrations changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketable.map((r) => `${r.id}:${r.status}`).join(",")]);

  if (marketable.length === 0) return null;

  return (
    <div className="card glass" style={{ marginTop: 16, padding: "14px 18px" }}>
      <h2 style={{ margin: "0 0 2px", fontSize: 15, fontWeight: 700 }}>
        Right-to-Sell deadlines
      </h2>
      <p className="mut" style={{ fontSize: 12, margin: "0 0 10px" }}>
        Annual Right-to-Sell fee per marketable DIN — due October 1 of the
        fiscal year. Amounts are billed by the fees service.
      </p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {marketable.map((r) => {
          const o = rts[r.id];
          if (!o) {
            return (
              <span key={r.id} className="chip mut">
                {r.product} · due …
              </span>
            );
          }
          if (!o.applies) {
            return (
              <span key={r.id} className="chip mut">
                {r.product} · {o.reason}
              </span>
            );
          }
          return (
            <span key={r.id}
              style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
              <span className={`chip ${o.overdue ? "blocked" : "ready"}`}>
                {r.product}
                {o.din ? ` (${o.din})` : ""} · due {o.due_date}
                {" · FY "}{o.fiscal_year}
                {o.overdue ? " · OVERDUE" : ""}
              </span>
              {/* WS3 provenance: the RTS due date is a fixed statutory anchor
                  (October 1 of the fiscal year) from the registry service — not
                  a computed running clock, so the anchor IS the due date. */}
              <ProvenancePopover
                prov={{
                  anchorLabel: `Right-to-Sell due (FY ${o.fiscal_year})`,
                  anchorDate: o.due_date,
                  anchorSource: "ingested",
                  basis: "calendar",
                  rule:
                    "The annual Right-to-Sell fee for a marketable DIN falls " +
                    "due on October 1 of the fiscal year; the registry service " +
                    "fixes this date per registration.",
                  citation:
                    "Food and Drug Regulations — annual Right-to-Sell / DIN " +
                    "notification (statutory October 1)",
                  asOf: null,
                }}
              />
            </span>
          );
        })}
      </div>
    </div>
  );
}

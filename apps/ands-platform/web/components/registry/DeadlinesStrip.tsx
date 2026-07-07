"use client";
// Right-to-Sell due dates for every marketable registration, straight from
// the registry service's /right-to-sell endpoint (statutory October 1).
import { useCallback, useEffect, useState } from "react";
import {
  RTS_STATUSES,
  registryApi,
  type Registration,
  type RightToSell,
} from "./registryApi";
import { ProvenancePopover } from "@/components/ProvenancePopover";
import { lifecycleApi, type VerifiedDate } from "../correspondence/api";
import { VerifiedDateControl } from "../correspondence/VerifiedDate";

export function DeadlinesStrip({ regs }: { regs: Registration[] }) {
  const [rts, setRts] = useState<Record<string, RightToSell>>({});
  const marketable = regs.filter((r) => RTS_STATUSES.includes(r.status));
  // Round-9 (n=4): verified-date overrides for the RTS clocks, one fetch per
  // distinct dossier (clock_key rts:{registration}:{fy} is globally unique).
  const [verified, setVerified] = useState<Record<string, VerifiedDate>>({});
  const dossierIds = Array.from(
    new Set(marketable.map((r) => r.dossier_id).filter(Boolean))).sort();
  const refreshVerified = useCallback(() => {
    dossierIds.forEach((d) =>
      lifecycleApi.listVerifiedDates(d)
        .then((res) => setVerified((m) => {
          const next = { ...m };
          res.verifications.forEach((v) => { next[v.clock_key] = v; });
          return next;
        }))
        .catch(() => {}));   // additive — chips render without verifications
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dossierIds.join(",")]);
  useEffect(() => { refreshVerified(); }, [refreshVerified]);

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
      <p className="mut" style={{ fontSize: 12, margin: "0 0 4px" }}>
        Annual Right-to-Sell fee per marketable DIN — due October 1 of the
        fiscal year. Amounts are billed by the fees service.
      </p>
      {/* Round-9 (operations BLOCKER, n=15): the statutory basis on the face
          of the strip, not only inside the per-chip popover — regulation,
          day-count convention, and the inputs the date derives from. */}
      <p className="mut" style={{ fontSize: 10.5, margin: "0 0 10px" }}>
        Basis: Food and Drug Regulations — annual Right-to-Sell / DIN
        notification · fixed calendar date (October 1 of the fiscal year, no
        day-counting) · inputs: registration status (post-NOC marketable) +
        today&apos;s date · calculated aid — verify against the HC record.
      </p>
      <div className="tile-strip">
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
              {/* round-9 (n=4): reconcile against the real RTS status */}
              {r.dossier_id && (
                <VerifiedDateControl
                  dossierId={r.dossier_id}
                  clockKey={`rts:${r.id}:${o.fiscal_year}`}
                  calculated={o.due_date}
                  latest={verified[`rts:${r.id}:${o.fiscal_year}`] || null}
                  onSaved={refreshVerified}
                />
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

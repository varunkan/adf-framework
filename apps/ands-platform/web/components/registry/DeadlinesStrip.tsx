"use client";
// Right-to-Sell fee due dates straight from the registry service's
// /right-to-sell endpoint — payable October 1, fixed by the Fees Order
// (SOR/2019-124 s. 52(3)).
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
        Annual Right-to-Sell fee per marketed DIN — payable October 1
        (SOR/2019-124 s. 52(3)). The fee is owed only if the DIN holder has
        sold the drug since DIN issuance (s. 52(2)); no fee applies while the
        product is dormant as of October 1 — i.e. Health Canada was notified
        under FDR C.01.014.71 of 12 consecutive months without sale, within
        the 12 months preceding October 1 (s. 52(4), until a C.01.014.72
        resumption notice). A post-NOC product never
        marketed, and a suspended/dormant DIN, owe no fee. Invoices issue on
        October 1 from the marketed status reported on the Annual Drug
        Notification; amounts are billed by the fees service.
      </p>
      {/* Round-9 (operations BLOCKER, n=15): the statutory basis on the face
          of the strip, not only inside the per-chip popover — regulation,
          day-count convention, and the inputs the date derives from. */}
      <p className="mut" style={{ fontSize: 10.5, margin: "0 0 10px" }}>
        Basis: Fees in Respect of Drugs and Medical Devices Order
        (SOR/2019-124), s. 52 — annual Right-to-Sell fee for a marketed DIN,
        payable October 1 (s. 52(3)) · fixed calendar date set by regulation
        (October 1, no day-counting) · inputs: registration status (marketed;
        sold since DIN issuance, not dormant) + today&apos;s date · calculated
        aid — verify against the HC record.
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
          // Health Canada issues invoices each October 1 (from the Annual
          // Drug Notification), payment due 30 days from issuance — inside
          // that window an unpaid fee is "unpaid/due", not OVERDUE. NOTE:
          // o.overdue is still date-derived by the registry service; the fees
          // service's payment state (right_to_sell_status: overdue =
          // outstanding AND past due) is the source of truth — the
          // service-side join is tracked against registry.py.
          const daysPastDue = Math.floor(
            (Date.now() - new Date(`${o.due_date}T00:00:00`).getTime()) /
              86400000);
          const inInvoiceWindow = o.overdue && daysPastDue <= 30;
          return (
            <span key={r.id}
              style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
              <span className={`chip ${o.overdue ? "blocked" : "ready"}`}>
                {r.product}
                {o.din ? ` (${o.din})` : ""} · due {o.due_date}
                {" · FY "}{o.fiscal_year}
                {o.overdue
                  ? inInvoiceWindow
                    ? " · unpaid — invoiced Oct 1, payment due 30 days from issuance"
                    : " · OVERDUE"
                  : ""}
              </span>
              {/* WS3 provenance: the RTS due date is a fixed regulatory anchor
                  — October 1, set by the Fees Order (SOR/2019-124 s. 52(3)) —
                  from the registry service, not a computed running clock, so
                  the anchor IS the due date. */}
              <ProvenancePopover
                prov={{
                  anchorLabel: `Right-to-Sell due (FY ${o.fiscal_year})`,
                  anchorDate: o.due_date,
                  anchorSource: "ingested",
                  basis: "calendar",
                  rule:
                    "The annual Right-to-Sell fee for a marketed DIN is " +
                    "payable on October 1 (SOR/2019-124 s. 52(3)), owed only " +
                    "if the drug has been sold since DIN issuance (s. 52(2)) " +
                    "and is not dormant as of October 1 (s. 52(4)); the " +
                    "registry service fixes this date per registration.",
                  citation:
                    "Fees in Respect of Drugs and Medical Devices Order " +
                    "(SOR/2019-124), s. 52 — annual Right-to-Sell fee, " +
                    "payable October 1 (s. 52(3))",
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

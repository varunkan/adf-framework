"use client";
// Correspondence hub + HC notice inbox + Form V / NOA register — the
// regulatory-affairs view of everything exchanged with Health Canada for
// one dossier, backed by the lifecycle service.
import { useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import type { DossierListItem } from "@/lib/dossierTypes";
import { Term } from "@/components/Term";
import { CorrespondenceHub } from "@/components/correspondence/CorrespondenceHub";
import { NoticeInbox } from "@/components/correspondence/NoticeInbox";
import { NoaRegister, StatutoryClockStrip } from "@/components/correspondence/NoaRegister";
// Round-9 (operations BLOCKER, n=4): tool dates vs verified official values.
import { ReconciliationView } from "@/components/correspondence/ReconciliationView";
// Round-9 (operations MAJOR, n=15): re-launchable 'Start here' guided tour.
import { StartHereTour } from "@/components/portfolio/StartHereTour";
// Round-9 (operations MAJOR, n=2): explicit FR-coverage statement.
import { BilingualNote } from "@/components/portfolio/BilingualNote";
import {
  SponsorScope,
  ALL_SPONSORS,
  matchesSponsor,
} from "@/components/SponsorScope";

export default function CorrespondencePage() {
  const [dossiers, setDossiers] = useState<DossierListItem[]>([]);
  const [dossierId, setDossierId] = useState("");
  const [picked, setPicked] = useState("");
  // WS-OPS-TENANT: per-client/sponsor scope is the FIRST control. Nothing is
  // pre-selected to a single dossier — the filer chooses the scope explicitly,
  // replacing the old "pre-fill to your first dossier" default.
  const [sponsor, setSponsor] = useState<string>(ALL_SPONSORS);
  // WS-OPS-TENANT (density): keep the litigation machinery (NOA / Form V
  // register) behind an opt-in "Advanced" expander so the correspondence view
  // isn't a wall of surfaces the moment a dossier opens.
  const [showNoa, setShowNoa] = useState(false);
  // bump to re-load the hub after a notice ingest auto-logs correspondence
  const [corrKey, setCorrKey] = useState(0);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { dossiers: items } = await dossierApi.listDossiers();
        if (!alive) return;
        setDossiers(items);
      } catch {
        // dossier service down — free-text entry still works
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // dossiers within the chosen sponsor scope — the picker only offers these,
  // so a filer can never reach across into another client's dossier by accident.
  const scoped = dossiers.filter((d) => matchesSponsor(d, sponsor));
  // if the current selection falls outside the new scope, drop it (don't leak
  // a previously-opened other-client dossier across a scope change).
  const pickedInScope = scoped.some((d) => d.dossier_id === picked);

  return (
    <>
      <TopNav subtitle="correspondence" />
      <main className="dossier-home">
        <header style={{ marginBottom: 8 }}>
          <div className="eyebrow">Operations</div>
          <h1>Correspondence &amp; notices</h1>
          <p className="lede">
            Log every exchange with Health Canada, ingest notices to drive the
            {" "}<Term k="DSTS" /> lifecycle, and watch the PM(NOC){" "}
            <Term k="litigation clock">statutory clocks</Term> on each{" "}
            <Term k="Form V" /> allegation (a <Term k="NOA" /> opens the{" "}
            <Term k="s.6" /> action window; an s.6 action starts the{" "}
            <Term k="24-month stay" />).
          </p>
          <p className="mut" style={{ maxWidth: "72ch" }}>
            Every change on this page is captured in the dossier’s append-only
            audit trail — actor and workspace stamped, sequence-numbered,
            exportable for inspections (open a dossier → Audit).
          </p>
          {/* Round-9 (operations MAJOR, n=2): FR coverage, stated plainly */}
          <BilingualNote />
        </header>

        {/* Round-9 (operations MAJOR, n=15): 'Start here' guided tour */}
        <StartHereTour page="correspondence" />

        <div className="notice" style={{ maxWidth: "72ch", marginTop: 4 }}>
          <b>Record only.</b> Everything on this page logs a record in your own
          workspace — it does <b>not</b> transmit anything to Health Canada.
          Ingesting a notice, serving an NOA or logging correspondence updates
          your tracking; filing with Health Canada happens only through the
          guided journey&apos;s transmit step (CESG).
        </div>

        {/* WS-OPS-TENANT: per-client/sponsor scope + isolation statement — the
            FIRST control, replacing the old auto-pick of dossier #1. */}
        <div style={{ marginTop: 20 }}>
        <SponsorScope
          items={dossiers}
          value={sponsor}
          onChange={(s) => {
            setSponsor(s);
            // reset the open dossier so we never leak the previous client's
            // dossier under a new sponsor scope; the filer re-picks explicitly.
            setPicked("");
            setDossierId("");
          }}
          count={scoped.length}
        />
        </div>

        <section className="card glass" style={{ padding: 18, maxWidth: 560, marginTop: 16 }}>
          <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>Open a dossier</h2>
          <label htmlFor="corr-dossier">Dossier</label>
          <div style={{ display: "flex", gap: 10 }}>
            <input
              id="corr-dossier"
              list="corr-dossier-options"
              value={dossierId}
              onChange={(e) => setDossierId(e.target.value)}
              placeholder="e123456"
            />
            <datalist id="corr-dossier-options">
              {scoped.map((d) => (
                <option key={d.dossier_id} value={d.dossier_id}>
                  {d.title}
                  {d.sponsor ? ` — ${d.sponsor}` : ""}
                </option>
              ))}
            </datalist>
            <button
              onClick={() => {
                const id = dossierId.trim();
                // only open dossiers inside the active sponsor scope
                if (scoped.some((d) => d.dossier_id === id)) setPicked(id);
              }}
              disabled={
                !dossierId.trim() ||
                dossierId.trim() === picked ||
                !scoped.some((d) => d.dossier_id === dossierId.trim())
              }
            >
              Open
            </button>
          </div>
          <p className="mut" style={{ margin: "6px 0 0", fontSize: 12 }}>
            {scoped.length} dossier{scoped.length === 1 ? "" : "s"} in the current
            scope. Only these are selectable.
          </p>
        </section>

        {!picked || !pickedInScope ? (
          <div className="notice" style={{ marginTop: 16 }}>
            Pick a dossier in the selected client / sponsor scope to see its
            correspondence, notices and NOA clocks.
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 18,
              marginTop: 18,
            }}
          >
            {/* Round-9 (n=6): live statutory clocks lead the page by default —
                never buried behind the Advanced expander. An at-risk clock
                (≤10 days) also auto-opens the register below. */}
            <StatutoryClockStrip
              dossierId={picked}
              onUrgent={() => setShowNoa(true)}
            />
            <NoticeInbox
              dossierId={picked}
              onIngested={() => setCorrKey((k) => k + 1)}
            />
            <CorrespondenceHub
              key={`${picked}:${corrKey}`}
              dossierId={picked}
              sponsor={scoped.find((d) => d.dossier_id === picked)?.sponsor}
            />

            {/* WS-OPS-TENANT (density / progressive disclosure): the Form V /
                NOA litigation register is advanced machinery most sessions
                don't need. Collapse it behind an opt-in toggle so the primary
                correspondence view stays scannable; nothing is removed. */}
            <div className="card glass" style={{ padding: 0 }}>
              <button
                className="ghost"
                aria-expanded={showNoa}
                onClick={() => setShowNoa((v) => !v)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "12px 18px",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span>{showNoa ? "▾" : "▸"}</span>
                Advanced — Form V / NOA litigation register
                <span className="mut" style={{ fontWeight: 400, fontSize: 12 }}>
                  PM(NOC) allegations &amp; statutory clocks
                </span>
              </button>
              {showNoa && (
                <div style={{ padding: "0 18px 18px" }}>
                  <NoaRegister dossierId={picked} />
                </div>
              )}
            </div>

            {/* Round-9 (operations BLOCKER, n=4): the reconciliation view —
                calculated tool dates vs the externally verified official
                values, discrepancies flagged, conflict rule stated. */}
            <ReconciliationView dossierId={picked} />
          </div>
        )}
      </main>
    </>
  );
}

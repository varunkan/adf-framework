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
import { NoaRegister } from "@/components/correspondence/NoaRegister";

export default function CorrespondencePage() {
  const [dossiers, setDossiers] = useState<DossierListItem[]>([]);
  const [dossierId, setDossierId] = useState("");
  const [picked, setPicked] = useState("");
  // bump to re-load the hub after a notice ingest auto-logs correspondence
  const [corrKey, setCorrKey] = useState(0);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { dossiers: items } = await dossierApi.listDossiers();
        if (!alive) return;
        setDossiers(items);
        if (items.length && !picked) {
          setDossierId(items[0].dossier_id);
          setPicked(items[0].dossier_id);
        }
      } catch {
        // dossier service down — free-text entry still works
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <TopNav subtitle="correspondence" />
      <main className="dossier-home">
        <h1>Correspondence &amp; notices</h1>
        <p className="mut" style={{ maxWidth: "70ch" }}>
          Log every exchange with Health Canada, ingest notices to drive the
          DSTS lifecycle, and watch the PM(NOC) statutory clocks on each{" "}
          <Term k="Form V" /> allegation (a <Term k="NOA" /> opens the{" "}
          <Term k="s.6" /> action window; an s.6 action starts the{" "}
          <Term k="24-month stay" />).
        </p>
        <p className="mut" style={{ fontSize: 12, maxWidth: "72ch" }}>
          Every change on this page is captured in the dossier’s append-only
          audit trail — actor and workspace stamped, sequence-numbered,
          exportable for inspections (open a dossier → Audit).
        </p>

        <div className="notice" style={{ maxWidth: "72ch" }}>
          <b>Record only.</b> Everything on this page logs a record in your own
          workspace — it does <b>not</b> transmit anything to Health Canada.
          Ingesting a notice, serving an NOA or logging correspondence updates
          your tracking; filing with Health Canada happens only through the
          guided journey&apos;s transmit step (CESG).
        </div>

        <div className="card glass" style={{ padding: 16, maxWidth: 560 }}>
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
              {dossiers.map((d) => (
                <option key={d.dossier_id} value={d.dossier_id}>
                  {d.title}
                </option>
              ))}
            </datalist>
            <button
              onClick={() => setPicked(dossierId.trim())}
              disabled={!dossierId.trim() || dossierId.trim() === picked}
            >
              Open
            </button>
          </div>
        </div>

        {!picked ? (
          <div className="notice" style={{ marginTop: 16 }}>
            Pick a dossier to see its correspondence, notices and NOA clocks.
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
            <NoticeInbox
              dossierId={picked}
              onIngested={() => setCorrKey((k) => k + 1)}
            />
            <CorrespondenceHub key={`${picked}:${corrKey}`} dossierId={picked} />
            <NoaRegister dossierId={picked} />
          </div>
        )}
      </main>
    </>
  );
}

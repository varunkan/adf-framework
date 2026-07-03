"use client";
// WS6 item 3: a readiness screen shown BEFORE journey Step 1. Two external
// prerequisites gate a real filing and have real lead times a PM must start
// early — the Health Canada 5-digit Company ID (enrolment by email, ~2 weeks)
// and the permanent Dossier ID (issued on a Dossier ID Request via REP). This
// screen does NOT block work: you can begin now and track either as an open
// risk (the existing placeholder-ID / CA-REP-0001 validation reminder), which
// stays visible until the real ID is set. Acknowledgement persists so a
// returning filer is not re-prompted.
import { useEffect, useState } from "react";
import { Term } from "./Term";

const KEY = "ands.prereqAck";

export function PrereqChecklist({ onBegin }: { onBegin: () => void }) {
  const [ack, setAck] = useState<boolean | null>(null); // null = still loading
  useEffect(() => {
    try { setAck(window.localStorage.getItem(KEY) === "1"); }
    catch { setAck(false); }
  }, []);

  // once acknowledged we render nothing — the normal Hero/journey shows through.
  if (ack === null || ack) return null;

  function begin() {
    try { window.localStorage.setItem(KEY, "1"); } catch { /* ignore */ }
    setAck(true);
    onBegin();
  }

  return (
    <div className="card glass" style={{ maxWidth: 720, margin: "24px auto", padding: 24 }}>
      <div className="eyebrow">Before you start · external prerequisites</div>
      <h2 style={{ marginTop: 4 }}>Two things Health Canada must issue you</h2>
      <p className="lede">
        Nothing on the guided journey waits on these — you can build your whole
        submission first. But both take real time to obtain, so request them
        now. Until each real ID is set, it stays on your dossier as a tracked{" "}
        <b>open risk</b> and the pre-filing validation reminds you.
      </p>

      <ol style={{ paddingLeft: 18, display: "flex", flexDirection: "column", gap: 14 }}>
        <li>
          <b>5-digit <Term k="Company ID" /></b>{" "}
          <span className="chip" style={{ fontSize: 11 }}>lead time ~2 weeks</span>
          <div className="mut" style={{ fontSize: 13, marginTop: 4 }}>
            Enrol by emailing your completed Company Template to the Office of
            Submission and Intellectual Property —{" "}
            <a href="mailto:hc.osip-bpip.sc@canada.ca">hc.osip-bpip.sc@canada.ca</a>.
            Typically issued within a couple of weeks. You need it before you can
            transmit, but not to start.
          </div>
        </li>
        <li>
          <b>Permanent <Term k="Dossier ID" /></b>{" "}
          <span className="chip" style={{ fontSize: 11 }}>issued on request via REP</span>
          <div className="mut" style={{ fontSize: 13, marginTop: 4 }}>
            File a Dossier ID Request through the{" "}
            <Term k="REP" /> (via your <Term k="CESG" /> account). Request it at
            most 8 weeks before you file. No ID yet? Begin with a placeholder ID
            and set the real one later — validation flags the placeholder as an
            open risk until you do.
          </div>
        </li>
      </ol>

      <div className="cta-row" style={{ marginTop: 16 }}>
        <button onClick={begin}>I understand — begin the journey →</button>
        <span className="nexthint">
          You can reopen this from Help at any time.
        </span>
      </div>
    </div>
  );
}

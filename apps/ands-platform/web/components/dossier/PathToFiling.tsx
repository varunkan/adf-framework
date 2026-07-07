"use client";
// ROUND9-VALIDATE item 8 (n=5, "the walkthrough tells me I must run an
// official tool but not how a first-timer actually obtains and runs it"):
// the 'Path to filing' CHECKLIST on the export success state — real,
// checkable steps (persisted per dossier in this browser), each explicitly
// marked "ANDS Studio" vs "External — you / consultant / publisher".
//
// HONESTY GUARDRAILS: Health Canada publishes the VALIDATION CRITERIA free at
// canada.ca ("Preparation of Regulatory Activities in eCTD Format"); the
// validator TOOLS themselves are commercial (Lorenz eValidator, docuBridge,
// GlobalSubmit — vendor license; cost varies by vendor and seat — we do NOT
// invent prices). CESG WebTrader requires CESG enrolment, typically handled
// by your publisher. This checklist EXTENDS the pinned eValidator banner; it
// never replaces or softens it.
import { useEffect, useState } from "react";
import { Term } from "../Term";

interface Step {
  id: string;
  title: string;
  owner: "ands" | "external";
  ownerLabel: string;
  body: React.ReactNode;
}

function steps(): Step[] {
  return [
    {
      id: "export",
      title: "Export the eCTD package",
      owner: "ands",
      ownerLabel: "ANDS Studio",
      body: (
        <>
          Download the transmissible sequence folder (index.xml,
          ca-regional.xml, every leaf at its href with checksums) — the export
          button above. Checked automatically when the export succeeds.
        </>
      ),
    },
    {
      id: "evalidator",
      title: "Obtain & run an eValidator on the exported package",
      owner: "external",
      ownerLabel: "External — you / consultant / publisher",
      body: (
        <>
          Health Canada publishes the eCTD validation <b>criteria</b> free at
          canada.ca (&ldquo;Preparation of Regulatory Activities in eCTD
          Format&rdquo;). The validator <b>tools</b> themselves are commercial
          — e.g. Lorenz eValidator, docuBridge, GlobalSubmit — licensed from
          the vendor; cost varies by vendor and seat count. To run one:
          <ol style={{ margin: "4px 0 0 16px", padding: 0 }}>
            <li>Point the validator at the exported sequence folder (unzip it first).</li>
            <li>Select the Health Canada / CA validation profile.</li>
            <li>Run it, and save the report file it produces.</li>
          </ol>
        </>
      ),
    },
    {
      id: "resolve",
      title: "Resolve any findings & re-export",
      owner: "external",
      ownerLabel: "ANDS Studio helps; judgement external",
      body: (
        <>
          Fix structural findings on the module pages here (each finding row
          links to its owning module), re-export, and re-run the eValidator.
          Judgement calls on eValidator findings stay with you / your
          consultant.
        </>
      ),
    },
    {
      id: "attach",
      title: "Attach the eValidator result + report file here",
      owner: "ands",
      ownerLabel: "ANDS Studio",
      body: (
        <>
          Record the pass/fail and attach the actual report file in the
          eValidator handoff below — it becomes downloadable, user-attested
          evidence against this dossier.
        </>
      ),
    },
    {
      id: "cesg",
      title: "Upload the validated package via CESG WebTrader",
      owner: "external",
      ownerLabel: "External — you / consultant / publisher",
      body: (
        <>
          Transmission goes through <Term k="CESG">CESG WebTrader</Term>, which
          requires CESG enrolment — typically handled by your publisher. ANDS
          Studio does not transmit anything to Health Canada.
        </>
      ),
    },
  ];
}

export function PathToFiling({
  dossierId,
  exported = false,
}: {
  dossierId: string;
  // step 1 auto-checks when the parent just completed a successful export
  exported?: boolean;
}) {
  const storageKey = `ands.pathToFiling.${dossierId}`;
  const [done, setDone] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      const saved = raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
      setDone(exported ? { ...saved, export: true } : saved);
    } catch {
      if (exported) setDone({ export: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, exported]);

  function toggle(id: string) {
    setDone((d) => {
      const next = { ...d, [id]: !d[id] };
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {}
      return next;
    });
  }

  const all = steps();
  const doneCount = all.filter((s) => done[s.id]).length;

  return (
    <div className="card glass" style={{ marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Path to filing</h3>
        <span className="mut" style={{ marginLeft: "auto", fontSize: 12 }}>
          {doneCount} / {all.length} steps checked
        </span>
      </div>
      <div className="mut" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>
        The concrete steps between this export and a Health Canada
        transmission — each marked with who does it. Checkmarks are your own
        working notes (saved in this browser, per dossier); they assert
        nothing to Health Canada.
      </div>
      <ol style={{ margin: "10px 0 0", padding: 0, listStyle: "none" }}>
        {all.map((s, i) => (
          <li
            key={s.id}
            style={{
              marginTop: i === 0 ? 0 : 8,
              paddingTop: i === 0 ? 0 : 8,
              borderTop: i === 0 ? "none" : "1px solid var(--line)",
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <input
              type="checkbox"
              id={`ptf-${dossierId}-${s.id}`}
              checked={!!done[s.id]}
              onChange={() => toggle(s.id)}
              style={{ marginTop: 3 }}
            />
            <div style={{ fontSize: 12.5 }}>
              <label
                htmlFor={`ptf-${dossierId}-${s.id}`}
                style={{ fontWeight: 600, cursor: "pointer" }}
              >
                {i + 1}. {s.title}
              </label>{" "}
              <span
                className={`chip ${s.owner === "ands" ? "" : "blocked"}`}
                style={{ fontSize: 9, padding: "0 6px", verticalAlign: "middle" }}
                title={
                  s.owner === "ands"
                    ? "This step happens inside ANDS Studio"
                    : "This step happens OUTSIDE ANDS Studio — you, your consultant or your publisher"
                }
              >
                {s.ownerLabel}
              </span>
              <div className="mut" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.55 }}>
                {s.body}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

"use client";
// onboarding — portfolio preview panel (n=2). Round-9 item 12 (MAJOR): "this
// whole onboarding is about accounts and security with zero visibility hooks."
// A compact, clearly-labelled ILLUSTRATIVE cross-dossier preview showing what
// the post-sign-in Portfolio surface looks like — dossier / status / next
// deadline / assignee / blockers. HONESTY GUARDRAIL: the rows are sample data
// and the label says so; no live-data capability is claimed on a screen where
// the user is not signed in. (The 'What you'll do here' primer itself lives in
// TopNav — another flow's surface — so this panel ships on the onboarding
// screen this flow owns.)

const SAMPLE_ROWS: Array<{
  dossier: string; status: string; deadline: string; assignee: string;
  blockers: string;
}> = [
  { dossier: "Metformin ANDS", status: "Screening", deadline: "SDN response — 12 days",
    assignee: "R. Tremblay", blockers: "1 open" },
  { dossier: "Atorvastatin ANDS", status: "Building 0001", deadline: "Sequence target — 4 wks",
    assignee: "M. Chen", blockers: "None" },
  { dossier: "Lisinopril ANDS", status: "Validated ✓", deadline: "Awaiting NOC",
    assignee: "R. Tremblay", blockers: "None" },
];

export function PortfolioPreview() {
  return (
    <div className="card glass" style={{ padding: "16px 18px", marginTop: 14,
      maxWidth: 520 }}>
      <div style={{ fontSize: 13 }}>
        <b>After sign-in: your portfolio at a glance</b>
      </div>
      <p className="mut" style={{ margin: "6px 0 8px", fontSize: 12 }}>
        Illustrative preview — after sign-in, Portfolio shows your{" "}
        <b>real</b> dossiers with live status, deadlines, assignees and
        blockers.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%",
          fontSize: 12 }}>
          <thead>
            <tr>
              {["Dossier", "Status", "Next deadline", "Assignee", "Blockers"]
                .map((h) => (
                <th key={h} className="mut" style={{ textAlign: "left",
                  padding: "4px 8px 4px 0", fontWeight: 500,
                  borderBottom: "1px solid var(--line)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SAMPLE_ROWS.map((r) => (
              <tr key={r.dossier}>
                <td style={{ padding: "5px 8px 5px 0" }}>{r.dossier}</td>
                <td style={{ padding: "5px 8px 5px 0" }}>
                  <span className="chip" style={{ fontSize: 11 }}>{r.status}</span>
                </td>
                <td style={{ padding: "5px 8px 5px 0" }}>{r.deadline}</td>
                <td style={{ padding: "5px 8px 5px 0" }}>{r.assignee}</td>
                <td style={{ padding: "5px 8px 5px 0" }}>{r.blockers}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mut" style={{ margin: "8px 0 0", fontSize: 11 }}>
        Sample rows for illustration only — not live data.
      </p>
    </div>
  );
}

"use client";
// Portfolio roll-up: totals across the dossiers in the active client/sponsor
// scope. WS-OPS-TENANT: an optional scope label makes it legible WHOSE totals
// these are, so a CRO/CDMO PM can never mistake one client's roll-up for the
// whole workspace.

export function SummaryCards({
  total,
  ready,
  blocked,
  scopeLabel,
}: {
  total: number;
  ready: number;
  blocked: number;
  // when set (a specific sponsor is scoped), shown above the cards so the
  // totals are unambiguously attributed to one client.
  scopeLabel?: string;
}) {
  const cards: { label: string; value: number; color?: string }[] = [
    { label: "Dossiers", value: total },
    { label: "Ready to file", value: ready, color: "var(--ok)" },
    { label: "Blocked", value: blocked, color: "var(--warn)" },
  ];
  return (
    <div style={{ marginTop: 20 }}>
      {scopeLabel && (
        <div
          className="mut"
          style={{ fontSize: 12, marginBottom: 8 }}
          aria-label="Roll-up scope"
        >
          Roll-up for <b>{scopeLabel}</b> — this client / sponsor only.
        </div>
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))",
          gap: 16,
        }}
      >
        {cards.map((c) => (
          <div key={c.label} className="card glass" style={{ padding: 18 }}>
            <div style={{ fontSize: 28, fontWeight: 800, color: c.color }}>
              {c.value}
            </div>
            <div
              className="mut"
              style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".08em" }}
            >
              {c.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

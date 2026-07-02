"use client";
// Portfolio roll-up: totals across every dossier in the tenant.

export function SummaryCards({
  total,
  ready,
  blocked,
}: {
  total: number;
  ready: number;
  blocked: number;
}) {
  const cards: { label: string; value: number; color?: string }[] = [
    { label: "Dossiers", value: total },
    { label: "Ready to file", value: ready, color: "var(--ok)" },
    { label: "Blocked", value: blocked, color: "var(--warn)" },
  ];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))",
        gap: 16,
        marginTop: 20,
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
  );
}

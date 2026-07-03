// WS6 portfolio deadlines — pure date math shared by the row column and the
// portfolio-wide rollup. The soonest_due value is an ISO YYYY-MM-DD derived
// server-side from a dossier's content-plan items (see DossierService).

export type DueMeta = {
  iso: string;
  days: number; // whole days from today (negative = overdue)
  overdue: boolean;
  soon: boolean; // due within the next 30 days (and not overdue)
  label: string; // human-friendly relative label
};

// midnight-anchored day delta so "today" is 0 regardless of the current time.
export function daysUntil(iso: string, now: Date = new Date()): number {
  const [y, m, d] = iso.split("-").map(Number);
  const due = Date.UTC(y, (m || 1) - 1, d || 1);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((due - today) / 86400000);
}

export function dueMeta(iso?: string | null, now: Date = new Date()): DueMeta | null {
  if (!iso) return null;
  const days = daysUntil(iso, now);
  const overdue = days < 0;
  const label = overdue
    ? `${-days}d overdue`
    : days === 0
      ? "due today"
      : `in ${days}d`;
  return { iso, days, overdue, soon: !overdue && days <= 30, label };
}

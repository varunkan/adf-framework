"use client";
// Round-9 catalog MAJOR — "'Soonest due' dates have no defined source or
// regulatory clock" (n=8). Every catalog due date is rendered WITH its named
// clock (source + the plan item driving it) and is enterable/editable in
// place: editing updates the DRIVING content-plan item (the stored truth),
// never a free date field. Overdue/soon flags are computed against that named
// clock.
//
// HONEST: the catalog's soonest-due is always a CLIENT-SET TARGET carried on
// a content-plan item. HC statutory clocks (45-day screening window, NOA
// clocks) come from real HC notices and live on the Portfolio/Correspondence
// rows — the catalog never fabricates a regulatory clock it does not hold.
import { useState } from "react";
import { dueMeta } from "@/lib/deadline";
import { toast } from "sonner";
import { catalogApi, type CatalogListItem, type SoonestDueMeta } from "./catalogApi";

// Set/edit the target date behind a row's named clock. When the dossier has
// no content plan yet, one is created (the plan is the deadline's storage —
// same items the Journey/collaboration surfaces read).
async function saveDue(d: CatalogListItem, iso: string): Promise<void> {
  const meta = d.soonest_due_meta;
  if (meta?.item_id) {
    // edit the DRIVING item; preserve its assignee (assign patches both)
    await catalogApi.assignItem(meta.item_id, meta.assignee || "", iso);
    return;
  }
  // no dated item yet — reuse the existing plan's first item, or create the
  // plan only when none exists (getPlan → null on 404; other failures throw
  // so a transient error never silently spawns a duplicate plan). The created
  // plan is exactly what the Journey surface would create for this dossier.
  const existing = await catalogApi.getPlan(d.dossier_id);
  const items = existing
    ? existing.plan.items
    : (await catalogApi.createPlan(
        d.dossier_id, d.submission_type || "ANDS", !!d.cs_be_only)).plan.items;
  const first = items.find((i) => i.status !== "complete") || items[0];
  if (!first) throw new Error("this dossier's content plan has no items");
  await catalogApi.assignItem(first.id, first.assignee || "", iso);
}

// The one-line clock provenance under a due date: named clock + driving item.
export function clockLabel(meta: SoonestDueMeta): string {
  return `${meta.clock_type} · ${meta.item_title}`;
}

export function DueClockCell({
  d,
  onSaved,
  compact,
}: {
  d: CatalogListItem;
  onSaved: () => Promise<void> | void;
  // compact = grid-tile rendering (chip-sized); default = list-cell rendering
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(d.soonest_due || "");
  const [busy, setBusy] = useState(false);
  const meta = d.soonest_due_meta || null;
  const dm = dueMeta(d.soonest_due);

  async function save() {
    if (!value) { setEditing(false); return; }
    setBusy(true);
    try {
      await saveDue(d, value);
      toast.success(`${d.dossier_id} — target date set (client-set target)`);
      setEditing(false);
      await onSaved();
    } catch (e) {
      toast.error(String((e as Error)?.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
        <input type="date" value={value} disabled={busy}
          onChange={(e) => setValue(e.target.value)}
          aria-label={`Target date for ${d.dossier_id}`}
          style={{ fontSize: 12, padding: "2px 6px", width: "auto" }} />
        <button className="ghost" style={{ fontSize: 11, padding: "2px 6px" }}
          disabled={busy} onClick={save}>{busy ? "…" : "Save"}</button>
        <button className="ghost" style={{ fontSize: 11, padding: "2px 6px" }}
          disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
      </span>
    );
  }

  const title = meta
    ? `${meta.clock_type} — driven by plan item "${meta.item_title}"` +
      (meta.assignee ? ` (assignee ${meta.assignee})` : "") +
      ` · due ${meta.date}. Not an HC statutory clock — HC clocks appear on ` +
      "Portfolio/Correspondence from real HC notices. Click ✎ to edit."
    : "No target date yet — set a client-set target (stored on this " +
      "dossier's content plan). HC statutory clocks are never invented here.";

  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "baseline",
      flexWrap: "wrap" }}
      // inside a grid tile the whole card is a Link — a click on the clock
      // must neither navigate (preventDefault) nor bubble to the row handler
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
      {dm ? (
        <span className={dm.overdue ? "bad-text" : dm.soon ? "warn-text" : "mut"}
          title={title}>
          {dm.label}
          {meta && (
            <span className="mut" style={{ fontSize: 11, display: "block" }}>
              {compact ? meta.clock_type : clockLabel(meta)}
            </span>
          )}
        </span>
      ) : (
        <span className="mut" title={title} style={{ fontSize: 12 }}>
          no target set
        </span>
      )}
      <button className="ghost" title={title}
        aria-label={`Set or edit target date for ${d.dossier_id}`}
        style={{ fontSize: 11, padding: "0 4px" }}
        onClick={(e) => { e.preventDefault(); setValue(d.soonest_due || "");
          setEditing(true); }}>
        ✎
      </button>
    </span>
  );
}

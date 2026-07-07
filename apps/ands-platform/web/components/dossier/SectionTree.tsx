"use client";
import { useEffect, useRef } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Sparkles } from "lucide-react";
import type { ModuleView, SectionNode } from "@/lib/dossierTypes";
import {
  LEAF_STATUS,
  effectiveLeafStatus,
  applicabilityHelp,
  opMeta,
  MODULE_NAME,
  type LeafState,
} from "@/lib/leafStatus";

// Plain-language help for the lifecycle operation chip — makes explicit whether
// the operation acts against a prior active (transmitted) sequence.
function opHelp(op?: string): string {
  switch (op) {
    case "replace":
      return "Replaces an earlier document already transmitted in an active sequence — it supersedes the old leaf in the official record.";
    case "append":
      return "Adds alongside a document in a prior active sequence — both remain part of the record.";
    case "delete":
      return "Withdraws a document from a prior active sequence — kept in history, removed from the current view.";
    default:
      return "Filed new — there is no prior active sequence this leaf supersedes.";
  }
}

// A small inline status icon + Radix tooltip, reused for the legend and every
// leaf row so the icon/word/colour vocabulary is identical everywhere.
function StatusIcon({
  state,
  label,
  extra,
}: {
  state: LeafState;
  label: string;
  extra?: string;
}) {
  const meta = LEAF_STATUS[state];
  const Icon = meta.icon;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <span
          className={`t-glyph ${state}`}
          role="img"
          aria-label={label}
          tabIndex={-1}
        >
          <Icon size={15} strokeWidth={2.25} aria-hidden />
        </span>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tt" sideOffset={6}>
          <b>{meta.word}</b>
          <div className="tt-sub">{meta.help}</div>
          {extra ? <div className="tt-sub">{extra}</div> : null}
          <Tooltip.Arrow className="tt-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export function SectionTree({
  module,
  selected,
  onSelect,
  opByLeaf = {},
}: {
  module: ModuleView;
  selected: string;
  onSelect: (s: string) => void;
  // leaf_id → live/pending eCTD lifecycle operator (from GET current-view)
  opByLeaf?: Record<string, string>;
}) {
  const visible = module.nodes.filter(
    (n) => n.applicability !== "suppressed" && n.applicability !== "na"
  );
  const suppressed = module.nodes.filter((n) => n.applicability === "suppressed");
  const markedNa = module.nodes.filter((n) => n.applicability === "na");

  // Roving-tabindex support: the ordered list of selectable leaf sections.
  const leafOrder = visible.filter((n) => n.kind === "document").map((n) => n.section);
  const listRef = useRef<HTMLUListElement>(null);

  function moveFocus(section: string) {
    onSelect(section);
    // focus the row once React has painted the new tabIndex
    requestAnimationFrame(() => {
      const el = listRef.current?.querySelector<HTMLElement>(
        `[data-section="${CSS.escape(section)}"]`
      );
      el?.focus();
    });
  }

  function onTreeKeyDown(e: React.KeyboardEvent, current: string) {
    const i = leafOrder.indexOf(current);
    if (i < 0) return;
    let next = -1;
    if (e.key === "ArrowDown") next = Math.min(leafOrder.length - 1, i + 1);
    else if (e.key === "ArrowUp") next = Math.max(0, i - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = leafOrder.length - 1;
    if (next >= 0) {
      e.preventDefault();
      moveFocus(leafOrder[next]);
    }
  }

  // roving anchor: the selected leaf, else the first selectable leaf
  const anchor = leafOrder.includes(selected) ? selected : leafOrder[0];

  const prog = module.progress;
  const modName = MODULE_NAME[module.module] || module.title;

  return (
    <nav className="section-tree glass" aria-label={`Module ${module.module} sections`}>
      {/* P1-6 — the tree owns its own module completeness header */}
      <header className="tree-head">
        <div className="tree-head-top">
          <span className="tree-mod">M{module.module}</span>
          <span className="tree-mod-name">{modName}</span>
        </div>
        <div
          className="progress"
          aria-hidden
          title={`${prog.required_filled} of ${prog.required_total} required sections placed`}
        >
          <i style={{ width: `${prog.percent}%` }} />
        </div>
        <div className="tree-head-count mut">
          {prog.required_filled}/{prog.required_total} required placed
        </div>
      </header>

      {/* Round-9 builder_forms MAJOR "Workspace density overload" (n=22),
          remaining ask "keep the status-key legend persistently visible": the
          key is a compact ALWAYS-ON strip again (P2-3 had demoted it to a
          hover-only button, which hid the vocabulary the panel asked to keep).
          One quiet line — icon + word, hover for the full meaning — so the
          density win is not undone. */}
      <div
        className="mut"
        role="list"
        aria-label="Status key — what each icon means"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "3px 10px",
          alignItems: "center",
          margin: "6px 0 2px",
          fontSize: 11,
        }}
      >
        {(["empty", "partial", "complete", "review", "na"] as LeafState[]).map(
          (s) => {
            const m = LEAF_STATUS[s];
            const Icon = m.icon;
            return (
              <span
                key={s}
                role="listitem"
                title={m.help}
                style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
              >
                <span className={`t-glyph ${s}`} aria-hidden>
                  <Icon size={12} aria-hidden />
                </span>
                {m.word}
              </span>
            );
          }
        )}
      </div>

      <ul role="tree" aria-orientation="vertical" ref={listRef}>
        {visible.map((n) =>
          n.kind === "group" ? (
            <li key={n.id} role="none" className={`tree-group d${n.depth}`}>
              {n.section} · {n.title}
            </li>
          ) : (
            <TreeItem
              key={n.id}
              n={n}
              selected={selected === n.section}
              roving={n.section === anchor}
              op={opByLeaf[n.leaf_id]}
              onSelect={onSelect}
              onKeyNav={onTreeKeyDown}
            />
          )
        )}
      </ul>

      {/* P2-1 — split the hidden bucket: "not in this model" vs "marked N/A" */}
      {suppressed.length > 0 && (
        <details className="tree-hidden">
          <summary>Not in this submission model ({suppressed.length})</summary>
          <ul>
            {suppressed.map((n) => (
              <NaRow key={n.id} n={n} onSelect={onSelect} />
            ))}
          </ul>
        </details>
      )}
      {markedNa.length > 0 && (
        <details className="tree-hidden" open>
          <summary>Marked N/A by you ({markedNa.length})</summary>
          <ul>
            {markedNa.map((n) => (
              <NaRow key={n.id} n={n} onSelect={onSelect} reason={n.na_reason} />
            ))}
          </ul>
        </details>
      )}
    </nav>
  );
}

function NaRow({
  n,
  onSelect,
  reason,
}: {
  n: SectionNode;
  onSelect: (s: string) => void;
  reason?: string | null;
}) {
  const meta = LEAF_STATUS.na;
  const Icon = meta.icon;
  return (
    <li className="tree-na">
      <button type="button" className="tree-na-btn" onClick={() => onSelect(n.section)}>
        <Tooltip.Root>
          <Tooltip.Trigger asChild>
            <span className="t-glyph na" aria-hidden>
              <Icon size={14} aria-hidden />
            </span>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content className="tt" sideOffset={6}>
              <b>N/A</b>
              <div className="tt-sub">{reason ? reason : meta.help}</div>
              <Tooltip.Arrow className="tt-arrow" />
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
        <span className="t-sec">{n.section}</span>
        <span className="t-title">{n.title}</span>
      </button>
      {reason ? <div className="tree-na-reason mut">{reason}</div> : null}
    </li>
  );
}

function TreeItem({
  n,
  selected,
  roving,
  op,
  onSelect,
  onKeyNav,
}: {
  n: SectionNode;
  selected: boolean;
  roving: boolean;
  op?: string;
  onSelect: (s: string) => void;
  onKeyNav: (e: React.KeyboardEvent, section: string) => void;
}) {
  const state = effectiveLeafStatus(n);
  const meta = LEAF_STATUS[state];
  const om = opMeta(op);
  const applic = n.applicability === "required" ? "Required" : "Optional";

  return (
    <li
      role="treeitem"
      aria-selected={selected}
      aria-label={`${n.section} ${n.title} — ${applic}, ${meta.word}${om ? `, ${om.word}` : ""}`}
      tabIndex={roving ? 0 : -1}
      data-section={n.section}
      className={`tree-item d${n.depth} s-${state} ${selected ? "sel" : ""}`}
      onClick={() => onSelect(n.section)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(n.section);
        } else {
          onKeyNav(e, n.section);
        }
      }}
    >
      <StatusIcon
        state={state}
        label={`${n.title}: ${meta.word}`}
        extra={applicabilityHelp(n.applicability)}
      />
      <div className="t-body">
        <div className="t-line1">
          <span className="t-title">{n.title}</span>
          <span className="t-sec">{n.section}</span>
        </div>
        <div className="t-line2 mut">
          {applic}
          {om ? (
            <>
              {" · "}
              {/* MAJOR: make the lifecycle operation legible per leaf — the
                  chip is the same NEW/REPL/APP/DEL vocabulary as everywhere,
                  and the tooltip spells out whether it acts on a prior active
                  sequence (replace/append/delete) or is filed new. */}
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <span
                    className={om.risk ? "t-op warn" : "t-op"}
                    role="img"
                    aria-label={`Lifecycle operation: ${om.word}`}
                    tabIndex={-1}
                  >
                    {om.label}
                  </span>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content className="tt" sideOffset={6}>
                    <b>{om.word}</b>
                    <div className="tt-sub">{opHelp(op)}</div>
                    <Tooltip.Arrow className="tt-arrow" />
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            </>
          ) : null}
          {" · "}
          {meta.word}
        </div>
      </div>
      {n.ai_draftable && (
        <Tooltip.Root>
          <Tooltip.Trigger asChild>
            <span
              className="t-ai"
              role="img"
              aria-label="AI drafting available"
              tabIndex={-1}
            >
              <Sparkles size={12} aria-hidden />
            </span>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content className="tt" sideOffset={6}>
              <b>AI drafting available</b>
              <div className="tt-sub">
                This section supports interactive AI drafting — you review and
                confirm it as your own content before anything is filed.
              </div>
              <Tooltip.Arrow className="tt-arrow" />
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
      )}
    </li>
  );
}

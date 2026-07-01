"use client";
import type { ModuleView, SectionNode } from "@/lib/dossierTypes";

const GLYPH: Record<string, string> = {
  empty: "○", partial: "◐", complete: "✓", na: "⊘",
};
const WORD: Record<string, string> = {
  empty: "to do", partial: "partly done", complete: "done", na: "not applicable",
};

export function SectionTree({
  module,
  selected,
  onSelect,
}: {
  module: ModuleView;
  selected: string;
  onSelect: (s: string) => void;
}) {
  const visible = module.nodes.filter(
    (n) => n.applicability !== "suppressed" && n.applicability !== "na"
  );
  const hidden = module.nodes.filter(
    (n) => n.applicability === "suppressed" || n.applicability === "na"
  );
  return (
    <nav className="section-tree" aria-label={`Module ${module.module} sections`}>
      <h2>{module.title}</h2>
      <ul role="tree">
        {visible.map((n) =>
          n.kind === "group" ? (
            <li key={n.id} role="none" className={`tree-group d${n.depth}`}>
              {n.section} · {n.title}
            </li>
          ) : (
            <TreeItem key={n.id} n={n} selected={selected === n.section}
              onSelect={onSelect} />
          )
        )}
      </ul>
      {hidden.length > 0 && (
        <details className="tree-hidden">
          <summary>Not required for this generic ({hidden.length})</summary>
          <ul>
            {hidden.map((n) => (
              <li key={n.id} className="tree-na">
                <span aria-hidden>⊘ </span>
                {n.section} {n.title}
              </li>
            ))}
          </ul>
        </details>
      )}
    </nav>
  );
}

function TreeItem({
  n,
  selected,
  onSelect,
}: {
  n: SectionNode;
  selected: boolean;
  onSelect: (s: string) => void;
}) {
  return (
    <li
      role="treeitem"
      aria-selected={selected}
      tabIndex={0}
      className={`tree-item d${n.depth} ${selected ? "sel" : ""}`}
      onClick={() => onSelect(n.section)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(n.section);
        }
      }}
    >
      <span className={`t-glyph ${n.status}`} aria-hidden>
        {GLYPH[n.status] ?? "○"}
      </span>
      <span className="t-sec">{n.section}</span>
      <span className="t-title">{n.title}</span>
      <span className={`t-badge ${n.applicability}`}>
        {n.applicability === "required" ? "req" : "opt"}
      </span>
      <span className="sr-only">
        {n.title}: {WORD[n.status] ?? "to do"}
      </span>
    </li>
  );
}

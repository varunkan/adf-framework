"use client";
import Link from "next/link";
import { UserChip } from "@/components/UserChip";
import { useParams } from "next/navigation";
import { useDossier } from "./DossierContext";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { MODULE_NAME, type ModuleTabState } from "@/lib/leafStatus";

const MODULES = ["1", "2", "3", "4", "5"];

const TAB_STATE_WORD: Record<ModuleTabState, string> = {
  complete: "complete",
  review: "review required",
  partial: "in progress",
  todo: "not started",
  na: "not required for this submission",
};

export function DossierHeader() {
  const { dossierId, index, content } = useDossier();
  const params = useParams();
  const active = String((params as any)?.module || "");
  const towerByMod = Object.fromEntries((content?.tower || []).map((t) => [t.module, t]));
  // per-module "holds an unconfirmed sample/AI draft" signal, from the live tree
  const reviewByMod = Object.fromEntries(
    (content?.modules || []).map((m) => [
      m.module,
      m.nodes.some((n) => n.needs_review),
    ])
  );

  return (
    <header className="topbar">
      <span className="brand">
        <span className="dot" aria-hidden />
        <Link href="/dossiers" style={{ color: "inherit" }}>ANDS&nbsp;Studio</Link>
        <small>· {index?.title || dossierId}</small>
      </span>
      <nav className="module-tabs" aria-label="eCTD modules">
        {MODULES.map((m) => {
          const t = towerByMod[m];
          const filled = t?.required_filled ?? 0;
          const total = t?.required_total ?? 0;
          const hasReview = !!reviewByMod[m];
          // roll the tower state into the shared tab vocabulary
          let state: ModuleTabState;
          if ((t?.state || "todo") === "na") state = "na";
          else if (hasReview) state = "review";
          else if (t?.state === "pass" && filled === total && total > 0) state = "complete";
          else if (filled > 0) state = "partial";
          else state = "todo";

          const pct = total > 0 ? Math.round((filled / total) * 100) : 0;
          const modName = MODULE_NAME[m] || `Module ${m}`;
          const fraction = state === "na" ? "N/A" : total > 0 ? `${filled}/${total}` : "";
          const aria =
            `Module ${m} (${modName})` +
            (state === "na"
              ? " — not required for this submission"
              : `, ${filled} of ${total} required sections complete, ${TAB_STATE_WORD[state]}`);

          return (
            <Link key={m}
              href={`/dossiers/${encodeURIComponent(dossierId)}/m/${m}`}
              className={`mtab ${state} ${active === m ? "active" : ""}`}
              aria-current={active === m ? "page" : undefined}
              aria-label={aria}
              title={aria}>
              <span className={`mtab-icon ${state}`} aria-hidden>
                {state === "complete" ? (
                  <CheckCircle2 size={14} />
                ) : state === "review" ? (
                  <AlertTriangle size={14} />
                ) : state === "na" ? (
                  "—"
                ) : (
                  <span className="mtab-dot" />
                )}
              </span>
              <span className="mtab-label">M{m}</span>
              {fraction && <span className="mtab-frac">{fraction}</span>}
              {/* per-module completeness underline */}
              {state !== "na" && (
                <span className="mtab-bar" aria-hidden>
                  <i style={{ width: `${pct}%` }} />
                </span>
              )}
            </Link>
          );
        })}
      </nav>
      <span className="spacer" />
      <UserChip />
      <Link className="chip" href={`/dossiers/${encodeURIComponent(dossierId)}/viewer`}>
        Application Viewer
      </Link>
      <Link className="chip" href={`/dossiers/${encodeURIComponent(dossierId)}/audit`}>Audit</Link>
      <Link className="chip" href="/portfolio">Portfolio</Link>
      <Link className="chip" href="/">Journey</Link>
    </header>
  );
}

"use client";
import Link from "next/link";
import { useState } from "react";
import { UserChip } from "@/components/UserChip";
import { useParams, useRouter } from "next/navigation";
import { useDossier } from "./DossierContext";
import { SetRealDossierIdModal } from "./SetRealDossierIdModal";
import {
  CheckCircle2,
  AlertTriangle,
  ShieldX,
  PenLine,
  KeyRound,
} from "lucide-react";
import { MODULE_NAME, type ModuleTabState } from "@/lib/leafStatus";
import type { SignatureReadiness } from "@/lib/dossierTypes";

const MODULES = ["1", "2", "3", "4", "5"];

// POLISH-ID-BEFORE-409: a PERSISTENT, ambient strip under the workspace chrome
// that fires the MOMENT a placeholder-ID (d…) dossier is opened — up front, in
// the builder, so setting the real Health Canada Dossier ID is a deliberate
// first step and the export 409 becomes a CONFIRMATION, not a surprise. Every
// dossier page mounts this header, so the prompt is unavoidable, not something
// the filer only discovers at the export wall. Reuses the shared set-real-ID +
// REP-request flow (SetRealDossierIdModal).
//
// Honest: the in-app REP Dossier-ID Request records the request intent — it
// does NOT transmit to Health Canada; export stays blocked until a real ID is
// set AND validation passes.
function PlaceholderIdBanner({ dossierId }: { dossierId: string }) {
  const router = useRouter();
  const params = useParams();
  const { index, refresh } = useDossier();
  const [open, setOpen] = useState(false);
  // only for placeholder (draft) IDs — a real HC Dossier ID never starts with 'd'
  if (!dossierId.startsWith("d")) return null;
  const active = String((params as any)?.module || "1");
  return (
    <>
      <div className="placeholder-id-banner notice warn" role="status">
        <KeyRound size={16} aria-hidden className="pib-icon" />
        <span className="pib-body">
          <strong>
            This dossier uses a placeholder ID ({dossierId}).
          </strong>{" "}
          Set the real Health Canada Dossier ID (issued via REP) before
          validation / export — export stays blocked until you do.
        </span>
        <button className="chip pib-cta" onClick={() => setOpen(true)}>
          <PenLine size={13} aria-hidden />
          Set real Dossier ID
        </button>
      </div>
      {open && (
        <SetRealDossierIdModal
          dossierId={dossierId}
          seedCompany={index?.company_id || ""}
          seedSponsor={index?.sponsor || ""}
          onClose={() => setOpen(false)}
          onRenamed={async (newId) => {
            setOpen(false);
            // the id changed — route to the same module under the new id, then
            // let the fresh page mount re-fetch. refresh() keeps this tab honest
            // if the router push is a no-op.
            await refresh();
            router.push(
              `/dossiers/${encodeURIComponent(newId)}/m/${encodeURIComponent(active)}`
            );
          }}
        />
      )}
    </>
  );
}

// POLISH-SIGN-BANNER: a PERSISTENT, ambient strip under the workspace chrome
// that fires the MOMENT the current package stops being cleanly signed — a leaf
// changed after signing, or a conflicted (author-signs) sign occurred. It is
// loud and always-visible (every dossier page mounts this header), not a status
// field the reviewer has to go read. It clears when the signature verifies.
//
// Honest: this is a role-separation + tamper-evidence signal (Part-11 aligned),
// NOT a Health Canada acceptance claim.
function SignatureReSignBanner({
  sr,
  dossierId,
}: {
  sr: SignatureReadiness | undefined;
  dossierId: string;
}) {
  // only fire for a REAL signature gone stale/conflicted — never for the
  // normal "not signed yet" pre-sign state.
  if (!sr?.needs_resign) return null;
  const label =
    sr.status === "sod_conflict"
      ? "Segregation-of-duties conflict"
      : "Package changed after signing";
  return (
    <div className="sign-resign-banner notice bad" role="alert">
      <ShieldX size={16} aria-hidden className="srb-icon" />
      <span className="srb-body">
        <strong>
          This package is not cleanly signed — {label}.
        </strong>{" "}
        A distinct authorized approver must re-sign the current version before
        hand-off / transmit. {sr.message}
      </span>
      <Link
        className="chip srb-cta"
        href={`/dossiers/${encodeURIComponent(dossierId)}/viewer#signature-readiness`}
      >
        <PenLine size={13} aria-hidden />
        Go to sign step
      </Link>
    </div>
  );
}

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
    <>
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
    <PlaceholderIdBanner dossierId={dossierId} />
    <SignatureReSignBanner
      sr={content?.signature_readiness}
      dossierId={dossierId}
    />
    </>
  );
}

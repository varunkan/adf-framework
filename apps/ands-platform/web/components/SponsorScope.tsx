"use client";
// WS-OPS-TENANT (round-8) BLOCKER — "Multi-client tenant isolation unproven;
// correspondence defaults to one dossier" (cdmo_ra_manager).
//
// A CRO / CDMO workspace carries MULTIPLE sponsors. The old surfaces pre-filled
// to the first dossier, which read to the panel as "isolation unproven — it
// just picked one and I can't tell whose data I'm looking at". This component
// makes the per-client/sponsor scope the FIRST, EXPLICIT control on the
// Correspondence and Portfolio surfaces, replacing that silent default:
//   1. an explicit per-client/sponsor selector (no auto-pick of dossier #1);
//   2. an honest tenant-isolation / role-based-visibility statement;
//   3. a per-sponsor access indicator that names the active scope.
//
// HONESTY: the hard tenant boundary is the WORKSPACE, enforced at the API
// (cross-workspace reads are refused there, not merely hidden in the UI). The
// sponsor selector is a within-workspace scope for a CRO/CDMO carrying several
// sponsors — we say that plainly rather than implying each sponsor is its own
// API-enforced tenant. Overclaiming here is exactly what would lose trust.
import { useMemo, useState } from "react";
import Link from "next/link";
import { ShieldCheck, ChevronDown, ChevronRight, Building2 } from "lucide-react";
import { tenantName } from "@/lib/auth";

// The minimal shape this control needs off each dossier — kept component-local
// so it works for both the Portfolio (DossierListItem) and Correspondence
// (also DossierListItem) callers without importing a shared page type.
export interface SponsoredItem {
  sponsor?: string | null;
}

export const ALL_SPONSORS = "__all__";
export const UNASSIGNED_SPONSOR = "__unassigned__";

// Distinct sponsors present in the workspace, sorted, with an "unassigned"
// bucket if any dossier has no REP sponsor recorded yet.
export function sponsorsOf(items: SponsoredItem[]): string[] {
  const set = new Set<string>();
  let hasUnassigned = false;
  for (const d of items) {
    const s = (d.sponsor || "").trim();
    if (s) set.add(s);
    else hasUnassigned = true;
  }
  const list = Array.from(set).sort((a, b) => a.localeCompare(b));
  if (hasUnassigned) list.push(UNASSIGNED_SPONSOR);
  return list;
}

// Does a dossier belong to the currently-scoped sponsor?
export function matchesSponsor(d: SponsoredItem, scope: string): boolean {
  if (scope === ALL_SPONSORS) return true;
  const s = (d.sponsor || "").trim();
  if (scope === UNASSIGNED_SPONSOR) return s === "";
  return s === scope;
}

function label(s: string): string {
  if (s === ALL_SPONSORS) return "All sponsors in this workspace";
  if (s === UNASSIGNED_SPONSOR) return "Unassigned (no REP sponsor set)";
  return s;
}

// The explicit per-client/sponsor scope control + isolation statement. Mounted
// as the FIRST control on Correspondence and Portfolio.
export function SponsorScope({
  items,
  value,
  onChange,
  count,
}: {
  items: SponsoredItem[];
  value: string;
  onChange: (scope: string) => void;
  // how many records/dossiers the active scope currently resolves to
  count?: number;
}) {
  const [open, setOpen] = useState(false);
  const sponsors = useMemo(() => sponsorsOf(items), [items]);
  const ws = tenantName();
  const activeLabel = label(value);

  return (
    <section
      className="card glass"
      aria-label="Client / sponsor scope"
      style={{ padding: 16, marginTop: 4 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Building2 size={16} aria-hidden />
        <label htmlFor="sponsor-scope" style={{ margin: 0, fontWeight: 600 }}>
          Client / sponsor
        </label>
        <select
          id="sponsor-scope"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{ width: "auto", minWidth: 260 }}
        >
          <option value={ALL_SPONSORS}>{label(ALL_SPONSORS)}</option>
          {sponsors.map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </select>

        {/* per-sponsor access indicator — names the active scope, never blank */}
        <span
          className="chip ready"
          title="You are viewing only this client / sponsor's records"
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <ShieldCheck size={12} aria-hidden />
          Scope: {activeLabel}
          {typeof count === "number" ? ` · ${count}` : ""}
        </span>

        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button
          className="ghost"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
          {open ? "Hide isolation detail" : "How isolation works"}
        </button>
      </div>

      <p className="mut" style={{ margin: "8px 0 0", fontSize: 12.5, maxWidth: "78ch" }}>
        Pick the client / sponsor whose records you want to work on. Nothing is
        pre-selected to a single dossier — you choose the scope explicitly.
      </p>

      {open && (
        <div className="disclosure-body" style={{ marginTop: 10, display: "grid", gap: 8,
          maxWidth: "80ch" }}>
          <p className="mut" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.5 }}>
            <b>Workspace = the hard tenant boundary.</b> You are signed into the
            {ws ? <> <b>{ws}</b> workspace</> : " workspace"} you belong to.
            Cross-workspace reads are refused at the API layer — not merely
            hidden in the UI — so another client&apos;s workspace is never
            reachable from here.
          </p>
          <p className="mut" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.5 }}>
            <b>Sponsor scope is within this one workspace.</b> A CRO / CDMO
            workspace can carry several sponsors; the selector above filters to
            one sponsor&apos;s dossiers so you don&apos;t mix clients by accident.
            This is a within-workspace filter, not a second API-enforced wall —
            we state that plainly rather than overclaim.
          </p>
          <p className="mut" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.5 }}>
            <b>Role-based visibility.</b> What you can see and do is governed by
            your role in this workspace (who may create / archive / restore /
            sign). Your role is badged on the{" "}
            <Link href="/account">Account &amp; security</Link> permission table.
          </p>
          <p className="mut" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.5 }}>
            <b>What the central governance trail can read across tenants.</b> The
            append-only audit trail records actor + workspace + UTC on every
            change. Governance/audit export is scoped to your own workspace; it
            does not read another workspace&apos;s dossier content. Only the
            platform vendor role can see cross-workspace operational metadata for
            support — never your clients&apos; dossier contents.
          </p>
        </div>
      )}
    </section>
  );
}

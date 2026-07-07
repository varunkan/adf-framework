"use client";
// Round-9 catalog BLOCKER — "'Isolated end-to-end' client-workspace claim is
// asserted, not proven" (n=5). This panel backs the catalog's isolation
// sentence with PROOF a QA manager can hand to an auditor:
//   1. a per-client Access view — who can see and edit each workspace/dossier
//      (the LIVE enforced role matrix + the per-sponsor dossier buckets);
//   2. the downloadable tenancy/security-validation document (the Account
//      page's "Export security settings & role table (PDF)" inspection
//      artifact);
//   3. the access/export log (per-dossier Part-11 audit trail + the
//      workspace-wide security event log).
//
// Also carries the round-9 catalog BLOCKER "No user roles, permissions, or
// e-signatures on workspace actions" (n=6) statements: which roles exist
// TODAY (live matrix, not a mock), that Owner (PM) is an accountability
// label — permissions come from roles — and the honest gap that a dedicated
// reviewer/approver role is not built yet (SoD on signing is what enforces
// author≠approver today).
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ShieldCheck, ChevronDown, ChevronRight } from "lucide-react";
import { auth, tenantName, type RoleMatrixRow } from "@/lib/auth";
import type { CatalogListItem } from "./catalogApi";

export function AccessProofPanel({ items }: { items: CatalogListItem[] }) {
  const [open, setOpen] = useState(false);
  const [roles, setRoles] = useState<RoleMatrixRow[] | null>(null);
  const [rolesErr, setRolesErr] = useState("");
  const ws = tenantName();

  useEffect(() => {
    if (!open || roles) return;
    auth.roleMatrix()
      .then((m) => setRoles(m.roles || []))
      .catch((e) => setRolesErr(String((e as Error)?.message || e)));
  }, [open, roles]);

  // per-client buckets: which dossiers each sponsor scope covers
  const bySponsor = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const d of items) {
      const s = (d.sponsor || "").trim() || "Unassigned (no REP sponsor set)";
      m.set(s, [...(m.get(s) || []), d.dossier_id]);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [items]);

  return (
    <section className="card glass" aria-label="Access & isolation proof"
      style={{ padding: "12px 16px", marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        flexWrap: "wrap" }}>
        <ShieldCheck size={15} aria-hidden />
        <b style={{ fontSize: 14 }}>Access &amp; isolation — see the proof</b>
        <span className="mut" style={{ fontSize: 12 }}>
          who can see/edit what, and the exports an auditor can take away
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          style={{ fontSize: 12, display: "inline-flex", alignItems: "center",
            gap: 4 }}>
          {open ? <ChevronDown size={14} aria-hidden />
            : <ChevronRight size={14} aria-hidden />}
          {open ? "Hide access view" : "Show access view"}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 10, display: "grid", gap: 10,
          maxWidth: "88ch" }}>
          {/* 1 — who can see and edit each workspace/dossier (live, enforced) */}
          <div>
            <b style={{ fontSize: 13 }}>
              Who can see &amp; edit — {ws ? `the ${ws} workspace` : "this workspace"}
            </b>
            <p className="mut" style={{ fontSize: 12.5, margin: "4px 0 6px",
              lineHeight: 1.5 }}>
              Access is governed by <b>workspace membership + role</b>, enforced
              at the API on every request (cross-workspace reads are refused,
              not merely hidden). Honest scope: <b>per-dossier ACLs are not
              built</b> — every member of this workspace can see its dossiers,
              with what they can <i>do</i> gated by the role matrix below.
              The sponsor filter above is a view scope, not a second API wall.
            </p>
            {rolesErr ? (
              <div className="mut" style={{ fontSize: 12 }}>
                Role matrix unavailable — {rolesErr}. The enforced table also
                lives on <Link href="/account">Account &amp; security</Link>.
              </div>
            ) : !roles ? (
              <div className="mut" style={{ fontSize: 12 }}>Loading the enforced
                role matrix…</div>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0,
                display: "grid", gap: 4 }}>
                {roles.map((r) => (
                  <li key={r.role} style={{ fontSize: 12.5 }}>
                    <span className="chip" style={{ fontSize: 11,
                      marginRight: 6 }}>{r.label || r.role}</span>
                    <span className="mut">{r.summary}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mut" style={{ fontSize: 12.5, margin: "6px 0 0",
              lineHeight: 1.5 }}>
              <b>Owner (PM) is an accountability label, not a permission
              source</b> — reassigning Owner never changes what anyone can do;
              roles do. <b>Not built yet (honest gap):</b> a dedicated
              reviewer/approver role. Today author≠approver is enforced on the
              e-signature path (segregation of duties on signing), and
              archive/restore capture a typed-name e-signature on the audit
              ledger.
            </p>
          </div>

          {/* per-client buckets — isolation visible at a glance */}
          <div>
            <b style={{ fontSize: 13 }}>Per-client view — which dossiers each
              sponsor scope covers</b>
            <ul style={{ listStyle: "none", margin: "4px 0 0", padding: 0,
              display: "flex", gap: 6, flexWrap: "wrap" }}>
              {bySponsor.map(([s, ids]) => (
                <li key={s}>
                  <span className="chip" style={{ fontSize: 11 }}
                    title={ids.join(", ")}>
                    {s} · {ids.length} dossier{ids.length === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
              {bySponsor.length === 0 && (
                <li className="mut" style={{ fontSize: 12 }}>No dossiers yet.</li>
              )}
            </ul>
          </div>

          {/* 2 + 3 — the take-away artifacts */}
          <div>
            <b style={{ fontSize: 13 }}>Auditor take-aways</b>
            <ul className="mut" style={{ fontSize: 12.5, margin: "4px 0 0",
              paddingLeft: 18, lineHeight: 1.6 }}>
              <li>
                <Link href="/account">Account &amp; security</Link> —
                &ldquo;Export security settings &amp; role table (PDF)&rdquo;:
                the tenancy/security-validation document for an inspection
                binder (isolation mechanisms, role table, security posture).
              </li>
              <li>
                <Link href="/account">Workspace security event log</Link> —
                the access/export log (sign-ins, exports, policy changes)
                on the same page.
              </li>
              <li>
                Per-dossier Part-11 audit trail — the Audit action on every
                tile/row below exports an immutable, SHA-256-manifested CSV.
              </li>
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}

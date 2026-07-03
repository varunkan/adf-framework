"use client";
// WS4.2 — the 'Your role' section expands into a permission matrix for every
// role, sourced from GET /rbac/matrix (which reads rbac.capabilities_for on the
// server) so what a user sees can never drift from what authorize() enforces.
import { useEffect, useState } from "react";
import { auth, type RoleMatrixRow } from "@/lib/auth";

// human-readable gloss for each enforced capability id
const CAP_LABELS: Record<string, string> = {
  "*": "Everything (platform-wide)",
  "tenant.read": "View this workspace",
  "dossier.read": "Read dossiers",
  "dossier.write": "Create & edit dossiers",
  validate: "Run validation",
  "tenant.manage_users": "Invite & remove members",
  admin: "Workspace administration",
  transmit: "Sign & transmit filings to Health Canada",
  "billing.read": "View billing & plan",
};

export function RoleMatrix({ myRole }: { myRole?: string }) {
  const [rows, setRows] = useState<RoleMatrixRow[] | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || rows) return;
    auth.roleMatrix().then((r) => setRows(r.roles)).catch((e) => setErr(String(e)));
  }, [open, rows]);

  return (
    <div style={{ marginTop: 10 }}>
      <button className="ghost" style={{ fontSize: 13 }}
        aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide role permissions ▲" : "What can each role do? ▼"}
      </button>
      {open && (
        <div style={{ marginTop: 10 }}>
          {err && <div className="notice bad">{err}</div>}
          {!rows && !err && (
            <div className="mut" style={{ fontSize: 13 }}>Loading permissions…</div>
          )}
          {rows && (
            <div style={{ display: "grid", gap: 10 }}>
              {rows.map((row) => (
                <div key={row.role} className="card"
                  style={{ padding: "10px 12px",
                    outline: row.role === myRole
                      ? "1px solid var(--accent, #6ea8fe)" : "none" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline",
                    flexWrap: "wrap" }}>
                    <b style={{ fontSize: 14 }}>{row.label}</b>
                    <code className="mut" style={{ fontSize: 12 }}>{row.role}</code>
                    {row.role === myRole && (
                      <span className="chip ready" style={{ fontSize: 11 }}>
                        Your role
                      </span>
                    )}
                  </div>
                  <p className="mut" style={{ margin: "4px 0 6px", fontSize: 13 }}>
                    {row.summary}
                  </p>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13,
                    display: "grid", gap: 2 }}>
                    {row.capabilities.map((c) => (
                      <li key={c}>{CAP_LABELS[c] || c}</li>
                    ))}
                  </ul>
                  <div className="mut" style={{ marginTop: 6, fontSize: 12 }}>
                    <b>Who assigns it:</b> {row.assignable_by}
                  </div>
                </div>
              ))}
              {/* R6-C: disambiguate the three admin-ish terms professionals
                  conflated (owner / tenant-admin / workspace-admin). */}
              <div className="mut" style={{ fontSize: 12, display: "grid",
                gap: 3 }}>
                <div><b>A note on the admin terms:</b></div>
                <div>
                  <b>Owner</b> — the platform operator who runs this deployment
                  and can act across every workspace. This is the hosting /
                  vendor role, not a customer role.
                </div>
                <div>
                  <b>Workspace admin</b> (internally the <b>tenant admin</b> —
                  &ldquo;tenant&rdquo; is just the code name for a workspace)
                  administers one workspace: invites and removes its members and
                  manages its settings, and can never see another workspace.
                </div>
              </div>
              <p className="mut" style={{ fontSize: 12, margin: 0 }}>
                This table is generated from the same capability sets the API
                enforces on every request — it cannot drift from what is actually
                allowed.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

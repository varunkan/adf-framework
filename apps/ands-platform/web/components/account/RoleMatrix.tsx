"use client";
// WS4.2 — the 'Your role' section expands into a permission matrix for every
// role, sourced from GET /rbac/matrix (which reads rbac.capabilities_for on the
// server) so what a user sees can never drift from what authorize() enforces.
//
// WS-ONBOARDING (round-8) #3 — the three admin-ish names (owner /
// workspace-admin / tenant-admin) confused 11 personas. Fix, UI-side only
// (the server role KEYS are unchanged, so enforcement is untouched):
//  - present plain PARALLEL display labels: Platform vendor / Workspace admin /
//    Company member;
//  - badge "Your role" at the top of the section (in addition to on the row);
//  - move the vendor-only "owner" row behind a collapsed
//    "Advanced / vendor roles" expander so a normal signup sees only the two
//    roles that apply to them.
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

// #3 — plain PARALLEL display labels keyed by the server role id. These override
// the server's `label` only for display; the role KEY (shown as a code chip and
// used for enforcement) is untouched, so this can never drift from authorize().
const DISPLAY_LABEL: Record<string, string> = {
  owner: "Platform vendor",
  "tenant-admin": "Workspace admin",
  user: "Company member",
};

// which role keys are the vendor-only rows hidden behind the Advanced expander
const VENDOR_ROLES = new Set(["owner"]);

function label(row: RoleMatrixRow): string {
  return DISPLAY_LABEL[row.role] || row.label;
}

// onboarding — item 6 (MAJOR n=7): the internal role key is NOISE on the
// default cards, so it only renders when showCode is set (the advanced
// section). The plain-name ↔ key mapping is preserved — relocated into the
// "Advanced / vendor roles" expander below, not deleted.
function RoleCard({ row, myRole, showCode = false }:
  { row: RoleMatrixRow; myRole?: string; showCode?: boolean }) {
  return (
    <div className="card" style={{ padding: "14px 16px",
      outline: row.role === myRole ? "1px solid var(--accent, #6ea8fe)" : "none" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline",
        flexWrap: "wrap" }}>
        <b style={{ fontSize: 15 }}>{label(row)}</b>
        {showCode && (
          <code className="mut" style={{ fontSize: 12 }}>{row.role}</code>
        )}
        {row.role === myRole && (
          <span className="chip ready" style={{ fontSize: 11 }}>Your role</span>
        )}
      </div>
      <p className="mut" style={{ margin: "6px 0 10px", fontSize: 13 }}>
        {row.summary}
      </p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13,
        display: "grid", gap: 4 }}>
        {row.capabilities.map((c) => (
          <li key={c}>{CAP_LABELS[c] || c}</li>
        ))}
      </ul>
      <div className="mut" style={{ marginTop: 10, fontSize: 12 }}>
        <b>Who assigns it:</b> {row.assignable_by}
      </div>
    </div>
  );
}

export function RoleMatrix({ myRole }: { myRole?: string }) {
  const [rows, setRows] = useState<RoleMatrixRow[] | null>(null);
  const [open, setOpen] = useState(false);
  const [showVendor, setShowVendor] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || rows) return;
    auth.roleMatrix().then((r) => setRows(r.roles)).catch((e) => setErr(String(e)));
  }, [open, rows]);

  const myLabel = rows?.find((r) => r.role === myRole);

  return (
    <div style={{ marginTop: 10 }}>
      {/* #3 — surface "Your role" as a plain parallel label right at the top,
          not only buried in the expanded table. */}
      {myLabel && (
        <div style={{ display: "flex", gap: 8, alignItems: "baseline",
          flexWrap: "wrap", marginBottom: 6 }}>
          <span className="chip ready" style={{ fontSize: 11 }}>Your role</span>
          <b style={{ fontSize: 13 }}>{label(myLabel)}</b>
        </div>
      )}
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
              {/* the two roles that apply to a customer signup, shown by default */}
              {rows.filter((r) => !VENDOR_ROLES.has(r.role)).map((row) => (
                <RoleCard key={row.role} row={row} myRole={myRole} />
              ))}

              {/* #3 — the vendor-only "owner" row behind a collapsed expander.
                  item 6 — the internal role keys live HERE now (an "Internal
                  role keys" list for API/integration work), so the default
                  cards stay plain-name only while the mapping stays
                  available. */}
              <div>
                <button className="ghost" style={{ fontSize: 12 }}
                  aria-expanded={showVendor}
                  onClick={() => setShowVendor((v) => !v)}>
                  {showVendor
                    ? "Hide advanced / vendor roles ▲"
                    : "Advanced / vendor roles ▼"}
                </button>
                {showVendor && (
                  <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
                    <p className="mut" style={{ fontSize: 12, margin: 0 }}>
                      This role belongs to the company that hosts the
                      platform, not to your organisation — you will never be
                      assigned it. Shown here for completeness.
                    </p>
                    {rows.filter((r) => VENDOR_ROLES.has(r.role)).map((row) => (
                      <RoleCard key={row.role} row={row} myRole={myRole}
                        showCode />
                    ))}
                    <div>
                      <b style={{ fontSize: 13 }}>
                        Internal role keys (for API / integration work)
                      </b>
                      <ul style={{ margin: "6px 0 0", paddingLeft: 18,
                        fontSize: 12, display: "grid", gap: 4 }}>
                        {rows.map((row) => (
                          <li key={row.role}>
                            {label(row)} → <code>{row.role}</code>
                          </li>
                        ))}
                      </ul>
                      <p className="mut" style={{ fontSize: 12,
                        margin: "6px 0 0" }}>
                        These code keys (e.g. <code>tenant-admin</code>) are
                        the internal identifiers the API enforces — you only
                        need them for API or integration work. Everywhere else
                        the plain name is what each role means for you.
                      </p>
                    </div>
                  </div>
                )}
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

"use client";
// WS-ONBOARDING (round-8) #2 (BLOCKER) — "Audit & compliance" section for the
// Account & security page. Three faithful parts the panel asked for:
//   (a) a login / settings-change event log (who / what / when) for sign-ins,
//       MFA-policy changes and role changes — filtered from the same append-only
//       governance trail the WorkspaceAudit viewer shows, but narrowed to
//       security-relevant events so an inspector sees them without noise;
//   (b) a NAMED 21 CFR Part 11 / GxP-alignment statement — honest about what is
//       implemented (audit trail, access control, e-record integrity) vs. what
//       is roadmap (validated e-signature binding), never claiming certification;
//   (c) an "Export security settings & role table (PDF)" button — opens a clean,
//       print-styled document (browser "Save as PDF") for an inspection binder.
//
// New file, self-contained: reuses governanceApi (audit) + auth.roleMatrix
// (role table) and adds no shared-type edits.
import { useEffect, useState } from "react";
import { governanceApi, type AuditEvent } from "@/lib/governanceApi";
import { auth, type RoleMatrixRow, type Principal } from "@/lib/auth";

// security-relevant categories/actions we surface (who/what/when). We match
// loosely on category + action text so we catch sign-ins, MFA-policy and role
// changes across however the services name them.
const SECURITY_HINTS = [
  "auth", "login", "sign-in", "signin", "session", "mfa", "role",
  "member", "user", "security", "password", "access",
];

function isSecurityEvent(e: AuditEvent): boolean {
  const hay = `${e.category || ""} ${e.action || ""}`.toLowerCase();
  return SECURITY_HINTS.some((h) => hay.includes(h));
}

function when(at: string): string {
  const d = new Date(at);
  return isNaN(d.getTime()) ? at : d.toLocaleString();
}

function actorOf(e: AuditEvent): string {
  const a = e.detail?.actor;
  return typeof a === "string" && a ? a : "—";
}

const DISPLAY_LABEL: Record<string, string> = {
  owner: "Platform vendor",
  "tenant-admin": "Workspace admin",
  user: "Company member",
};

function esc(s: string): string {
  return String(s ?? "").replace(/[&<>]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] || c));
}

// Build a clean printable HTML doc of the security settings + role table and
// hand it to the browser print dialog ("Save as PDF"). Honest: this is a
// browser print export, not a server-signed PDF.
function exportSecurityPdf(
  me: Principal | null,
  roles: RoleMatrixRow[],
  requireMfa: boolean | null,
) {
  const now = new Date().toLocaleString();
  const roleRows = roles.map((r) => `
    <tr>
      <td><b>${esc(DISPLAY_LABEL[r.role] || r.label)}</b><br/>
        <code>${esc(r.role)}</code></td>
      <td>${esc(r.summary)}</td>
      <td>${r.capabilities.map(esc).join(", ")}</td>
      <td>${esc(r.assignable_by)}</td>
    </tr>`).join("");

  const doc = `<!doctype html><html><head><meta charset="utf-8"/>
    <title>ANDS Studio — Security settings &amp; role table</title>
    <style>
      body{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;
        margin:32px;}
      h1{font-size:18px;margin:0 0 4px;} h2{font-size:14px;margin:20px 0 6px;}
      .mut{color:#555;} table{border-collapse:collapse;width:100%;margin-top:6px;}
      th,td{border:1px solid #bbb;padding:6px 8px;text-align:left;
        vertical-align:top;font-size:12px;} th{background:#f0f0f0;}
      code{font-size:11px;color:#555;} .kv{margin:2px 0;}
      .foot{margin-top:24px;font-size:11px;color:#555;}
    </style></head><body>
    <h1>ANDS Studio — Security settings &amp; role table</h1>
    <div class="mut">Inspection export · generated ${esc(now)}</div>
    <h2>Workspace &amp; account</h2>
    <div class="kv">Workspace: <b>${esc(me?.tenant_name || "—")}</b></div>
    <div class="kv">Exported by: <b>${esc(me?.email || "—")}</b>
      (${esc(DISPLAY_LABEL[me?.role || ""] || me?.role || "—")})</div>
    <div class="kv">Workspace MFA policy:
      <b>${requireMfa == null ? "unknown"
        : requireMfa ? "Required for all members" : "Optional per member"}</b></div>
    <div class="kv">Session length: 12 hours (server-enforced)</div>
    <h2>Role &amp; permission table</h2>
    <table><thead><tr>
      <th>Role</th><th>What it is</th><th>Capabilities (enforced by API)</th>
      <th>Who assigns it</th></tr></thead>
      <tbody>${roleRows}</tbody></table>
    <div class="foot">
      Compliance posture: this deployment maintains an append-only, actor- and
      workspace-stamped audit trail and role-based access control aligned to the
      audit-trail and access-control expectations of 21 CFR Part 11 / GxP.
      Validated bound e-signatures are on the roadmap and are NOT claimed here.
      This document is a browser print export for an inspection binder, not a
      cryptographically signed record.
    </div>
    </body></html>`;

  const w = window.open("", "_blank");
  if (!w) return;
  w.document.open();
  w.document.write(doc);
  w.document.close();
  w.focus();
  // give the new document a tick to lay out before printing
  setTimeout(() => { try { w.print(); } catch { /* user can print manually */ } }, 300);
}

export function SecurityCompliance() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [roles, setRoles] = useState<RoleMatrixRow[]>([]);
  const [me, setMe] = useState<Principal | null>(null);
  const [requireMfa, setRequireMfa] = useState<boolean | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    governanceApi.listAudit(200)
      .then((all) => setEvents(all.filter(isSecurityEvent)))
      .catch((e) => { setEvents([]); setErr(String(e?.message || e)); });
    auth.roleMatrix().then((r) => setRoles(r.roles)).catch(() => {});
    auth.me().then(setMe).catch(() => {});
    auth.tenantSecurity().then((s) => setRequireMfa(s.require_mfa)).catch(() => {});
  }, []);

  return (
    <section className="card glass" style={{ padding: "20px 22px",
      maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
        flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Audit &amp; compliance</h2>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" style={{ fontSize: 12 }}
          disabled={!roles.length}
          onClick={() => exportSecurityPdf(me, roles, requireMfa)}>
          Export security settings &amp; role table (PDF)
        </button>
      </div>

      {/* (b) named 21 CFR Part 11 / GxP statement — honest scope */}
      <p className="mut" style={{ marginTop: 12, fontSize: 14 }}>
        <b>21 CFR Part 11 / GxP alignment.</b> Security-relevant actions land on
        an append-only, actor- and workspace-stamped audit trail (below), access
        is governed by role-based capabilities enforced at the API, and stored
        records carry integrity metadata. This aligns with the audit-trail and
        access-control expectations of 21 CFR Part 11 and GxP. Being honest:
        this is an <b>alignment statement, not a certification</b>, and validated
        cryptographically-bound e-signatures are on the roadmap — do not treat
        this as a completed Part-11 e-signature system.
      </p>

      {/* (a) security event log — who / what / when */}
      <h3 style={{ margin: "20px 0 6px" }}>
        Sign-in &amp; security-settings event log
      </h3>
      <p className="mut" style={{ margin: "0 0 10px", fontSize: 13 }}>
        Sign-ins, MFA-policy changes and role changes for this workspace —
        who, what and when. Narrowed from the full audit trail below.
      </p>
      {events === null ? (
        <div className="mut" style={{ fontSize: 13 }}>Loading security events…</div>
      ) : err && events.length === 0 ? (
        <div className="mut" style={{ fontSize: 13 }}>
          Security event log unavailable — {err}
        </div>
      ) : events.length === 0 ? (
        <div className="mut" style={{ fontSize: 13 }}>
          No security-relevant events recorded for this workspace yet.
        </div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {events.map((e) => (
            <li key={e.id} style={{ padding: "6px 2px",
              borderBottom: "1px solid var(--line)", display: "flex", gap: 10,
              alignItems: "baseline", flexWrap: "wrap", fontSize: 13 }}>
              <span className="chip" style={{ fontSize: 11 }}>
                {e.category || "event"}
              </span>
              <b>{e.action}</b>
              <span className="mut" style={{ fontSize: 11 }}>
                {when(e.at)} · by {actorOf(e)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

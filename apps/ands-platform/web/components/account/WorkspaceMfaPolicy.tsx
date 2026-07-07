"use client";
// WS4.1 — workspace-mandated MFA control. Admins (owner / tenant-admin) can flip
// 'require MFA for all members'. This is a CONVENIENCE surface only: enforcement
// lives server-side in the identity login path (service.login →
// _workspace_requires_mfa) and cannot be bypassed from the browser. Non-admins
// see the current policy read-only.
//
// onboarding — MFA default is now Required, server-enforced for NEW workspaces
// (round-9 item 4, BLOCKER n=4): the identity service creates every new
// workspace with require_mfa on, so this card REPORTS the enforced default and
// makes relaxation the explicit admin action (the panel rejected the old
// "Optional per member" + "Recommended: Required" chip pattern).
//
// onboarding — enforced session value in place of a bare dropdown (round-9
// item 7, MAJOR n=6): the session length is a FACT (12 h, SESSION_TTL in the
// identity service, enforced on every request) and is stated as such with no
// 'documented target' caveat. Idle lockout remains genuinely unshipped
// enforcement, so ONLY it keeps the admin-set documented-policy dropdown with
// a caveat narrowed to idle alone.
import { useEffect, useState } from "react";
import { auth, type TenantSecurity } from "@/lib/auth";

const IDLE_KEY = "ands.idlePolicy";

const IDLE_OPTS = [
  { v: "15", label: "15 minutes" },
  { v: "30", label: "30 minutes" },
  { v: "60", label: "1 hour" },
  { v: "off", label: "No idle lockout" },
];

function readPolicy(key: string, fallback: string): string {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}
function writePolicy(key: string, v: string) {
  try { localStorage.setItem(key, v); } catch { /* private mode — non-fatal */ }
}

export function WorkspaceMfaPolicy() {
  const [sec, setSec] = useState<TenantSecurity | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // item 7 — only IDLE lockout remains a documented (declared) policy; the
  // session length is server-enforced and stated as a fact below.
  const [idleMin, setIdleMin] = useState("30");

  useEffect(() => {
    auth.tenantSecurity().then(setSec).catch((e) => setErr(String(e)));
    setIdleMin(readPolicy(IDLE_KEY, "30"));
  }, []);

  async function toggle(next: boolean) {
    setBusy(true); setErr("");
    try {
      const r = await auth.setRequireMfa(next);
      setSec((s) => (s ? { ...s, require_mfa: r.require_mfa } : s));
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  // TIER3-SOD-ENFORCE: flip the 'enforce segregation of duties' policy. When on,
  // an e-signature whose signer is also an author of the signed content is
  // HARD-BLOCKED on the sign path (server-enforced), not just warned.
  async function toggleSod(next: boolean) {
    setBusy(true); setErr("");
    try {
      const r = await auth.setRequireSod(next);
      setSec((s) => (s ? { ...s, require_sod: r.require_sod } : s));
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  const canManage = !!sec?.can_manage;

  return (
    <section className="card glass" style={{ padding: "20px 22px",
      maxWidth: 760 }}>
      <h2 style={{ marginTop: 0 }}>Workspace security policy</h2>
      {!sec ? (
        <div className="mut" style={{ marginTop: 10, fontSize: 13 }}>
          {err ? <span className="notice bad">{err}</span> : "Loading policy…"}
        </div>
      ) : (
        <div style={{ marginTop: 12, fontSize: 13, display: "grid",
          gap: 22 }}>
          {/* ---- MFA policy (server-enforced) ---- */}
          <div>
          <h3 style={{ margin: "0 0 8px" }}>
            Multi-factor authentication
          </h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
            flexWrap: "wrap" }}>
            <span className={sec.require_mfa ? "chip ready" : "chip"}>
              {sec.require_mfa ? "Required for all members ✓ (secure default)"
                : "Optional per member — relaxed by an admin"}
            </span>
            {canManage && (
              <button disabled={busy} onClick={() => toggle(!sec.require_mfa)}>
                {busy ? "Saving…"
                  : sec.require_mfa
                  ? "Relax MFA to optional (records an explicit admin decision)"
                  : "Require MFA for everyone →"}
              </button>
            )}
          </div>
          <p className="mut" style={{ marginTop: 8 }}>
            {sec.require_mfa
              ? "Members without a verified authenticator cannot complete " +
                "sign-in — they are guided to set one up first. Enforced by " +
                "the identity service on every login, not just hidden in the UI. " +
                "This is the default for every new workspace; relaxing it is an " +
                "explicit admin decision."
              : "The default for new workspaces is Required — this workspace " +
                "was relaxed to optional by an admin. Turn it back on to block " +
                "password-only sign-in — members are then required to enrol " +
                "TOTP MFA before they can continue. Enforced server-side on " +
                "every login."}
          </p>
          </div>

          {/* ---- Segregation of duties (server-enforced sign policy) ---- */}
          <div>
          <h3 style={{ margin: "0 0 8px" }}>
            Segregation of duties
          </h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
            flexWrap: "wrap" }}>
            <span className={sec.require_sod ? "chip ready" : "chip"}>
              {sec.require_sod ? "Enforced on signing ✓"
                : "Advisory (warn only)"}
            </span>
            {canManage && (
              <button disabled={busy} onClick={() => toggleSod(!sec.require_sod)}>
                {busy ? "Saving…"
                  : sec.require_sod ? "Make segregation advisory"
                  : "Enforce segregation of duties →"}
              </button>
            )}
          </div>
          <p className="mut" style={{ marginTop: 8 }}>
            {sec.require_sod
              ? "An e-signature is blocked when the signer is also an author of " +
                "the content being signed — a distinct authorized approver must " +
                "apply it. Enforced server-side on the sign path (the dossier " +
                "service), recorded on the Part-11 manifest and audit trail — " +
                "not just a UI warning."
              : "Today the sign step WARNS when the signer is also an author but " +
                "still lets them sign. Turn this on to BLOCK that signature and " +
                "require a distinct authorized approver — enforced server-side, " +
                "recorded on the Part-11 record. This is a workspace control " +
                "over signing; it is not an SSO/IdP identity check."}
          </p>
          </div>

          {/* ---- Session length (enforced fact) + idle lockout (documented
                  policy) — round-9 item 7: the enforced number replaces the
                  bare dropdown; the caveat is narrowed to idle lockout, the
                  only genuinely unshipped enforcement. ---- */}
          <div>
          <h3 style={{ margin: "0 0 8px" }}>
            Session length &amp; idle lockout
          </h3>
          <p style={{ margin: "0 0 10px", fontSize: 13 }}>
            <b>Session length: 12 h</b> — enforced server-side by the identity
            service on every request.
          </p>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
            alignItems: "flex-end" }}>
            <label style={{ display: "grid", gap: 3, fontSize: 12 }}>
              <span className="mut">Idle lockout after</span>
              <select value={idleMin} disabled={!canManage}
                onChange={(e) => { setIdleMin(e.target.value);
                  writePolicy(IDLE_KEY, e.target.value); }}>
                {IDLE_OPTS.map((o) => (
                  <option key={o.v} value={o.v}>{o.label}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="mut" style={{ marginTop: 8, fontSize: 12 }}>
            Idle lockout is your workspace&apos;s <b>documented policy</b> for
            auditors and SOPs; enforcement of the idle timeout is on the
            roadmap. The 12-hour session length above needs no such caveat —
            it is live, server-enforced behaviour.
          </p>
          </div>

          {(!canManage || err) && (
            <div>
              {!canManage && (
                <p className="mut" style={{ fontSize: 12, margin: 0 }}>
                  Only a workspace admin can change these policies.
                </p>
              )}
              {err && <div className="notice bad" style={{ marginTop: 8 }}>{err}</div>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// #5 + #6 — a compact security-policy summary surfaced DURING onboarding (the
// post-login primer), so session length + MFA posture are visible up front
// instead of buried in settings. Self-contained: reads the same declared policy
// and the server MFA state.
export function OnboardingSecuritySummary() {
  const [sec, setSec] = useState<TenantSecurity | null>(null);
  const [idleMin, setIdleMin] = useState("30");

  useEffect(() => {
    auth.tenantSecurity().then(setSec).catch(() => {});
    setIdleMin(readPolicy(IDLE_KEY, "30"));
  }, []);

  const idleLabel = IDLE_OPTS.find((o) => o.v === idleMin)?.label || idleMin;
  return (
    <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
      {/* item 7 — the summary states the ENFORCED session value, not the old
          localStorage-declared one; idle lockout stays the documented policy */}
      <b>Security here:</b> sign-in valid for 12 h (server-enforced) · idle
      lockout {idleLabel} (documented policy) · workspace MFA{" "}
      {sec ? (sec.require_mfa ? "Required ✓ (secure default)"
        : "Optional — relaxed by an admin (default is Required)")
        : "—"}
      {" "}· segregation of duties{" "}
      {sec ? (sec.require_sod ? "Enforced ✓" : "Advisory") : "—"}.
    </div>
  );
}

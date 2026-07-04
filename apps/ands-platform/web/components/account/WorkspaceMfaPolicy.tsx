"use client";
// WS4.1 — workspace-mandated MFA control. Admins (owner / tenant-admin) can flip
// 'require MFA for all members'. This is a CONVENIENCE surface only: enforcement
// lives server-side in the identity login path (service.login →
// _workspace_requires_mfa) and cannot be bypassed from the browser. Non-admins
// see the current policy read-only.
//
// WS-ONBOARDING (round-8) #5 — session/MFA policy:
//  - MFA is presented as Required-by-default: when a workspace is still on the
//    optional setting we show a "Recommended: Required" prompt so a new admin
//    lands on the secure posture rather than discovering it buried in settings.
//  - session length + idle-lockout become an admin-configurable, DOCUMENTED
//    policy (1/4/8/12h + idle timeout). We are honest that this is a declared
//    workspace policy (the live session is still 12h server-side today); the
//    dropdown records the policy the workspace commits to and is surfaced during
//    onboarding via <OnboardingSecuritySummary/>.
import { useEffect, useState } from "react";
import { auth, type TenantSecurity } from "@/lib/auth";

const SESSION_KEY = "ands.sessionPolicy";
const IDLE_KEY = "ands.idlePolicy";

const SESSION_OPTS = [
  { v: "1", label: "1 hour" },
  { v: "4", label: "4 hours" },
  { v: "8", label: "8 hours" },
  { v: "12", label: "12 hours" },
];
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
  // #5 — documented session policy (declared, admin-configurable)
  const [sessionHrs, setSessionHrs] = useState("12");
  const [idleMin, setIdleMin] = useState("30");

  useEffect(() => {
    auth.tenantSecurity().then(setSec).catch((e) => setErr(String(e)));
    setSessionHrs(readPolicy(SESSION_KEY, "12"));
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

  const canManage = !!sec?.can_manage;

  return (
    <section className="card glass" style={{ padding: "14px 18px",
      maxWidth: 720, marginTop: 14 }}>
      <h2 style={{ margin: 0, fontSize: 15 }}>Workspace security policy</h2>
      {!sec ? (
        <div className="mut" style={{ marginTop: 8, fontSize: 13 }}>
          {err ? <span className="notice bad">{err}</span> : "Loading policy…"}
        </div>
      ) : (
        <div style={{ marginTop: 8, fontSize: 13 }}>
          {/* ---- MFA policy (server-enforced) ---- */}
          <h3 style={{ margin: "0 0 6px", fontSize: 13 }}>
            Multi-factor authentication
          </h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
            flexWrap: "wrap" }}>
            <span className={sec.require_mfa ? "chip ready" : "chip"}>
              {sec.require_mfa ? "Required for all members ✓"
                : "Optional per member"}
            </span>
            {!sec.require_mfa && (
              <span className="chip blocked" style={{ fontSize: 11 }}>
                Recommended: Required
              </span>
            )}
            {canManage && (
              <button disabled={busy} onClick={() => toggle(!sec.require_mfa)}>
                {busy ? "Saving…"
                  : sec.require_mfa ? "Make MFA optional"
                  : "Require MFA for everyone →"}
              </button>
            )}
          </div>
          <p className="mut" style={{ marginTop: 8 }}>
            {sec.require_mfa
              ? "Members without a verified authenticator cannot complete " +
                "sign-in — they are guided to set one up first. Enforced by " +
                "the identity service on every login, not just hidden in the UI."
              : "The secure default for a regulated workspace is Required. Turn " +
                "this on to block password-only sign-in — members are then " +
                "required to enrol TOTP MFA before they can continue. Enforced " +
                "server-side on every login."}
          </p>

          {/* ---- Session length + idle lockout (documented policy) ---- */}
          <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>
            Session length &amp; idle lockout
          </h3>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap",
            alignItems: "flex-end" }}>
            <label style={{ display: "grid", gap: 3, fontSize: 12 }}>
              <span className="mut">Sign-in valid for</span>
              <select value={sessionHrs} disabled={!canManage}
                onChange={(e) => { setSessionHrs(e.target.value);
                  writePolicy(SESSION_KEY, e.target.value); }}>
                {SESSION_OPTS.map((o) => (
                  <option key={o.v} value={o.v}>{o.label}</option>
                ))}
              </select>
            </label>
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
            This is your workspace's <b>documented policy</b> for auditors and
            SOPs. Being honest: sessions today expire server-side after 12 hours;
            the policy you set here is recorded as the target and is surfaced to
            members during onboarding. Configurable enforcement of shorter
            windows and idle timeout is on the roadmap.
          </p>

          {!canManage && (
            <p className="mut" style={{ fontSize: 12 }}>
              Only a workspace admin can change these policies.
            </p>
          )}
          {err && <div className="notice bad" style={{ marginTop: 8 }}>{err}</div>}
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
  const [sessionHrs, setSessionHrs] = useState("12");
  const [idleMin, setIdleMin] = useState("30");

  useEffect(() => {
    auth.tenantSecurity().then(setSec).catch(() => {});
    setSessionHrs(readPolicy(SESSION_KEY, "12"));
    setIdleMin(readPolicy(IDLE_KEY, "30"));
  }, []);

  const idleLabel = IDLE_OPTS.find((o) => o.v === idleMin)?.label || idleMin;
  return (
    <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
      <b>Security here:</b> sign-in valid for {sessionHrs}h · idle lockout{" "}
      {idleLabel} · workspace MFA{" "}
      {sec ? (sec.require_mfa ? "Required ✓" : "Optional (Required recommended)")
        : "—"}.
    </div>
  );
}

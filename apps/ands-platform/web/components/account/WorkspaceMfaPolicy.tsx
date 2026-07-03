"use client";
// WS4.1 — workspace-mandated MFA control. Admins (owner / tenant-admin) can flip
// 'require MFA for all members'. This is a CONVENIENCE surface only: enforcement
// lives server-side in the identity login path (service.login →
// _workspace_requires_mfa) and cannot be bypassed from the browser. Non-admins
// see the current policy read-only.
import { useEffect, useState } from "react";
import { auth, type TenantSecurity } from "@/lib/auth";

export function WorkspaceMfaPolicy() {
  const [sec, setSec] = useState<TenantSecurity | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    auth.tenantSecurity().then(setSec).catch((e) => setErr(String(e)));
  }, []);

  async function toggle(next: boolean) {
    setBusy(true); setErr("");
    try {
      const r = await auth.setRequireMfa(next);
      setSec((s) => (s ? { ...s, require_mfa: r.require_mfa } : s));
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  return (
    <section className="card glass" style={{ padding: "14px 18px",
      maxWidth: 720, marginTop: 14 }}>
      <h2 style={{ margin: 0, fontSize: 15 }}>Workspace MFA policy</h2>
      {!sec ? (
        <div className="mut" style={{ marginTop: 8, fontSize: 13 }}>
          {err ? <span className="notice bad">{err}</span> : "Loading policy…"}
        </div>
      ) : (
        <div style={{ marginTop: 8, fontSize: 13 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
            flexWrap: "wrap" }}>
            <span className={sec.require_mfa ? "chip ready" : "chip"}>
              {sec.require_mfa ? "Required for all members ✓"
                : "Optional per member"}
            </span>
            {sec.can_manage && (
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
              : "Turn this on to block password-only sign-in for this " +
                "workspace. Members are then required to enrol TOTP MFA before " +
                "they can continue."}
          </p>
          {!sec.can_manage && (
            <p className="mut" style={{ fontSize: 12 }}>
              Only a workspace admin can change this policy.
            </p>
          )}
          {err && <div className="notice bad" style={{ marginTop: 8 }}>{err}</div>}
        </div>
      )}
    </section>
  );
}

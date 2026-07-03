"use client";
// Account & security — round-4 panel fixes: the workspace identity a user
// sees is the SERVER's record (12/12 personas), and the identity service's
// TOTP MFA (which always existed) finally has a UI (9/12 personas).
import { useEffect, useState } from "react";
import Link from "next/link";
import { auth, type Principal } from "@/lib/auth";
import { UserChip } from "@/components/UserChip";
import { WorkspaceAudit } from "@/components/account/WorkspaceAudit";
import { RoleMatrix } from "@/components/account/RoleMatrix";
import { WorkspaceMfaPolicy } from "@/components/account/WorkspaceMfaPolicy";
import { RoadmapCard } from "@/components/account/RoadmapCard";

type MfaFlow =
  | { step: "idle" }
  | { step: "enrolling"; secret: string; uri: string }
  | { step: "enabled" };

export default function AccountPage() {
  const [me, setMe] = useState<Principal | null>(null);
  const [mfa, setMfa] = useState<MfaFlow>({ step: "idle" });
  const [mfaKnown, setMfaKnown] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    auth.me().then(setMe).catch(() => setMe(null));
    auth.mfa.status()
      .then((s) => { if (s.enabled) setMfa({ step: "enabled" }); })
      .catch(() => {})
      .finally(() => setMfaKnown(true));
  }, []);

  async function startEnroll() {
    setBusy(true); setErr("");
    try {
      const r = await auth.mfa.enroll();
      setMfa({ step: "enrolling", secret: r.secret, uri: r.provisioning_uri });
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  async function verify() {
    setBusy(true); setErr("");
    try {
      await auth.mfa.verify(code);
      setMfa({ step: "enabled" });
      setCode("");
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  return (
    <>
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio <small>· account &amp; security</small>
        </span>
        <span className="spacer" />
        <UserChip />
        <Link className="chip" href="/dossiers">Dossier manager</Link>
        <Link className="chip" href="/portfolio">Portfolio</Link>
        <Link className="chip" href="/registry">Registry</Link>
        <Link className="chip" href="/correspondence">Correspondence</Link>
        <Link className="chip" href="/">Guided journey →</Link>
      </header>
      <main className="dossier-home">
        <h1>Account &amp; security</h1>

        <section className="card glass" style={{ padding: "14px 18px",
          maxWidth: 720 }}>
          <h2 style={{ margin: 0, fontSize: 15 }}>Who you are here</h2>
          {me ? (
            <div style={{ marginTop: 8, fontSize: 14, display: "grid",
              gap: 4 }}>
              <div><span className="mut">Signed in as</span>{" "}
                <b>{me.email}</b></div>
              <div><span className="mut">Workspace</span>{" "}
                <b>{me.tenant_name || "—"}</b>{" "}
                <small className="mut">(from the account record — every
                  dossier, document and filing here is isolated to this
                  workspace)</small></div>
              <div><span className="mut">Role</span> {me.role}</div>
              <RoleMatrix myRole={me.role} />
            </div>
          ) : (
            <div className="mut" style={{ marginTop: 8, fontSize: 13 }}>
              Loading your account…
            </div>
          )}
        </section>

        <section className="card glass" style={{ padding: "14px 18px",
          maxWidth: 720, marginTop: 14 }}>
          <h2 style={{ margin: 0, fontSize: 15 }}>
            Multi-factor authentication
          </h2>
          {!mfaKnown ? (
            <div className="mut" style={{ marginTop: 8, fontSize: 13 }}>
              Checking MFA status…
            </div>
          ) : mfa.step === "enabled" ? (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              <span className="chip ready">Enabled ✓</span>
              <p className="mut" style={{ marginTop: 8 }}>
                Sign-ins to this account now require a 6-digit code from your
                authenticator app in addition to your password.
              </p>
            </div>
          ) : mfa.step === "idle" ? (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              <p className="mut" style={{ margin: "0 0 10px" }}>
                Add a time-based one-time code (TOTP) from any standard
                authenticator app (1Password, Google Authenticator, Authy…)
                as a second factor. Recommended for every account that can
                sign or transmit.
              </p>
              <button onClick={startEnroll} disabled={busy}>
                {busy ? "Working…" : "Set up authenticator app →"}
              </button>
            </div>
          ) : (
            <div style={{ marginTop: 8, fontSize: 13, display: "grid",
              gap: 10 }}>
              <div className="notice">
                <b>Step 1 —</b> add this secret to your authenticator app
                (or paste the setup link into an app that accepts
                otpauth&nbsp;URIs):
                <div style={{ marginTop: 6, display: "flex", gap: 8,
                  alignItems: "center", flexWrap: "wrap" }}>
                  <code style={{ fontSize: 14, letterSpacing: 1 }}>
                    {mfa.secret}
                  </code>
                  <button className="ghost" style={{ fontSize: 12 }}
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(mfa.uri);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 2000);
                      } catch {}
                    }}>
                    {copied ? "Copied ✓" : "Copy setup link"}
                  </button>
                </div>
              </div>
              <div>
                <b>Step 2 —</b> enter the current 6-digit code to confirm:
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <input value={code} inputMode="numeric"
                    placeholder="6-digit code" style={{ maxWidth: 160 }}
                    onChange={(e) => setCode(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && code) verify(); }} />
                  <button onClick={verify} disabled={busy || !code}>
                    {busy ? "Verifying…" : "Turn on MFA →"}
                  </button>
                </div>
                <p className="mut" style={{ marginTop: 6 }}>
                  Nothing is enforced until this code verifies — if you stop
                  here, sign-in stays password-only.
                </p>
              </div>
            </div>
          )}
          {err && <div className="notice bad" style={{ marginTop: 10 }}>
            {err}</div>}
        </section>

        {/* WS4.1: workspace-wide MFA mandate — a NEW section; the per-user MFA
            enrol section above is left untouched. */}
        <WorkspaceMfaPolicy />

        <section className="card glass" style={{ padding: "14px 18px",
          maxWidth: 720, marginTop: 14 }}>
          <h2 style={{ margin: 0, fontSize: 15 }}>Password &amp; sessions</h2>
          <ul className="mut" style={{ margin: "8px 0 0", paddingLeft: 18,
            fontSize: 13, display: "grid", gap: 4 }}>
            <li>Passwords must be at least 10 characters with letters and
              numbers, and are stored only as salted hashes.</li>
            <li>To change your password, sign out and use{" "}
              <Link href="/login">Forgot password?</Link> — a one-time code
              (15-minute expiry) sets the new one and signs out every other
              session on the account.</li>
            <li>Sessions last 12 hours and live in an HttpOnly cookie —
              page scripts can never read your token.</li>
          </ul>
        </section>

        <section className="card glass" style={{ padding: "14px 18px",
          maxWidth: 720, marginTop: 14 }}>
          <h2 style={{ margin: 0, fontSize: 15 }}>
            Deployment &amp; data residency
          </h2>
          <ul className="mut" style={{ margin: "8px 0 0", paddingLeft: 18,
            fontSize: 13, display: "grid", gap: 4 }}>
            <li>ANDS Studio is self-hosted: every service and database runs
              inside your own environment. Nothing leaves it except the
              packages you deliberately transmit to Health Canada.</li>
            <li>Every record is scoped to this workspace at every service —
              cross-workspace reads are refused at the API, not just hidden
              in the UI.</li>
            <li>Honest limits: single sign-on (SAML/OIDC) is not yet
              available — accounts are per-workspace, with TOTP MFA above as
              the second factor. Every state change lands on the append-only
              audit event stream.</li>
          </ul>
        </section>

        {/* WS3: workspace-wide Part-11 audit viewer + inspection export.
            A NEW section only — the MFA/identity/data-residency sections above
            are owned by WS4 and are left untouched. */}
        <WorkspaceAudit />

        {/* WS4.3: honest roadmap of not-yet-built enterprise capabilities. */}
        <RoadmapCard />
      </main>
    </>
  );
}

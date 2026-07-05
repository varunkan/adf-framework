"use client";
// Account & security — round-4 panel fixes: the workspace identity a user
// sees is the SERVER's record (12/12 personas), and the identity service's
// TOTP MFA (which always existed) finally has a UI (9/12 personas).
import { useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { auth, type Principal } from "@/lib/auth";
import { Term } from "@/components/Term";
import { Disclosure } from "@/components/Disclosure";
import { WorkspaceAudit } from "@/components/account/WorkspaceAudit";
import { RoleMatrix } from "@/components/account/RoleMatrix";
import { WorkspaceMfaPolicy } from "@/components/account/WorkspaceMfaPolicy";
import { WorkspaceSsoPolicy } from "@/components/account/WorkspaceSsoPolicy";
import { RoadmapCard } from "@/components/account/RoadmapCard";
import { SecurityCompliance } from "@/components/account/SecurityCompliance";

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
      <TopNav subtitle="account & security" />
      <main className="dossier-home" style={{ display: "grid", gap: 18 }}>
        <h1 style={{ marginBottom: 2 }}>Account &amp; security</h1>

        <section className="card glass" style={{ padding: "20px 22px",
          maxWidth: 760 }}>
          <h2 style={{ marginTop: 0 }}>Who you are here</h2>
          {me ? (
            <div style={{ marginTop: 14, fontSize: 14, display: "grid",
              gap: 14 }}>
              {/* aligned label / value rows so the identity facts scan as a
                  clean two-column list rather than a run-on block */}
              <div style={{ display: "grid",
                gridTemplateColumns: "minmax(120px, max-content) 1fr",
                gap: "10px 18px", alignItems: "baseline" }}>
                <span className="mut">Signed in as</span>
                <b>{me.email}</b>

                <span className="mut"><Term k="workspace">Workspace</Term></span>
                <div>
                  <b>{me.tenant_name || "—"}</b>
                  <div className="mut" style={{ fontSize: 12, marginTop: 3 }}>
                    From the account record — every dossier, document and filing
                    here is isolated to this workspace.
                  </div>
                </div>

                <span className="mut">Role</span>
                <span>{me.role}</span>

                {/* CAMP-SSO-OIDC — how this identity is assured RIGHT NOW: an
                    SSO-verified principal (signed in via the workspace IdP) vs a
                    recorded email (password login). The e-sign / Part-11 record
                    reflects the same distinction. */}
                <span className="mut">Identity</span>
                {me.identity_verified ? (
                  <div>
                    <span className="chip ready">SSO-verified ✓</span>
                    <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
                      Authenticated principal via{" "}
                      {me.identity_issuer || "your identity provider"} — your
                      e-signatures record a verified identity, not just an email.
                    </div>
                  </div>
                ) : (
                  <div>
                    <span className="chip">Recorded email</span>
                    <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
                      Password sign-in — honestly a recorded email. With
                      workspace SSO configured (below), sign-in becomes a
                      verified principal.
                    </div>
                  </div>
                )}
              </div>
              <RoleMatrix myRole={me.role} />
            </div>
          ) : (
            <div className="mut" style={{ marginTop: 10, fontSize: 13 }}>
              Loading your account…
            </div>
          )}
        </section>

        <section className="card glass" style={{ padding: "20px 22px",
          maxWidth: 760 }}>
          <h2 style={{ marginTop: 0 }}>
            <Term k="MFA">Multi-factor authentication</Term>
          </h2>
          {!mfaKnown ? (
            <div className="mut" style={{ marginTop: 10, fontSize: 13 }}>
              Checking MFA status…
            </div>
          ) : mfa.step === "enabled" ? (
            <div style={{ marginTop: 10, fontSize: 13 }}>
              <span className="chip ready">Enabled ✓</span>
              <p className="mut" style={{ marginTop: 8 }}>
                Sign-ins to this account now require a 6-digit code from your
                authenticator app in addition to your password.
              </p>
            </div>
          ) : mfa.step === "idle" ? (
            <div style={{ marginTop: 10, fontSize: 13 }}>
              <p className="mut" style={{ margin: "0 0 10px" }}>
                Add a time-based one-time code (<Term k="TOTP" />) from any
                standard authenticator app (1Password, Google Authenticator,
                Authy…) as a second factor. Recommended for every account that
                can sign or transmit.
              </p>
              <button onClick={startEnroll} disabled={busy}>
                {busy ? "Working…" : "Set up authenticator app →"}
              </button>
            </div>
          ) : (
            <div style={{ marginTop: 10, fontSize: 13, display: "grid",
              gap: 12 }}>
              <div className="notice">
                <b>Step 1 —</b> add this secret to your authenticator app
                (or paste the setup link into an app that accepts{" "}
                <Term k="otpauth URI">otpauth&nbsp;URIs</Term>):
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

        {/* CAMP-SSO-OIDC: per-workspace OpenID Connect single sign-on config. */}
        <WorkspaceSsoPolicy />

        <section className="card glass" style={{ padding: "20px 22px",
          maxWidth: 760 }}>
          <h2 style={{ marginTop: 0 }}>Password &amp; sessions</h2>
          {/* R6-C: plain, non-technical items on the face; the crypto/security
              detail (salted hash, HttpOnly) moves into a "For your IT
              department" expander so the sign-in card stays plain. */}
          <ul className="mut" style={{ margin: "12px 0 0", paddingLeft: 20,
            fontSize: 14, display: "grid", gap: 8 }}>
            <li>Passwords must be at least 10 characters with letters and
              numbers.</li>
            <li>To change your password, sign out and use{" "}
              <Link href="/login">Forgot password?</Link> — a one-time code
              (15-minute expiry) sets the new one and signs out every other
              session on the account.</li>
            <li>You stay signed in for 12 hours, then sign in again.</li>
          </ul>
          <Disclosure
            showLabel="For your IT department"
            hideLabel="Hide IT / security detail"
            summary={<span>How credentials and sessions are secured</span>}
          >
            <ul className="mut" style={{ margin: "6px 0 0", paddingLeft: 20,
              fontSize: 13, display: "grid", gap: 6 }}>
              <li>Passwords are stored only as a{" "}
                <Term k="salted hash" /> — never in a form that can be reversed
                back into the password.</li>
              <li>Your session token lives in an <Term k="HttpOnly" /> cookie,
                so page scripts can never read or exfiltrate it.</li>
              <li>Every security-relevant change lands on the append-only audit
                event stream (see the audit viewer below).</li>
            </ul>
          </Disclosure>
        </section>

        <section className="card glass" style={{ padding: "20px 22px",
          maxWidth: 760 }}>
          <h2 style={{ marginTop: 0 }}>
            Deployment &amp; data residency
          </h2>
          <ul className="mut" style={{ margin: "12px 0 0", paddingLeft: 20,
            fontSize: 14, display: "grid", gap: 10 }}>
            <li>ANDS Studio is self-hosted: every service and database runs
              inside your own environment. Nothing leaves it except the
              packages you deliberately transmit to Health Canada.</li>
            <li>Every record is scoped to this workspace at every service —
              cross-workspace reads are refused at the API, not just hidden
              in the UI.</li>
            <li>Single sign-on via <Term k="OIDC" /> (OpenID Connect,
              Authorization Code + PKCE) is available and configured per
              workspace above — SSO members sign in as IdP-verified principals.
              Being honest about what is <i>not</i> yet built:{" "}
              <Term k="SAML" />, automated provisioning (<Term k="SCIM" />) and{" "}
              <Term k="SIEM" /> streaming remain on the roadmap. Password
              accounts (with <Term k="TOTP" /> MFA above) stay available
              alongside SSO. Every state change lands on the append-only audit
              event stream.</li>
          </ul>
        </section>

        {/* WS-ONBOARDING #2: named 21 CFR Part 11 / GxP statement, a security
            event log (sign-ins / MFA-policy / role changes), and a PDF export of
            the security settings + role table for an inspection binder. */}
        <SecurityCompliance />

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

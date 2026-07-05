"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { Term } from "@/components/Term";

const PW_RULE = "At least 10 characters, with letters and numbers.";

// WS-ONBOARDING (round-8) #7 — a visible FR/EN language cue on a Health Canada
// tool. This toggles the card's leading copy between English and French so the
// bilingual cue actually does something (not a dead decoration). The form
// controls and honesty/isolation copy are left as-is; full app localisation is
// out of scope for this workstream.
type Lang = "en" | "fr";
const L: Record<Lang, {
  signIn: string; createWs: string; resetPw: string;
  isolated: string; whatIsWs: string; wsDesc: string; residency: string;
}> = {
  en: {
    signIn: "Sign in",
    createWs: "Create your workspace",
    resetPw: "Reset your password",
    isolated: "Your clients' dossiers are isolated per workspace.",
    whatIsWs: "What is a workspace?",
    wsDesc: "a workspace is one isolated client company and its dossiers.",
    residency:
      "Self-hosted: run ANDS Studio in your own environment so your data can " +
      "stay resident in Canada.",
  },
  fr: {
    signIn: "Se connecter",
    createWs: "Créer votre espace de travail",
    resetPw: "Réinitialiser votre mot de passe",
    isolated: "Les dossiers de vos clients sont isolés par espace de travail.",
    whatIsWs: "Qu'est-ce qu'un espace de travail ?",
    wsDesc:
      "un espace de travail regroupe une seule société cliente et ses dossiers.",
    residency:
      "Auto-hébergé : exécutez ANDS Studio dans votre propre environnement " +
      "pour que vos données puissent rester au Canada.",
  },
};

export default function LoginPage() {
  const router = useRouter();
  const [lang, setLang] = useState<Lang>("en");
  const [mode, setMode] = useState<"login" | "signup" | "reset" | "sso">("login");
  const [email, setEmail] = useState("");
  // CAMP-SSO-OIDC — SSO is per-workspace, so the user names their workspace,
  // then we redirect to that workspace's configured identity provider.
  const [ssoWorkspace, setSsoWorkspace] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  // WS4.5 — first-run CRO-vs-in-house: 'own' = filing for your own company,
  // 'clients' = a CRO filing on behalf of client companies. Drives the copy so
  // an in-house RA doesn't feel the product is CRO-only.
  const [filingFor, setFilingFor] = useState<"own" | "clients">("own");
  const [revealCode, setRevealCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // reset-mode state
  const [resetSent, setResetSent] = useState(false);
  const [resetCode, setResetCode] = useState("");
  const [devCode, setDevCode] = useState("");
  const [notice, setNotice] = useState("");
  // MFA challenge: shown only after the service asks for it
  const [needMfa, setNeedMfa] = useState(false);
  const [mfaCode, setMfaCode] = useState("");

  function switchMode(m: "login" | "signup" | "reset" | "sso") {
    setMode(m);
    setErr("");
    setNotice("");
    setResetSent(false);
    setResetCode("");
    setDevCode("");
    setRevealCode(false);
  }

  // CAMP-SSO-OIDC — begin an OpenID Connect login for the named workspace: ask
  // the identity service for the IdP authorization redirect, then send the
  // browser there. The IdP returns to /auth/sso/callback with code + state.
  async function startSso() {
    setBusy(true);
    setErr("");
    try {
      const next =
        new URLSearchParams(window.location.search).get("next") || "/dossiers";
      try { sessionStorage.setItem("ands_sso_next", next); } catch {}
      const redirectUri = `${window.location.origin}/auth/sso/callback`;
      const r = await auth.sso.authorize(ssoWorkspace.trim(), redirectUri);
      window.location.assign(r.authorization_url);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  async function go() {
    setBusy(true);
    setErr("");
    try {
      if (mode === "signup") await auth.signup(email, password, company);
      else await auth.login(email, password, mfaCode);
      // read ?next at click time (no useSearchParams hook → no Suspense
      // boundary needed → clean production build)
      router.push(
        new URLSearchParams(window.location.search).get("next") || "/dossiers");
      router.refresh();
    } catch (e) {
      const msg = String(e);
      // workspace-mandated MFA (member has NO enrolled secret): show the guidance
      // message, NOT the 6-digit challenge field — they have nothing to type yet.
      if (/workspace requires multi-factor/i.test(msg)) {
        setNeedMfa(false);
        setErr(msg);
      } else if (/multi-factor|authenticator/i.test(msg)) {
        setNeedMfa(true);
        setErr(needMfa && mfaCode ? "That code didn't verify — codes rotate every 30 seconds; try the current one." : "");
      } else {
        setErr(msg);
      }
      setBusy(false);
    }
  }

  async function requestReset() {
    setBusy(true);
    setErr("");
    try {
      const r = await auth.resetRequest(email);
      setResetSent(true);
      setNotice(r.message);
      if (r.reset_code) { setDevCode(r.reset_code); setRevealCode(false); }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function completeReset() {
    setBusy(true);
    setErr("");
    try {
      await auth.resetComplete(email, resetCode, password);
      switchMode("login");
      setNotice("Password updated — sign in with your new password.");
      setPassword("");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <div className="card glass login-card">
        <div className="brand" style={{ marginBottom: 6, display: "flex",
          alignItems: "center", gap: 8 }}>
          <span className="dot" aria-hidden /> ANDS&nbsp;Studio
          <span className="spacer" style={{ marginLeft: "auto" }} />
          {/* #7 — visible FR/EN language cue */}
          <div role="group" aria-label="Language / Langue"
            style={{ display: "inline-flex", gap: 2, fontSize: 12 }}>
            <button type="button" aria-pressed={lang === "en"}
              className={lang === "en" ? "" : "ghost"}
              style={{ fontSize: 12, padding: "2px 8px" }}
              onClick={() => setLang("en")}>EN</button>
            <button type="button" aria-pressed={lang === "fr"}
              className={lang === "fr" ? "" : "ghost"}
              style={{ fontSize: 12, padding: "2px 8px" }}
              onClick={() => setLang("fr")}>FR</button>
          </div>
        </div>
        <h1 className="step-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {mode === "login" ? L[lang].signIn
            : mode === "signup" ? L[lang].createWs
            : mode === "sso" ? "Sign in with your organization"
            : L[lang].resetPw}
        </h1>

        {/* Intro copy grouped as one calm block with even spacing, instead of
            stacked lines with negative margins crushed together. */}
        <div style={{ display: "grid", gap: 8 }}>
          {mode === "signup" && (
            <p className="mut" style={{ fontSize: 12, margin: 0 }}>
              <Term k="workspace">{L[lang].whatIsWs}</Term> — {L[lang].wsDesc}
            </p>
          )}
          <p className="mut" style={{ fontSize: 13, margin: 0 }}>
            {mode === "login"
              ? L[lang].isolated
              : mode === "signup"
              ? (filingFor === "own"
                ? "One workspace for your company — dossiers, documents and " +
                  "filings stay isolated to your organisation."
                : "One workspace per client company — dossiers, documents and " +
                  "filings stay isolated between the clients you file for.")
              : mode === "sso"
              ? "Use your organisation's identity provider (OpenID Connect). " +
                "You are redirected to your IdP to authenticate, then returned " +
                "here signed in as a verified principal."
              : "Enter your account email. We issue a one-time code (expires " +
                "in 15 minutes) to set a new password."}
          </p>

          {/* #7 — one-line data-residency clarifier: self-hosted can stay in
              Canada (a gating question for HC filers). */}
          <p className="mut" style={{ fontSize: 12, margin: 0 }}>
            🍁 {L[lang].residency}
          </p>
        </div>

        {mode === "signup" && (
          <>
            <div>
              <label>Who are you filing for?</label>
              <div className="cta-row" role="radiogroup"
                aria-label="Who are you filing for?" style={{ gap: 8 }}>
                <button type="button" role="radio"
                  aria-checked={filingFor === "own"}
                  className={filingFor === "own" ? "" : "ghost"}
                  onClick={() => setFilingFor("own")}>
                  Your own company
                </button>
                <button type="button" role="radio"
                  aria-checked={filingFor === "clients"}
                  className={filingFor === "clients" ? "" : "ghost"}
                  onClick={() => setFilingFor("clients")}>
                  On behalf of clients (CRO)
                </button>
              </div>
              <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
                {filingFor === "own"
                  ? "In-house regulatory affairs — one workspace for your "
                    + "organisation's own dossiers."
                  : "Contract research / consultancy — create a separate "
                    + "isolated workspace per client company."}
              </div>
            </div>
            <div>
              <label>
                {filingFor === "own" ? "Your company name" : "Client company name"}
              </label>
              <input value={company} onChange={(e) => setCompany(e.target.value)}
                placeholder={filingFor === "own"
                  ? "Acme Therapeutics Inc." : "Northbridge Regulatory CRO"}
                autoComplete="organization" />
            </div>
          </>
        )}
        {/* CAMP-SSO-OIDC — organization SSO panel (per-workspace OIDC). */}
        {mode === "sso" && (
          <>
            <div>
              <label>Workspace ID</label>
              <input value={ssoWorkspace}
                onChange={(e) => setSsoWorkspace(e.target.value)}
                placeholder="your-workspace-id"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && ssoWorkspace.trim()) startSso();
                }} />
              <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
                Single sign-on is configured per workspace by your admin. Enter
                the workspace ID your admin gave you, then continue to your
                organisation&apos;s identity provider.
              </div>
            </div>
            <p className="mut" style={{ fontSize: 12, marginTop: 4 }}>
              Standard supported: <b>OpenID Connect</b> (Authorization Code +
              PKCE, RS256 id-token validation). SAML, SCIM provisioning and SIEM
              streaming are on the <Link href="/roadmap#sso">roadmap</Link> — not
              claimed here.
            </p>
          </>
        )}

        {mode !== "sso" && (
          <div>
            <label>Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)}
              type="email" placeholder="ra@company.example"
              autoComplete="email" />
          </div>
        )}

        {mode === "reset" && resetSent && (
          <>
            {devCode && (
              <div className="notice" style={{ fontSize: 13 }}>
                <b>Demo environment — no outbound email.</b> In a production
                deployment this code is emailed to {email || "your address"}{" "}
                and never displayed. Here it is available on-screen, but hidden
                until you reveal it so it is never accidentally captured in a
                screenshot of a real workflow.
                <div style={{ marginTop: 6 }}>
                  {revealCode ? (
                    <>One-time code: <b>{devCode}</b>{" "}
                      <button className="ghost" style={{ fontSize: 12 }}
                        onClick={() => setRevealCode(false)}>Hide</button>
                    </>
                  ) : (
                    <button className="ghost" style={{ fontSize: 12 }}
                      onClick={() => setRevealCode(true)}>
                      Reveal demo code
                    </button>
                  )}
                </div>
              </div>
            )}
            <div>
              <label>One-time code</label>
              <input value={resetCode} onChange={(e) => setResetCode(e.target.value)}
                inputMode="numeric" placeholder="8-digit code" />
            </div>
          </>
        )}

        {mode !== "sso" && (mode !== "reset" || resetSent) && (
          <div>
            <label>{mode === "reset" ? "New password" : "Password"}</label>
            <input value={password} onChange={(e) => setPassword(e.target.value)}
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              onKeyDown={(e) => { if (e.key === "Enter" && mode !== "reset") go(); }} />
            {mode !== "login" && (
              <div style={{ fontSize: 12, marginTop: 4 }}
                className={!password ? "mut"
                  : password.length >= 10 && /[a-zA-Z]/.test(password) &&
                    /\d/.test(password) ? "mut" : ""}
                aria-live="polite">
                {!password ? PW_RULE
                  : password.length >= 10 && /[a-zA-Z]/.test(password) &&
                    /\d/.test(password)
                  ? "✓ Meets the password rules."
                  : `✗ ${PW_RULE}${password.length < 10
                      ? ` (${10 - password.length} more characters)` : ""}`}
              </div>
            )}
          </div>
        )}

        {needMfa && mode === "login" && (
          <div>
            <label>Authenticator code</label>
            <input value={mfaCode} onChange={(e) => setMfaCode(e.target.value)}
              inputMode="numeric" placeholder="6-digit code" autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") go(); }} />
            <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
              This account has{" "}
              <Term k="MFA">multi-factor authentication</Term> enabled — a
              second code from your phone. Enter the current 6-digit code from
              your authenticator app.
            </div>
          </div>
        )}

        {notice && <div className="notice" style={{ fontSize: 13 }}>{notice}</div>}
        {err && <div className="notice bad">{err}</div>}

        {mode === "reset" ? (
          <div className="cta-row">
            {!resetSent ? (
              <button onClick={requestReset} disabled={busy || !email}>
                {busy ? "Working…" : "Send me a code →"}
              </button>
            ) : (
              <button onClick={completeReset}
                disabled={busy || !resetCode || !password}>
                {busy ? "Working…" : "Set new password →"}
              </button>
            )}
            <button className="ghost" onClick={() => switchMode("login")}>
              Back to sign in
            </button>
          </div>
        ) : mode === "sso" ? (
          <div className="cta-row">
            <button onClick={startSso} disabled={busy || !ssoWorkspace.trim()}>
              {busy ? "Redirecting…" : "Continue to your identity provider →"}
            </button>
            <button className="ghost" onClick={() => switchMode("login")}>
              Back to sign in
            </button>
          </div>
        ) : (
          <>
            <div className="cta-row">
              <button onClick={go} disabled={busy || !email || !password}>
                {busy ? "Working…" : mode === "login" ? "Sign in →" : "Create workspace →"}
              </button>
              <button className="ghost"
                onClick={() => switchMode(mode === "login" ? "signup" : "login")}>
                {mode === "login" ? "New here? Create a workspace" : "Have an account? Sign in"}
              </button>
            </div>
            {mode === "login" && (
              <>
                <button className="ghost" style={{ fontSize: 13, marginTop: 6 }}
                  onClick={() => switchMode("reset")}>
                  Forgot password?
                </button>
                {/* CAMP-SSO-OIDC — real, built organization SSO (OpenID Connect).
                    This is now a working flow, not a teaser: it opens the SSO
                    panel where the user names their workspace and is redirected
                    to that workspace's IdP. SAML/SCIM/SIEM remain honest roadmap. */}
                <div style={{ marginTop: 10,
                  borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 10 }}>
                  <button className="ghost" style={{ width: "100%" }}
                    onClick={() => switchMode("sso")}>
                    Sign in with your organization (SSO) →
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </main>
  );
}

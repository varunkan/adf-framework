"use client";
import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { auth } from "@/lib/auth";
import { Term } from "@/components/Term";

const PW_RULE = "At least 10 characters, with letters and numbers.";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "signup" | "reset">("login");
  const [email, setEmail] = useState("");
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

  function switchMode(m: "login" | "signup" | "reset") {
    setMode(m);
    setErr("");
    setNotice("");
    setResetSent(false);
    setResetCode("");
    setDevCode("");
    setRevealCode(false);
  }

  async function go() {
    setBusy(true);
    setErr("");
    try {
      if (mode === "signup") await auth.signup(email, password, company);
      else await auth.login(email, password, mfaCode);
      router.push(params.get("next") || "/dossiers");
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
        <div className="brand" style={{ marginBottom: 6 }}>
          <span className="dot" aria-hidden /> ANDS&nbsp;Studio
        </div>
        <h1 className="step-title" style={{ marginTop: 0 }}>
          {mode === "login" ? "Sign in"
            : mode === "signup" ? "Create your workspace"
            : "Reset your password"}
        </h1>
        {mode === "signup" && (
          <p className="mut" style={{ fontSize: 12, marginTop: -4 }}>
            <Term k="workspace">What is a workspace?</Term> — a workspace is
            one isolated client company and its dossiers.
          </p>
        )}
        <p className="mut" style={{ fontSize: 13 }}>
          {mode === "login"
            ? "Your clients' dossiers are isolated per workspace."
            : mode === "signup"
            ? (filingFor === "own"
              ? "One workspace for your company — dossiers, documents and " +
                "filings stay isolated to your organisation."
              : "One workspace per client company — dossiers, documents and " +
                "filings stay isolated between the clients you file for.")
            : "Enter your account email. We issue a one-time code (expires " +
              "in 15 minutes) to set a new password."}
        </p>

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
        <div>
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)}
            type="email" placeholder="ra@company.example" autoComplete="email" />
        </div>

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

        {(mode !== "reset" || resetSent) && (
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
                {/* Round-6 WS-A (front door must feel finished): the SSO teaser
                    and "not available yet" roadmap copy are removed from the
                    sign-in card. SSO stays discoverable via a single small
                    roadmap link — nothing on the front door promises a flow
                    that isn't built. */}
                <div className="mut" style={{ fontSize: 12, marginTop: 10,
                  borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 10 }}>
                  <Link href="/roadmap#sso">Enterprise SSO on the roadmap →</Link>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </main>
  );
}

// useSearchParams() opts a route into client-side rendering, so Next.js requires
// the consuming component to sit under a <Suspense> boundary for static
// prerendering to succeed. Wrapping LoginForm here keeps the sign-in / MFA / SSO
// logic untouched while giving the build a boundary to prerender against.
export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="login-page">
          <div className="card glass login-card">
            <div className="brand" style={{ marginBottom: 6 }}>
              <span className="dot" aria-hidden /> ANDS&nbsp;Studio
            </div>
            <p className="mut" style={{ fontSize: 13 }}>Loading…</p>
          </div>
        </main>
      }
    >
      <LoginForm />
    </Suspense>
  );
}

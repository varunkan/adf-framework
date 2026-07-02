"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { auth } from "@/lib/auth";

const PW_RULE = "At least 10 characters, with letters and numbers.";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "signup" | "reset">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // reset-mode state
  const [resetSent, setResetSent] = useState(false);
  const [resetCode, setResetCode] = useState("");
  const [devCode, setDevCode] = useState("");
  const [notice, setNotice] = useState("");

  function switchMode(m: "login" | "signup" | "reset") {
    setMode(m);
    setErr("");
    setNotice("");
    setResetSent(false);
    setResetCode("");
    setDevCode("");
  }

  async function go() {
    setBusy(true);
    setErr("");
    try {
      if (mode === "signup") await auth.signup(email, password, company);
      else await auth.login(email, password);
      router.push(params.get("next") || "/dossiers");
      router.refresh();
    } catch (e) {
      setErr(String(e));
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
      if (r.reset_code) setDevCode(r.reset_code);
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
        <p className="mut" style={{ fontSize: 13 }}>
          {mode === "login"
            ? "Your clients' dossiers are isolated per workspace."
            : mode === "signup"
            ? "One workspace per client company — dossiers, documents and " +
              "filings stay isolated."
            : "Enter your account email. We issue a one-time code (expires " +
              "in 15 minutes) to set a new password."}
        </p>

        {mode === "signup" && (
          <div>
            <label>Company / client name</label>
            <input value={company} onChange={(e) => setCompany(e.target.value)}
              placeholder="Northbridge Regulatory CRO" autoComplete="organization" />
          </div>
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
                Your one-time code (shown here because this environment has
                no email delivery): <b>{devCode}</b>
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
              <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
                {PW_RULE}
              </div>
            )}
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
                {mode === "login" ? "New client? Create a workspace" : "Have an account? Sign in"}
              </button>
            </div>
            {mode === "login" && (
              <button className="ghost" style={{ fontSize: 13, marginTop: 6 }}
                onClick={() => switchMode("reset")}>
                Forgot password?
              </button>
            )}
          </>
        )}
      </div>
    </main>
  );
}

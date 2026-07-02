"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { auth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

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

  return (
    <main className="login-page">
      <div className="card glass login-card">
        <div className="brand" style={{ marginBottom: 6 }}>
          <span className="dot" aria-hidden /> ANDS&nbsp;Studio
        </div>
        <h1 className="step-title" style={{ marginTop: 0 }}>
          {mode === "login" ? "Sign in" : "Create your workspace"}
        </h1>
        <p className="mut" style={{ fontSize: 13 }}>
          {mode === "login"
            ? "Your clients' dossiers are isolated per workspace."
            : "One workspace per client company — dossiers, documents and " +
              "filings stay isolated."}
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
        <div>
          <label>Password</label>
          <input value={password} onChange={(e) => setPassword(e.target.value)}
            type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
            onKeyDown={(e) => { if (e.key === "Enter") go(); }} />
        </div>
        {err && <div className="notice bad">{err}</div>}
        <div className="cta-row">
          <button onClick={go} disabled={busy || !email || !password}>
            {busy ? "Working…" : mode === "login" ? "Sign in →" : "Create workspace →"}
          </button>
          <button className="ghost" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setErr(""); }}>
            {mode === "login" ? "New client? Create a workspace" : "Have an account? Sign in"}
          </button>
        </div>
      </div>
    </main>
  );
}

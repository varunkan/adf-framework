"use client";
// CAMP-SSO-OIDC — the OIDC redirect_uri landing page. After the user authenticates
// at their organization's identity provider, the IdP redirects the browser back
// here with `?code=...&state=...`. We hand both to the identity service, which
// validates the id_token (RS256 + issuer/audience/nonce), binds the user to the
// verified IdP subject and mints the session cookie — then we continue into the app.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";

export default function SsoCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState<"working" | "error">("working");
  const [err, setErr] = useState("");
  const ran = useRef(false); // the code is single-use — never exchange it twice

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code") || "";
    const state = params.get("state") || "";
    const idpError = params.get("error");
    if (idpError) {
      setStatus("error");
      setErr(params.get("error_description") || idpError);
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setErr("This sign-in link is missing its code or state.");
      return;
    }
    auth.sso
      .callback(state, code)
      .then(() => {
        // the proxy set the HttpOnly session cookie from the callback response
        const next =
          sessionStorage.getItem("ands_sso_next") || "/dossiers";
        try { sessionStorage.removeItem("ands_sso_next"); } catch {}
        router.push(next);
        router.refresh();
      })
      .catch((e) => {
        setStatus("error");
        setErr(String(e));
      });
  }, [router]);

  return (
    <main className="login-page">
      <div className="card glass login-card">
        <div className="brand" style={{ marginBottom: 6, display: "flex",
          alignItems: "center", gap: 8 }}>
          <span className="dot" aria-hidden /> ANDS&nbsp;Studio
        </div>
        {status === "working" ? (
          <>
            <h1 className="step-title" style={{ marginTop: 0 }}>
              Completing sign-in…
            </h1>
            <p className="mut" style={{ fontSize: 13 }}>
              Verifying your organization sign-in and preparing your workspace.
            </p>
          </>
        ) : (
          <>
            <h1 className="step-title" style={{ marginTop: 0 }}>
              Single sign-on didn&apos;t complete
            </h1>
            <div className="notice bad" style={{ fontSize: 13 }}>{err}</div>
            <div className="cta-row" style={{ marginTop: 10 }}>
              <Link href="/login"><button>Back to sign in</button></Link>
            </div>
          </>
        )}
      </div>
    </main>
  );
}

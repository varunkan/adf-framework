"use client";
// CAMP-SSO-OIDC — per-workspace single sign-on (OpenID Connect) configuration.
// An admin (owner / tenant-admin) enables SSO and sets the issuer + client id
// (+ optional client secret / redirect URI). Members then sign in via "Sign in
// with your organization (SSO)" on the login screen, and their signing sessions
// become IdP-VERIFIED principals — which the Part-11 e-sign record reflects.
//
// Honesty: the standard implemented is OpenID Connect Authorization Code + PKCE
// with RS256 id_token validation. SAML, SCIM provisioning and SIEM streaming are
// NOT implemented and are shown as roadmap — never claimed here. The stored
// client secret is never echoed back to the browser (only whether one is set).
import { useEffect, useState } from "react";
import { auth, type SsoConfig } from "@/lib/auth";
import { Term } from "@/components/Term";

export function WorkspaceSsoPolicy() {
  const [cfg, setCfg] = useState<SsoConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  // editable draft
  const [issuer, setIssuer] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [redirectUri, setRedirectUri] = useState("");

  useEffect(() => {
    auth.sso
      .get()
      .then((c) => {
        setCfg(c);
        setIssuer(c.issuer);
        setClientId(c.client_id);
        setRedirectUri(
          c.redirect_uri ||
            (typeof window !== "undefined"
              ? `${window.location.origin}/auth/sso/callback`
              : "")
        );
      })
      .catch((e) => setErr(String(e)));
  }, []);

  async function save(enabled: boolean) {
    setBusy(true);
    setErr("");
    setSaved(false);
    try {
      const next = await auth.sso.set({
        enabled,
        issuer: issuer.trim(),
        client_id: clientId.trim(),
        // blank secret = keep the stored one (the service honours this)
        client_secret: clientSecret,
        redirect_uri: redirectUri.trim(),
      });
      setCfg(next);
      setClientSecret(""); // never keep the secret in component state after save
      setSaved(true);
    } catch (e) {
      setErr(String(e));
    }
    setBusy(false);
  }

  const canManage = !!cfg?.can_manage;

  return (
    <section className="card glass" style={{ padding: "20px 22px",
      maxWidth: 760 }}>
      <h2 style={{ marginTop: 0 }}>
        Single sign-on (<Term k="SSO">SSO</Term> · <Term k="OIDC">OpenID Connect</Term>)
      </h2>
      {!cfg ? (
        <div className="mut" style={{ marginTop: 10, fontSize: 13 }}>
          {err ? <span className="notice bad">{err}</span> : "Loading SSO config…"}
        </div>
      ) : (
        <div style={{ marginTop: 12, fontSize: 13 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
            flexWrap: "wrap" }}>
            <span className={cfg.enabled ? "chip ready" : "chip"}>
              {cfg.enabled ? "Enabled ✓"
                : cfg.configured ? "Configured (off)" : "Not configured"}
            </span>
            {cfg.enabled && (
              <span className="mut" style={{ fontSize: 12 }}>
                Members can sign in via your identity provider — their signing
                sessions are IdP-verified principals.
              </span>
            )}
          </div>

          {canManage ? (
            <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
              <label style={{ display: "grid", gap: 3 }}>
                <span className="mut" style={{ fontSize: 12 }}>
                  OIDC issuer URL
                </span>
                <input value={issuer} onChange={(e) => setIssuer(e.target.value)}
                  placeholder="https://login.microsoftonline.com/…/v2.0" />
              </label>
              <label style={{ display: "grid", gap: 3 }}>
                <span className="mut" style={{ fontSize: 12 }}>Client ID</span>
                <input value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="the OIDC application (client) id" />
              </label>
              <label style={{ display: "grid", gap: 3 }}>
                <span className="mut" style={{ fontSize: 12 }}>
                  Client secret{" "}
                  {cfg.has_secret && (
                    <span className="chip" style={{ fontSize: 11 }}>
                      one is stored
                    </span>
                  )}
                </span>
                <input value={clientSecret} type="password"
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder={cfg.has_secret
                    ? "leave blank to keep the stored secret"
                    : "the OIDC client secret (optional for public clients)"} />
              </label>
              <label style={{ display: "grid", gap: 3 }}>
                <span className="mut" style={{ fontSize: 12 }}>
                  Redirect URI (register this at your IdP)
                </span>
                <input value={redirectUri}
                  onChange={(e) => setRedirectUri(e.target.value)} />
              </label>
              <div className="cta-row">
                {cfg.enabled ? (
                  <>
                    <button disabled={busy} onClick={() => save(true)}>
                      {busy ? "Saving…" : "Save changes"}
                    </button>
                    <button className="ghost" disabled={busy}
                      onClick={() => save(false)}>
                      Disable SSO
                    </button>
                  </>
                ) : (
                  <button disabled={busy || !issuer.trim() || !clientId.trim()}
                    onClick={() => save(true)}>
                    {busy ? "Saving…" : "Enable SSO →"}
                  </button>
                )}
              </div>
              {saved && (
                <div className="notice" style={{ fontSize: 12 }}>
                  Saved. Share your workspace ID with members so they can use{" "}
                  &ldquo;Sign in with your organization (SSO)&rdquo;.
                </div>
              )}
            </div>
          ) : (
            <p className="mut" style={{ marginTop: 8, fontSize: 12 }}>
              Only a workspace admin can configure SSO.
            </p>
          )}

          <p className="mut" style={{ marginTop: 12, fontSize: 12 }}>
            Standard supported: <b>{cfg.protocol}</b>. On successful SSO login the
            user is bound to the IdP-verified subject and the existing session is
            issued. Being honest: <Term k="SAML" />, automated provisioning
            (<Term k="SCIM" />) and <Term k="SIEM" /> streaming are not
            implemented — they remain on the roadmap.
          </p>
          {err && <div className="notice bad" style={{ marginTop: 8 }}>{err}</div>}
        </div>
      )}
    </section>
  );
}

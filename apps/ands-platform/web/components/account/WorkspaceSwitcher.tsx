"use client";
// onboarding — multi-workspace switching + per-client billing (n=1). Round-9
// item 17 (minor), shipped as the LARGEST HONEST SUBSET and stating its limits
// in-UI:
//  - Workspaces are deliberately isolated with separate credentials — there is
//    no server-side "all my workspaces under one login" enumeration, because
//    accounts are not email-verified and matching by email across tenants
//    would leak workspace names/billing to anyone who signs up with the same
//    address. So the list here is DEVICE-LOCAL: workspaces you have signed
//    into from this browser (localStorage `ands.knownWorkspaces`, appended by
//    the login page on successful sign-in). Switching re-authenticates.
//  - Per-client billing visibility for the CURRENT workspace via the
//    authenticated GET /billing read (the identity API enforces same-tenant).
import { useEffect, useState } from "react";
import Link from "next/link";
import { auth, type Principal } from "@/lib/auth";

export const KNOWN_WORKSPACES_KEY = "ands.knownWorkspaces";

export interface KnownWorkspace {
  name: string;
  email: string;
  at: string; // ISO timestamp of the last successful sign-in on this device
}

export function readKnownWorkspaces(): KnownWorkspace[] {
  try {
    const raw = localStorage.getItem(KNOWN_WORKSPACES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr)
      ? arr.filter((w) => w && typeof w.name === "string") : [];
  } catch { return []; }
}

// called by the login page after a successful sign-in / workspace creation
export function rememberWorkspace(name: string, email: string) {
  if (!name) return;
  try {
    const rest = readKnownWorkspaces()
      .filter((w) => !(w.name === name && w.email === email));
    const next = [{ name, email, at: new Date().toISOString() }, ...rest]
      .slice(0, 12);
    localStorage.setItem(KNOWN_WORKSPACES_KEY, JSON.stringify(next));
  } catch { /* private mode — non-fatal */ }
}

interface BillingAccess {
  tenant_id: string;
  state: string;           // ok | grace | blocked
  billing_status: string;  // active | past_due | canceled
  reason?: string;
}

export function WorkspaceSwitcher() {
  const [me, setMe] = useState<Principal | null>(null);
  const [known, setKnown] = useState<KnownWorkspace[]>([]);
  const [billing, setBilling] = useState<BillingAccess | null>(null);
  const [billingErr, setBillingErr] = useState("");

  useEffect(() => {
    setKnown(readKnownWorkspaces());
    auth.me().then((p) => {
      setMe(p);
      if (!p.tenant_id) return;
      // same-tenant billing read — enforced server-side by the identity API
      fetch(`/api/identity/billing?tenant_id=${encodeURIComponent(p.tenant_id)}`,
        { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(`billing read replied ${r.status}`);
          setBilling(await r.json());
        })
        .catch((e) => setBillingErr(String(e?.message || e)));
    }).catch(() => {});
  }, []);

  const others = known.filter((w) => w.name !== (me?.tenant_name || ""));

  return (
    <section className="card glass" style={{ padding: "20px 22px",
      maxWidth: 760 }}>
      <h2 style={{ marginTop: 0 }}>Your client workspaces on this device</h2>
      <p className="mut" style={{ marginTop: 10, fontSize: 13 }}>
        One sign-in per client workspace is the isolation model here — each
        workspace has its own credentials, so switching re-authenticates. This
        list is kept on this device only (workspaces you have signed into from
        this browser); there is no cross-workspace account linking on the
        server, by design.
      </p>

      {/* current workspace + its plan/billing line */}
      <div style={{ marginTop: 10, fontSize: 13, display: "grid", gap: 6 }}>
        <div>
          <span className="chip ready" style={{ fontSize: 11 }}>
            Signed in now
          </span>{" "}
          <b>{me?.tenant_name || "—"}</b>
        </div>
        <div className="mut" style={{ fontSize: 12 }}>
          Plan &amp; billing status:{" "}
          {billing ? (
            <>
              <b>{billing.billing_status || "—"}</b>
              {" · access "}
              <b>{billing.state}</b>
              {billing.reason ? ` — ${billing.reason}` : ""}
            </>
          ) : billingErr ? (
            <>unavailable — {billingErr}</>
          ) : (
            <>loading…</>
          )}
        </div>
      </div>

      {others.length > 0 ? (
        <ul style={{ listStyle: "none", margin: "14px 0 0", padding: 0,
          display: "grid", gap: 8 }}>
          {others.map((w) => (
            <li key={`${w.name}|${w.email}`} style={{ display: "flex",
              gap: 10, alignItems: "baseline", flexWrap: "wrap",
              fontSize: 13 }}>
              <b>{w.name}</b>
              <span className="mut" style={{ fontSize: 11 }}>
                last signed in {new Date(w.at).toLocaleDateString()}
                {w.email ? ` as ${w.email}` : ""}
              </span>
              <Link className="ghost" style={{ fontSize: 12 }}
                href={`/login?email=${encodeURIComponent(w.email || "")}`}>
                Switch → sign in to this workspace
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mut" style={{ marginTop: 12, fontSize: 12 }}>
          No other workspaces have been signed into from this device yet. A
          CRO operator managing several sponsors signs into each sponsor&apos;s
          workspace separately — they will appear here once used.
        </p>
      )}
    </section>
  );
}

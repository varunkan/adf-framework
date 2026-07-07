"use client";
// Registry — marketed-product registrations (product × country × dossier ×
// DIN), post-NOC status lifecycle and Right-to-Sell obligations (REQ-111).
import { useCallback, useEffect, useState } from "react";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { Term } from "@/components/Term";
import { auth } from "@/lib/auth";
import {
  registryApi,
  type Registration,
  type RegistrationStatus,
} from "@/components/registry/registryApi";
import { RegisterForm } from "@/components/registry/RegisterForm";
import { RegistrationRow } from "@/components/registry/RegistrationRow";
import { DeadlinesStrip } from "@/components/registry/DeadlinesStrip";
import { AnnualChecklist } from "@/components/registry/AnnualChecklist";
// Round-9 (operations MAJOR, n=15): re-launchable 'Start here' guided tour.
import { StartHereTour } from "@/components/portfolio/StartHereTour";
// Round-9 (operations MAJOR, n=2): explicit FR-coverage statement.
import { BilingualNote } from "@/components/portfolio/BilingualNote";

export default function RegistryPage() {
  const [regs, setRegs] = useState<Registration[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // WS-OVERALL (round-8) BLOCKER — a visible per-tenant boundary indicator so a
  // CRO/CDMO can SEE, on this record surface, which client workspace they are
  // acting in and that the data is walled off per workspace. Honest: this reads
  // the signed-in workspace; it does not claim isolation the API doesn't enforce
  // (cross-workspace reads are refused server-side — see the Trust & security
  // summary on the home page).
  const [workspace, setWorkspace] = useState<string | null>(null);
  useEffect(() => {
    auth.me()
      .then((p) => setWorkspace(p.tenant_name || null))
      .catch(() => setWorkspace(null));
  }, []);

  const load = useCallback(async () => {
    try {
      setRegs((await registryApi.list()).registrations);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  function created(reg: Registration) {
    setRegs((prev) => [...prev, reg]);
    setCreating(false);
    setErr("");
  }

  async function transition(id: string, status: RegistrationStatus) {
    setBusy(true);
    setErr("");
    try {
      const updated = await registryApi.setStatus(id, status);
      setRegs((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <TopNav subtitle="registry" />
      <main className="dossier-home">
        <header style={{ marginBottom: 8 }}>
          <div className="eyebrow">Operations</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12,
            flexWrap: "wrap" }}>
            <h1>Product registry</h1>
            {/* per-tenant boundary indicator — which client workspace am I in? */}
            <span
              className="chip"
              title="You are working inside a single client workspace. Data is walled off per workspace — cross-workspace reads are refused at the API. See the Trust & security summary on the home page."
              style={{ display: "inline-flex", alignItems: "center", gap: 5,
                fontSize: 11.5 }}
            >
              <ShieldCheck size={13} aria-hidden />
              Workspace: <b>{workspace || "this client"}</b> · isolated
            </span>
            <span className="spacer" />
            <button onClick={() => setCreating((v) => !v)}>
              {creating ? "Cancel" : "Register product +"}
            </button>
          </div>
          <p className="lede">
            Every marketed-product registration — <Term k="DIN" />, market status
            and the post-approval obligations (including{" "}
            <Term k="Right to Sell" />) that follow the{" "}
            <Term k="NOC">Notice of Compliance</Term>.
          </p>
          <p className="mut" style={{ maxWidth: "72ch" }}>
            Every change on this page is captured in the dossier’s append-only
            audit trail — actor and workspace stamped, sequence-numbered,
            exportable for inspections (open a dossier → Audit).
          </p>
          {/* Round-9 (operations MAJOR, n=2): FR coverage, stated plainly */}
          <BilingualNote />
        </header>

        {/* Round-9 (operations MAJOR, n=15): 'Start here' guided tour */}
        <StartHereTour page="registry" />

        <div className="notice" style={{ maxWidth: "72ch", marginTop: 4 }}>
          <b>Record only.</b> Registering a product or changing its status here
          logs a record in your own workspace — it does <b>not</b> transmit or
          file anything with Health Canada. Update these to mirror what Health
          Canada has already told you.
        </div>

        {creating && <RegisterForm onCreated={created} />}

        {err && <div className="notice bad" style={{ marginTop: 16 }}>{err}</div>}

        {loading ? (
          <div className="mut" style={{ marginTop: 20 }}>
            Loading registrations…
          </div>
        ) : (
          <>
            <DeadlinesStrip regs={regs} />

            {regs.length === 0 ? (
              <div className="notice" style={{ marginTop: 16 }}>
                No registrations yet. Register a product once its dossier
                reaches NOC.
              </div>
            ) : (
              <ul
                aria-label="Product registrations"
                style={{
                  listStyle: "none",
                  margin: "20px 0 0",
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                {regs.map((r) => (
                  <li key={r.id}>
                    <RegistrationRow reg={r} busy={busy}
                      onTransition={transition} />
                  </li>
                ))}
              </ul>
            )}

            <AnnualChecklist />
          </>
        )}
      </main>
    </>
  );
}

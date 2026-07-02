"use client";
// Registry — marketed-product registrations (product × country × dossier ×
// DIN), post-NOC status lifecycle and Right-to-Sell obligations (REQ-111).
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { UserChip } from "@/components/UserChip";
import {
  registryApi,
  type Registration,
  type RegistrationStatus,
} from "@/components/registry/registryApi";
import { RegisterForm } from "@/components/registry/RegisterForm";
import { RegistrationRow } from "@/components/registry/RegistrationRow";
import { DeadlinesStrip } from "@/components/registry/DeadlinesStrip";
import { AnnualChecklist } from "@/components/registry/AnnualChecklist";

export default function RegistryPage() {
  const [regs, setRegs] = useState<Registration[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

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
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio <small>· registry</small>
        </span>
        <span className="spacer" />
        <UserChip />
        <Link className="chip" href="/dossiers">Dossier manager</Link>
        <Link className="chip" href="/portfolio">Portfolio</Link>
        <Link className="chip" href="/">Guided journey →</Link>
      </header>
      <main className="dossier-home">
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1>Product registry</h1>
          <span className="spacer" />
          <button onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancel" : "Register product +"}
          </button>
        </div>
        <p className="mut" style={{ maxWidth: "64ch" }}>
          Every marketed-product registration — DIN, market status and the
          post-approval obligations that follow the Notice of Compliance.
        </p>

        {creating && <RegisterForm onCreated={created} />}

        {err && <div className="notice bad">{err}</div>}

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

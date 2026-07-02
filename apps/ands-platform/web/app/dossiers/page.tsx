"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { dossierApi } from "@/lib/dossierApi";
import type { DossierListItem } from "@/lib/dossierTypes";
import { Term } from "@/components/Term";
import { UserChip } from "@/components/UserChip";

export default function DossiersHome() {
  const router = useRouter();
  const [items, setItems] = useState<DossierListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [did, setDid] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setItems((await dossierApi.listDossiers()).dossiers);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function remove(e: React.MouseEvent, dossierId: string) {
    e.preventDefault();  // the tile is a Link — don't navigate
    e.stopPropagation();
    if (!window.confirm(
      `Delete dossier ${dossierId} and all of its documents? This cannot be undone.`)) return;
    setErr("");
    try {
      await dossierApi.deleteDossier(dossierId);
      await load();
    } catch (er) {
      setErr(String(er));
    }
  }

  function usePlaceholder() {
    // 'd' prefix = draft: work starts now, the real HC ID replaces it later
    setDid("d" + String(Math.floor(100000 + Math.random() * 900000)));
    setErr("");
  }

  async function setRealId(e: React.MouseEvent, oldId: string) {
    e.preventDefault();
    e.stopPropagation();
    const newId = window.prompt(
      "Enter the Dossier ID issued by Health Canada (one letter + 6–7 " +
      "digits, e.g. e123456).\nAll documents, sequences and history move " +
      "with it.", "");
    if (!newId) return;
    setErr("");
    try {
      await dossierApi.renameDossier(oldId, newId.trim().toLowerCase());
      await load();
    } catch (er) {
      setErr(String(er));
    }
  }

  async function create() {
    if (!/^[a-z]\d{6,7}$/.test(did.trim())) {
      setErr("Dossier ID must be one letter + 6–7 digits (e.g. e123456)");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await dossierApi.createDossier({ dossier_id: did.trim(), title, cs_be_only: true });
      router.push(`/dossiers/${encodeURIComponent(did.trim())}/m/1`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio <small>· dossier manager</small>
        </span>
        <span className="spacer" />
        <UserChip />
        <Link className="chip" href="/portfolio">Portfolio</Link>
        <Link className="chip" href="/registry">Registry</Link>
        <Link className="chip" href="/correspondence">Correspondence</Link>
        <Link className="chip" href="/">Guided journey →</Link>
      </header>
      <main className="dossier-home">
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1>Your product dossiers</h1>
          <span className="spacer" />
          <button onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancel" : "New dossier +"}
          </button>
        </div>
        <p className="mut" style={{ maxWidth: "64ch" }}>
          A <Term k="Dossier ID" /> is the permanent file for one product at Health
          Canada. Open a dossier to build its eCTD Module 1–5 — upload or author
          every document with full guidance on each section.
        </p>

        {creating && (
          <div className="card glass" style={{ maxWidth: 560, marginTop: 8 }}>
            <div className="field-row">
              <div>
                <label>Dossier ID</label>
                <input value={did} onChange={(e) => setDid(e.target.value)}
                  placeholder="e123456" />
              </div>
              <div>
                <label>Product name</label>
                <input value={title} onChange={(e) => setTitle(e.target.value)}
                  placeholder="Drugazole 10 mg tablet" />
              </div>
            </div>
            <p className="mut" style={{ fontSize: 12, margin: "6px 0 0" }}>
              Health Canada issues your Dossier ID when you file a Dossier ID
              Request through REP (via your CESG account).{" "}
              <button className="ghost" style={{ fontSize: 12, padding: "0 4px" }}
                onClick={usePlaceholder}>
                No ID yet? Start with a placeholder →
              </button>{" "}
              You can set the real ID any time; validation reminds you before
              filing.
            </p>
            <div className="cta-row">
              <button onClick={create} disabled={busy}>
                {busy ? "Creating…" : "Create & open →"}
              </button>
            </div>
          </div>
        )}

        {err && <div className="notice bad">{err}</div>}

        {loading ? (
          <div className="mut" style={{ marginTop: 20 }}>Loading dossiers…</div>
        ) : items.length === 0 ? (
          <div className="notice" style={{ marginTop: 16 }}>
            No dossiers yet. Create one to start building a submission.
          </div>
        ) : (
          <div className="dossier-grid">
            {items.map((d) => {
              const passed = d.tower.filter((t) => t.state === "pass").length;
              const applic = d.tower.filter((t) => t.state !== "na").length;
              return (
                <Link key={d.dossier_id} href={`/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`}
                  className="card glass dossier-tile">
                  <div className="d-id">
                    {d.dossier_id}
                    {d.dossier_id.startsWith("d") && (
                      <button className="chip blocked" title="Placeholder ID — set the real Health Canada Dossier ID"
                        style={{ marginLeft: 8, fontSize: 11 }}
                        onClick={(e) => setRealId(e, d.dossier_id)}>
                        draft ID — set real ✎
                      </button>
                    )}
                  </div>
                  <div className="d-title">{d.title}</div>
                  <div className="d-meta mut">{d.submission_type} · CS-BE</div>
                  <div className="progress"><i style={{
                    width: `${applic ? (passed / applic) * 100 : 0}%` }} /></div>
                  <span className={`chip ${d.gate?.complete ? "ready" : "blocked"}`}>
                    {d.gate?.complete ? "Ready to file" : `${passed}/${applic} modules`}
                  </span>
                  <button className="tile-delete" title={`Delete ${d.dossier_id}`}
                    aria-label={`Delete dossier ${d.dossier_id}`}
                    onClick={(e) => remove(e, d.dossier_id)}>✕</button>
                </Link>
              );
            })}
          </div>
        )}
      </main>
    </>
  );
}

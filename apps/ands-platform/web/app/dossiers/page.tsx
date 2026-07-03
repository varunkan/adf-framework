"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { dossierApi } from "@/lib/dossierApi";
import type { DossierListItem } from "@/lib/dossierTypes";
import { Term } from "@/components/Term";
import { UserChip } from "@/components/UserChip";
import { Modal } from "@/components/Modal";

type ArchivedItem = DossierListItem & {
  archived_at?: string;
  archived_by?: string;
  archive_reason?: string;
};

export default function DossiersHome() {
  const router = useRouter();
  const [items, setItems] = useState<DossierListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [did, setDid] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // in-app modal state (replaces native confirm/prompt)
  const [delTarget, setDelTarget] = useState<string | null>(null);
  const [delTyped, setDelTyped] = useState("");
  const [delReason, setDelReason] = useState("");
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [renameNew, setRenameNew] = useState("");
  const [renameReason, setRenameReason] = useState("");
  const [modalBusy, setModalBusy] = useState(false);
  const [modalErr, setModalErr] = useState("");

  // recoverable 'trash' (archived dossiers) — restore with undo
  const [showArchived, setShowArchived] = useState(false);
  const [archived, setArchived] = useState<ArchivedItem[]>([]);

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

  const loadArchived = useCallback(async () => {
    try {
      setArchived((await dossierApi.listArchived()).dossiers);
    } catch (er) {
      setErr(String(er));
    }
  }, []);

  function openDelete(e: React.MouseEvent, dossierId: string) {
    e.preventDefault();  // the tile is a Link — don't navigate
    e.stopPropagation();
    setDelTarget(dossierId);
    setDelTyped("");
    setDelReason("");
    setModalErr("");
  }

  async function confirmDelete() {
    if (!delTarget) return;
    setModalBusy(true);
    setModalErr("");
    try {
      // send the typed Dossier ID as confirm_id — the server re-checks it
      // (a direct API DELETE cannot bypass this typed-confirmation gate).
      await dossierApi.deleteDossier(delTarget, delReason.trim(),
        delTyped.trim());
      setDelTarget(null);
      await load();
      if (showArchived) await loadArchived();
    } catch (er) {
      setModalErr(String(er));
    } finally {
      setModalBusy(false);
    }
  }

  async function restore(dossierId: string) {
    setErr("");
    try {
      await dossierApi.restoreDossier(dossierId, "restored from dossier manager");
      await Promise.all([load(), loadArchived()]);
    } catch (er) {
      setErr(String(er));
    }
  }

  function usePlaceholder() {
    // 'd' prefix = draft: work starts now, the real HC ID replaces it later
    setDid("d" + String(Math.floor(100000 + Math.random() * 900000)));
    setErr("");
  }

  function openRename(e: React.MouseEvent, oldId: string) {
    e.preventDefault();
    e.stopPropagation();
    setRenameTarget(oldId);
    setRenameNew("");
    setRenameReason("");
    setModalErr("");
  }

  async function confirmRename() {
    if (!renameTarget) return;
    const next = renameNew.trim().toLowerCase();
    if (!/^[a-z]\d{6,7}$/.test(next)) {
      setModalErr("Dossier ID must be one letter + 6–7 digits (e.g. e123456)");
      return;
    }
    setModalBusy(true);
    setModalErr("");
    try {
      await dossierApi.renameDossier(renameTarget, next, renameReason.trim());
      setRenameTarget(null);
      await load();
    } catch (er) {
      setModalErr(String(er));
    } finally {
      setModalBusy(false);
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
        <Link className="chip" href="/help">Help</Link>
        <Link className="chip" href="/portfolio">Portfolio</Link>
        <Link className="chip" href="/registry">Registry</Link>
        <Link className="chip" href="/correspondence">Correspondence</Link>
        <Link className="chip" href="/">Guided journey →</Link>
      </header>
      <main className="dossier-home">
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1>Your product dossiers</h1>
          <span className="spacer" />
          <button className="ghost" onClick={() => {
            const next = !showArchived;
            setShowArchived(next);
            if (next) loadArchived();
          }}>
            {showArchived ? "Hide archived" : "View archived (trash)"}
          </button>
          <button onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancel" : "New dossier +"}
          </button>
        </div>
        <p className="mut" style={{ maxWidth: "64ch" }}>
          A <Term k="Dossier ID" /> is the permanent file for one product at Health
          Canada. Open a dossier to build its eCTD Module 1–5 — upload or author
          every document with full guidance on each section. Everything on this
          page belongs to your workspace alone: client workspaces are isolated
          end-to-end (per-workspace data partitions, tenant-checked on every
          request, cross-client access is structurally impossible).
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
                        onClick={(e) => openRename(e, d.dossier_id)}>
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
                    onClick={(e) => openDelete(e, d.dossier_id)}>✕</button>
                </Link>
              );
            })}
          </div>
        )}

        {showArchived && (
          <section className="card glass" style={{ marginTop: 20, padding: 16 }}>
            <h2 style={{ margin: 0, fontSize: 15 }}>Archived (recoverable)</h2>
            <p className="mut" style={{ fontSize: 12, margin: "6px 0 0",
              maxWidth: "72ch" }}>
              Deleting a dossier archives it here rather than destroying it —
              nothing is purged. Restore any archived dossier to return it to
              your working list; every delete and restore is on the audit trail.
            </p>
            {archived.length === 0 ? (
              <div className="mut" style={{ marginTop: 12, fontSize: 13 }}>
                No archived dossiers.
              </div>
            ) : (
              <ul style={{ listStyle: "none", margin: "12px 0 0", padding: 0,
                display: "flex", flexDirection: "column", gap: 8 }}>
                {archived.map((a) => (
                  <li key={a.dossier_id} className="card" style={{
                    padding: "10px 14px", display: "flex", gap: 12,
                    alignItems: "baseline", flexWrap: "wrap" }}>
                    <b>{a.dossier_id}</b>
                    <span className="mut" style={{ fontSize: 13 }}>{a.title}</span>
                    <span className="spacer" style={{ marginLeft: "auto" }} />
                    <span className="mut" style={{ fontSize: 11,
                      flexBasis: "100%" }}>
                      archived {a.archived_at ? new Date(a.archived_at)
                        .toLocaleString() : "—"}
                      {a.archived_by ? ` · by ${a.archived_by}` : ""}
                      {a.archive_reason ? ` · reason: ${a.archive_reason}` : ""}
                    </span>
                    <button onClick={() => restore(a.dossier_id)}>
                      Restore ↩
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </main>

      {delTarget && (
        <Modal
          title="Delete this dossier?"
          onClose={() => setDelTarget(null)}
          footer={
            <>
              <button className="ghost" onClick={() => setDelTarget(null)}>
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={
                  modalBusy || delTyped.trim() !== delTarget || !delReason.trim()
                }
              >
                {modalBusy ? "Archiving…" : "Archive dossier"}
              </button>
            </>
          }
        >
          <p className="mut" style={{ fontSize: 13, marginTop: 0 }}>
            This does <b>not</b> permanently destroy the dossier — it moves{" "}
            <b>{delTarget}</b> and all of its documents to the archive (trash),
            where it can be <b>restored with undo</b>. The action is recorded on
            the append-only audit trail.
          </p>
          <label style={{ fontSize: 13 }}>
            Type the Dossier ID <code>{delTarget}</code> to confirm
          </label>
          <input
            value={delTyped}
            autoFocus
            onChange={(e) => setDelTyped(e.target.value)}
            placeholder={delTarget}
            style={{ width: "100%", marginTop: 4 }}
          />
          <label style={{ fontSize: 13, marginTop: 10, display: "block" }}>
            Reason for change (required)
          </label>
          <input
            value={delReason}
            onChange={(e) => setDelReason(e.target.value)}
            placeholder="e.g. duplicate created in error"
            style={{ width: "100%", marginTop: 4 }}
          />
          {modalErr && (
            <div className="notice bad" style={{ marginTop: 10 }}>{modalErr}</div>
          )}
        </Modal>
      )}

      {renameTarget && (
        <Modal
          title="Set the real Health Canada Dossier ID"
          onClose={() => setRenameTarget(null)}
          footer={
            <>
              <button className="ghost" onClick={() => setRenameTarget(null)}>
                Cancel
              </button>
              <button onClick={confirmRename} disabled={modalBusy || !renameNew.trim()}>
                {modalBusy ? "Applying…" : "Apply new ID"}
              </button>
            </>
          }
        >
          <p className="mut" style={{ fontSize: 13, marginTop: 0 }}>
            Re-key <b>{renameTarget}</b> to the Dossier ID issued by Health
            Canada (one letter + 6–7 digits, e.g. <code>e123456</code>). All
            documents, sequences and history move with it. The before/after IDs
            and your reason are written to the audit trail.
          </p>
          <label style={{ fontSize: 13 }}>New Dossier ID</label>
          <input
            value={renameNew}
            autoFocus
            onChange={(e) => setRenameNew(e.target.value)}
            placeholder="e123456"
            style={{ width: "100%", marginTop: 4 }}
          />
          <label style={{ fontSize: 13, marginTop: 10, display: "block" }}>
            Reason for change (optional)
          </label>
          <input
            value={renameReason}
            onChange={(e) => setRenameReason(e.target.value)}
            placeholder="e.g. HC issued Dossier ID via REP"
            style={{ width: "100%", marginTop: 4 }}
          />
          {modalErr && (
            <div className="notice bad" style={{ marginTop: 10 }}>{modalErr}</div>
          )}
        </Modal>
      )}
    </>
  );
}

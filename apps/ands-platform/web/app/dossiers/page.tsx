"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { dossierApi } from "@/lib/dossierApi";
import type { DossierListItem } from "@/lib/dossierTypes";
import { Term } from "@/components/Term";
import { TopNav } from "@/components/TopNav";
import { Modal } from "@/components/Modal";
import { SetRealDossierIdModal } from "@/components/dossier/SetRealDossierIdModal";
import { auth } from "@/lib/auth";
import { dueMeta } from "@/lib/deadline";
import { toast } from "sonner";

// The three Health Canada abbreviated/supplemental pathways this tool models.
// comparative-BE (cs_be_only) is an ANDS-only property, not a submission type.
const SUBMISSION_TYPES = [
  { code: "ANDS", label: "ANDS — Abbreviated New Drug Submission (generic)" },
  { code: "SANDS", label: "SANDS — Supplement to an ANDS (post-NOC change)" },
  { code: "SNDS", label: "SNDS — Supplement to a New Drug Submission" },
] as const;

type SortKey =
  | "dossier_id" | "title" | "status" | "submission_type"
  | "sponsor" | "owner" | "soonest_due";

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
  // R7: submission type is chosen at creation (no longer hardcoded ANDS/CS-BE);
  // cs_be_only is an ANDS-only comparative-BE property, sponsor/owner feed the
  // portfolio list view (WS6 fields already round-trip to the index).
  const [subType, setSubType] = useState<string>("ANDS");
  const [csBeOnly, setCsBeOnly] = useState(true);
  const [sponsor, setSponsor] = useState("");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // R7 catalog list/table view — triage dozens of dossiers across sponsors.
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [sortKey, setSortKey] = useState<SortKey>("soonest_due");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filterText, setFilterText] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [myEmail, setMyEmail] = useState<string>("");
  useEffect(() => {
    auth.me().then((m) => setMyEmail((m?.name || m?.email || "").toLowerCase()))
      .catch(() => {});
  }, []);

  // in-app modal state (replaces native confirm/prompt)
  const [delTarget, setDelTarget] = useState<string | null>(null);
  const [delTyped, setDelTyped] = useState("");
  const [delReason, setDelReason] = useState("");
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalErr, setModalErr] = useState("");

  // POLISH-ID-BEFORE-409: the set-real-ID + REP flow now lives in the shared
  // SetRealDossierIdModal (reused by the builder chrome). Seed it with any
  // known sponsor/company for the target dossier.
  const [renameSeedCompany, setRenameSeedCompany] = useState("");
  const [renameSeedSponsor, setRenameSeedSponsor] = useState("");

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
      toast.success(`${delTarget} archived — recoverable from Trash`);
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
      toast.success(`${dossierId} restored`);
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
    // seed the REP helper with any known sponsor/company for this dossier
    const d = items.find((it) => it.dossier_id === oldId);
    setRenameSeedCompany((d as { company_id?: string })?.company_id || "");
    setRenameSeedSponsor((d as { sponsor?: string })?.sponsor || "");
  }

  async function create() {
    if (!/^[a-z]\d{6,7}$/.test(did.trim())) {
      setErr("Dossier ID must be one letter + 6–7 digits (e.g. e123456)");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await dossierApi.createDossier({
        dossier_id: did.trim(),
        title,
        submission_type: subType,
        // cs_be_only only means something on the ANDS path; force false otherwise
        cs_be_only: subType === "ANDS" ? csBeOnly : false,
        sponsor: sponsor.trim() || undefined,
        owner: owner.trim() || undefined,
      });
      toast.success(`Dossier ${did.trim()} created`);
      router.push(`/dossiers/${encodeURIComponent(did.trim())}/m/1`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  // R7: honest per-tile submission label. CS-BE is shown ONLY when the dossier
  // is actually a comparative-BE ANDS (cs_be_only) — never hardcoded.
  function typeLabel(d: DossierListItem): string {
    const t = d.submission_type || "ANDS";
    return t === "ANDS" && d.cs_be_only ? `${t} · CS-BE` : t;
  }

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir((v) => (v === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir("asc"); }
  }

  const rows = useMemo(() => {
    const q = filterText.trim().toLowerCase();
    let out = items.filter((d) => {
      if (mineOnly && myEmail &&
          (d.owner || "").toLowerCase() !== myEmail) return false;
      if (!q) return true;
      return [d.dossier_id, d.title, d.submission_type, d.sponsor, d.owner]
        .some((v) => String(v || "").toLowerCase().includes(q));
    });
    const val = (d: DossierListItem): string | number => {
      switch (sortKey) {
        case "status": {
          const applic = d.tower.filter((t) => t.state !== "na").length;
          const passed = d.tower.filter((t) => t.state === "pass").length;
          return d.gate?.complete ? 1e6 : (applic ? passed / applic : 0);
        }
        case "submission_type": return typeLabel(d);
        case "soonest_due":
          // no deadline sorts last on asc (Infinity), first on desc
          return d.soonest_due ? Date.parse(d.soonest_due) : Number.MAX_SAFE_INTEGER;
        case "title": return (d.title || "").toLowerCase();
        case "sponsor": return (d.sponsor || "").toLowerCase();
        case "owner": return (d.owner || "").toLowerCase();
        default: return (d.dossier_id || "").toLowerCase();
      }
    };
    out = [...out].sort((a, b) => {
      const va = val(a), vb = val(b);
      const c = va < vb ? -1 : va > vb ? 1 : 0;
      return sortDir === "asc" ? c : -c;
    });
    return out;
  }, [items, filterText, mineOnly, myEmail, sortKey, sortDir]);

  const sortArrow = (k: SortKey) =>
    sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "";

  return (
    <>
      <TopNav subtitle="dossier manager" />
      <main className="dossier-home">
        <div style={{ display: "flex", alignItems: "baseline", gap: 12,
          flexWrap: "wrap" }}>
          <h1>Your product dossiers</h1>
          <span className="spacer" />
          <div className="seg" role="group" aria-label="View mode">
            <button className={viewMode === "grid" ? "on" : ""}
              aria-pressed={viewMode === "grid"}
              onClick={() => setViewMode("grid")}>Grid</button>
            <button className={viewMode === "list" ? "on" : ""}
              aria-pressed={viewMode === "list"}
              onClick={() => setViewMode("list")}>List</button>
          </div>
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
          Canada. Open a dossier to build its <Term k="eCTD" />{" "}
          <Term k="Module 1">Module 1–5</Term> — upload or author
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
                <p className="mut" style={{ fontSize: 11, margin: "3px 0 0" }}>
                  Format: one letter + 6–7 digits (e.g. <code>e123456</code>).
                  A <code>d…</code> placeholder marks a draft ID until Health
                  Canada issues the real one.
                </p>
              </div>
              <div>
                <label>Product name</label>
                <input value={title} onChange={(e) => setTitle(e.target.value)}
                  placeholder="Drugazole 10 mg tablet" />
              </div>
            </div>
            <div className="field-row">
              <div>
                <label>Submission type</label>
                <select value={subType}
                  onChange={(e) => setSubType(e.target.value)}
                  style={{ width: "100%" }}>
                  {SUBMISSION_TYPES.map((t) => (
                    <option key={t.code} value={t.code}>{t.label}</option>
                  ))}
                </select>
                {subType === "ANDS" && (
                  <label style={{ display: "flex", alignItems: "center",
                    gap: 6, fontSize: 12, marginTop: 6, fontWeight: 400 }}>
                    <input type="checkbox" checked={csBeOnly}
                      style={{ width: "auto" }}
                      onChange={(e) => setCsBeOnly(e.target.checked)} />
                    Comparative-BE only (<Term k="CS-BE" /> path — suppresses the
                    nonclinical/clinical summaries)
                  </label>
                )}
              </div>
              <div>
                <label>Client / sponsor <span className="mut"
                  style={{ fontWeight: 400 }}>(optional)</span></label>
                <input value={sponsor} onChange={(e) => setSponsor(e.target.value)}
                  placeholder="Acme Pharma Inc." />
                <label style={{ marginTop: 6 }}>Owner (PM) <span className="mut"
                  style={{ fontWeight: 400 }}>(optional)</span></label>
                <input value={owner} onChange={(e) => setOwner(e.target.value)}
                  placeholder="j.smith@cro.example" />
              </div>
            </div>
            <p className="mut" style={{ fontSize: 12, margin: "6px 0 0" }}>
              Health Canada issues your Dossier ID when you file a Dossier ID
              Request through <Term k="REP" /> (via your <Term k="CESG" />{" "}
              account).{" "}
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
          <>
            {/* R7 triage bar — search + "just my dossiers" for multi-sponsor PMs */}
            <div style={{ display: "flex", gap: 12, alignItems: "center",
              flexWrap: "wrap", margin: "14px 0 4px" }}>
              <input value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="Filter by product, ID, type, client or owner…"
                aria-label="Filter dossiers"
                style={{ flex: "1 1 260px", maxWidth: 420 }} />
              {myEmail && (
                <label style={{ display: "flex", alignItems: "center", gap: 6,
                  fontSize: 13 }}>
                  <input type="checkbox" checked={mineOnly}
                    style={{ width: "auto" }}
                    onChange={(e) => setMineOnly(e.target.checked)} />
                  Just my dossiers
                </label>
              )}
              <span className="mut" style={{ fontSize: 12 }}>
                {rows.length} of {items.length}
              </span>
            </div>

            {rows.length === 0 ? (
              <div className="notice" style={{ marginTop: 12 }}>
                No dossiers match your filter.
              </div>
            ) : viewMode === "grid" ? (
              <div className="dossier-grid">
                {rows.map((d) => {
                  const passed = d.tower.filter((t) => t.state === "pass").length;
                  const applic = d.tower.filter((t) => t.state !== "na").length;
                  return (
                    <Link key={d.dossier_id} href={`/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`}
                      className="card glass dossier-tile">
                      <div className="d-id">
                        {d.dossier_id}
                        {d.dossier_id.startsWith("d") && (
                          <button className="chip placeholder-id" title="Placeholder ID — NOT a Health Canada Dossier ID. Export and transmission are blocked until you set the real ID (issued via REP)."
                            style={{ marginLeft: 8, fontSize: 11 }}
                            onClick={(e) => openRename(e, d.dossier_id)}>
                            ⚠ placeholder — set real ID ✎
                          </button>
                        )}
                      </div>
                      <div className="d-title">{d.title}</div>
                      <div className="d-meta mut">
                        {typeLabel(d)}
                        {d.sponsor ? ` · ${d.sponsor}` : ""}
                      </div>
                      <div className="progress"><i style={{
                        width: `${applic ? (passed / applic) * 100 : 0}%` }} /></div>
                      {/* WS1-c: completeness is NOT a filing verdict. Never render
                          "Ready to file" from module-completion — that green badge
                          must come from a real eCTD validation pass (in the builder/
                          journey), not this catalog roll-up. */}
                      <span className={`chip ${d.gate?.complete ? "" : "blocked"}`}
                        title={d.gate?.complete
                          ? "All required modules built — structural completeness only, NOT a validation pass. Open the module builder and run eCTD validation before filing."
                          : "Some required modules are not yet built"}>
                        {d.gate?.complete
                          ? `${passed}/${applic} modules built — validate to file`
                          : `${passed}/${applic} modules built`}
                      </span>
                      <button className="tile-delete" title={`Delete ${d.dossier_id}`}
                        aria-label={`Delete dossier ${d.dossier_id}`}
                        onClick={(e) => openDelete(e, d.dossier_id)}>✕</button>
                    </Link>
                  );
                })}
              </div>
            ) : (
              <div className="table-wrap" style={{ overflowX: "auto",
                marginTop: 8 }}>
                <table className="dossier-table">
                  <thead>
                    <tr>
                      {([
                        ["dossier_id", "Dossier ID"],
                        ["title", "Product"],
                        ["status", "Status"],
                        ["submission_type", "Type"],
                        ["sponsor", "Client / sponsor"],
                        ["owner", "Owner"],
                        ["soonest_due", "Soonest due"],
                      ] as [SortKey, string][]).map(([k, lbl]) => (
                        <th key={k}>
                          <button className="th-sort" onClick={() => toggleSort(k)}
                            aria-label={`Sort by ${lbl}`}>
                            {lbl}{sortArrow(k)}
                          </button>
                        </th>
                      ))}
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((d) => {
                      const passed = d.tower.filter((t) => t.state === "pass").length;
                      const applic = d.tower.filter((t) => t.state !== "na").length;
                      const dm = dueMeta(d.soonest_due);
                      return (
                        <tr key={d.dossier_id}
                          onClick={() => router.push(
                            `/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`)}
                          style={{ cursor: "pointer" }}>
                          <td style={{ fontFamily: "ui-monospace,monospace" }}>
                            {d.dossier_id}
                            {d.dossier_id.startsWith("d") && (
                              <span className="chip placeholder-id" style={{ marginLeft: 6,
                                fontSize: 10 }} title="Placeholder ID — NOT a Health Canada Dossier ID; export/transmission blocked until the real ID is set">⚠ placeholder</span>
                            )}
                          </td>
                          <td>{d.title}</td>
                          <td>
                            <span className={`chip ${d.gate?.complete ? "" : "blocked"}`}
                              title={d.gate?.complete
                                ? "Modules built (structural completeness) — not a validation pass; validate before filing"
                                : "Some required modules not yet built"}>
                              {d.gate?.complete ? `${passed}/${applic} built` : `${passed}/${applic}`}
                            </span>
                          </td>
                          <td>{typeLabel(d)}</td>
                          <td>{d.sponsor || <span className="mut">—</span>}</td>
                          <td>{d.owner || <span className="mut">—</span>}</td>
                          <td>
                            {dm ? (
                              <span className={dm.overdue ? "bad-text"
                                : dm.soon ? "warn-text" : "mut"}
                                title={dm.iso}>{dm.label}</span>
                            ) : <span className="mut">—</span>}
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <button className="tile-delete" style={{
                              position: "static", opacity: 1 }}
                              title={`Delete ${d.dossier_id}`}
                              aria-label={`Delete dossier ${d.dossier_id}`}
                              onClick={(e) => openDelete(e, d.dossier_id)}>✕</button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
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
        <SetRealDossierIdModal
          dossierId={renameTarget}
          seedCompany={renameSeedCompany}
          seedSponsor={renameSeedSponsor}
          onClose={() => setRenameTarget(null)}
          onRenamed={async () => {
            setRenameTarget(null);
            await load();
          }}
        />
      )}
    </>
  );
}

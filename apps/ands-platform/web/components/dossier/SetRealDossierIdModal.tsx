"use client";
// POLISH-ID-BEFORE-409: the shared "set the real Health Canada Dossier ID"
// modal — extracted from the dossiers list page so BOTH the catalog AND the
// builder chrome (DossierHeader placeholder banner) can open the same flow.
// It owns its own busy / error / REP-request state so callers only supply the
// target id + an onRenamed callback. Reuses the existing renameDossier +
// requestRepDossierId helpers.
//
// HONEST: the in-app REP Dossier-ID Request records the request intent +
// returns guidance — it does NOT transmit to Health Canada.
import { useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { RepRequest } from "@/lib/dossierTypes";
import { Term } from "@/components/Term";
import { Modal } from "@/components/Modal";
import { toast } from "sonner";

export function SetRealDossierIdModal({
  dossierId,
  seedCompany = "",
  seedSponsor = "",
  onClose,
  onRenamed,
}: {
  dossierId: string;
  seedCompany?: string;
  seedSponsor?: string;
  onClose: () => void;
  // called with the new (real) id after a successful rename
  onRenamed: (newId: string) => void | Promise<void>;
}) {
  const [renameNew, setRenameNew] = useState("");
  const [renameReason, setRenameReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // in-app REP Dossier-ID Request helper (prepared, not transmitted)
  const [repBusy, setRepBusy] = useState(false);
  const [repDone, setRepDone] = useState<RepRequest | null>(null);
  const [repCompany, setRepCompany] = useState(seedCompany);
  const [repSponsor, setRepSponsor] = useState(seedSponsor);

  // re-seed if the target changes while mounted
  useEffect(() => {
    setRepCompany(seedCompany);
    setRepSponsor(seedSponsor);
  }, [seedCompany, seedSponsor]);

  async function confirmRename() {
    const next = renameNew.trim().toLowerCase();
    if (!/^[a-z]\d{6,7}$/.test(next)) {
      setErr("Dossier ID must be one letter + 6–7 digits (e.g. e123456)");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await dossierApi.renameDossier(dossierId, next, renameReason.trim());
      toast.success(`Dossier ID set to ${next}`);
      await onRenamed(next);
    } catch (er) {
      setErr(String(er));
    } finally {
      setBusy(false);
    }
  }

  async function fileRepRequest() {
    setRepBusy(true);
    setErr("");
    try {
      const rr = await dossierApi.requestRepDossierId(dossierId, {
        company_id: repCompany.trim() || undefined,
        sponsor: repSponsor.trim() || undefined,
      });
      setRepDone(rr);
      toast.success("REP Dossier-ID Request prepared and recorded (not transmitted).");
    } catch (er) {
      setErr(String(er));
    } finally {
      setRepBusy(false);
    }
  }

  return (
    <Modal
      title="Set the real Health Canada Dossier ID"
      onClose={onClose}
      footer={
        <>
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button onClick={confirmRename} disabled={busy || !renameNew.trim()}>
            {busy ? "Applying…" : "Apply new ID"}
          </button>
        </>
      }
    >
      <p className="mut" style={{ fontSize: 13, marginTop: 0 }}>
        Re-key <b>{dossierId}</b> to the Dossier ID issued by Health Canada (one
        letter + 6–7 digits, e.g. <code>e123456</code>). All documents,
        sequences and history move with it, and export unblocks once a real ID
        is set (validation permitting). The before/after IDs and your reason are
        written to the audit trail.
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

      {/* file the REP Dossier-ID Request from inside the notice. HONEST — it
          records the request intent + returns guidance; it does NOT transmit to
          Health Canada. Shown for placeholder (d…) dossiers only. */}
      {dossierId.startsWith("d") && (
        <div className="notice" style={{ marginTop: 14, fontSize: 13 }}>
          <div style={{ fontWeight: 600 }}>
            Don&apos;t have a Dossier ID yet? Request one (REP)
          </div>
          <p className="mut" style={{ fontSize: 12, margin: "4px 0 8px" }}>
            Health Canada issues the Dossier ID through the Regulatory Enrolment
            Process (REP) via <Term k="CESG" />. ANDS Studio prepares and
            records the request here — it does <b>not</b> transmit to Health
            Canada. Once HC issues the ID, set it above.
          </p>
          {repDone ? (
            <div className="notice ok" style={{ fontSize: 12 }}>
              <div style={{ fontWeight: 600 }}>
                Request prepared and recorded (not transmitted).
              </div>
              <p className="mut" style={{ margin: "4px 0 6px" }}>
                {repDone.guidance.summary}
              </p>
              <ol style={{ margin: "0 0 0 16px", padding: 0 }}>
                {repDone.guidance.steps.map((s) => (
                  <li key={s} className="mut" style={{ marginTop: 2 }}>
                    {s}
                  </li>
                ))}
              </ol>
              <a
                href={repDone.guidance.url}
                target="_blank"
                rel="noreferrer"
                className="mut"
                style={{ display: "inline-block", marginTop: 6, fontSize: 12 }}
              >
                Health Canada — Regulatory Enrolment Process (REP) ↗
              </a>
            </div>
          ) : (
            <>
              <div className="field-row">
                <div>
                  <label style={{ fontSize: 12 }}>
                    Company ID{" "}
                    <span className="mut" style={{ fontWeight: 400 }}>
                      (optional)
                    </span>
                  </label>
                  <input
                    value={repCompany}
                    onChange={(e) => setRepCompany(e.target.value)}
                    placeholder="HC company identifier"
                    style={{ width: "100%", marginTop: 3 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 12 }}>
                    Sponsor{" "}
                    <span className="mut" style={{ fontWeight: 400 }}>
                      (optional)
                    </span>
                  </label>
                  <input
                    value={repSponsor}
                    onChange={(e) => setRepSponsor(e.target.value)}
                    placeholder="Acme Pharma Inc."
                    style={{ width: "100%", marginTop: 3 }}
                  />
                </div>
              </div>
              <button
                className="ghost"
                style={{ marginTop: 8, fontSize: 12 }}
                onClick={fileRepRequest}
                disabled={repBusy}
              >
                {repBusy ? "Preparing…" : "Prepare REP Dossier-ID Request →"}
              </button>
            </>
          )}
        </div>
      )}

      {err && (
        <div className="notice bad" style={{ marginTop: 10 }}>
          {err}
        </div>
      )}
    </Modal>
  );
}

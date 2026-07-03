"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dossierApi } from "@/lib/dossierApi";
import type { JourneyView, Stage } from "@/lib/types";
import { Term } from "./Term";
import { DrugIntake } from "./DrugIntake";
import { TrackView } from "./TrackView";

type AdvanceFn = (step: string, data?: Record<string, any>) => Promise<void>;

export function StepCard({
  stage,
  view,
  onAdvance,
  onView,
  busy,
}: {
  stage: Stage;
  view: JourneyView;
  onAdvance: AdvanceFn;
  onView: (v: JourneyView) => void;
  busy: boolean;
}) {
  const [form, setForm] = useState<Record<string, any>>({});
  const [localErr, setLocalErr] = useState("");
  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    setForm({});
    setLocalErr("");
  }, [stage.key]);

  async function go(data?: Record<string, any>) {
    setLocalErr("");
    try {
      // What the inputs DISPLAY must be what we submit: the submission step's
      // drug-product field pre-fills from journey signals, so an untouched
      // field still has a visible value the user expects to count.
      const sig = view.signals || {};
      const seeded =
        stage.key === "submission" && sig.drug_product
          ? { drug_product: sig.drug_product, ...form }
          : form;
      await onAdvance(stage.key, data ?? seeded);
    } catch (e) {
      setLocalErr(String(e));
    }
  }

  const cta = stage.cta || "Continue";
  const sig = view.signals || {};

  return (
    <div className="card glass stepcard">
      <div className="eyebrow">
        <span aria-hidden>{stage.icon}</span>
        Step {stage.n} of 10 {stage.reg ? `· ${stage.reg}` : ""}
      </div>
      <h2 className="step-title">{stage.label}</h2>
      <p className="lede">{stage.purpose}</p>

      {/* per-step teaching + fields */}
      {stage.key === "orient" && (
        <>
          <div className="teach">
            You&apos;re about to file an <Term k="ANDS" /> — the pathway for a
            generic copy of an approved Canadian brand drug. Instead of repeating
            the original trials, you&apos;ll prove your version is the
            &ldquo;same&rdquo;: pharmaceutically equivalent and{" "}
            <Term k="bioequivalence">bioequivalent</Term> to the{" "}
            <Term k="CRP">Canadian Reference Product</Term>. I&apos;ll walk you
            through every step, in the order Health Canada actually needs them.
          </div>
          <DrugIntake sessionId={view.id} initial={view.intake} />
        </>
      )}

      {stage.key === "company" && (
        <>
          <div className="teach">
            Health Canada assigns your company a 5-digit{" "}
            <Term k="Company ID" />. You need it before you can transmit — but
            nothing else waits on it. Don&apos;t have one? Enrol through the{" "}
            <Term k="REP" /> by sending a completed Company Template to the
            Office of Submission and Intellectual Property
            (hc.osip-bpip.sc@canada.ca); IDs are typically issued within a
            couple of weeks.
          </div>
          <label>Your Health Canada Company ID</label>
          <input
            value={form.company_id || ""}
            onChange={(e) => set("company_id", e.target.value)}
            placeholder="e.g. 12345"
            inputMode="numeric"
          />
          {/* WS6: a persistent open-risk flag, not a silent skip. Requesting
              while pending records the gap so it stays visible until the real
              5-digit ID is set — mirroring the placeholder Dossier-ID reminder
              the pre-filing validation raises. */}
          {sig.company_pending && !sig.company_id ? (
            <div className="notice warn" style={{ marginTop: 8 }}>
              ⚠ Open risk tracked: your Company ID is still <b>pending</b> with
              Health Canada. You can keep working, but you cannot transmit until
              the real 5-digit ID is set here — this reminder stays until then.
            </div>
          ) : (
            <button className="ghost" style={{ marginTop: 8, fontSize: 13 }}
              onClick={() => onAdvance(stage.key, { company_pending: true })}>
              I&apos;ve requested it — flag as an open risk & continue →
            </button>
          )}
        </>
      )}

      {stage.key === "dossier" && <DossierStep form={form} set={set} />}

      {stage.key === "submission" && (
        <>
          <div className="teach">
            Now we create the submission itself — your <Term k="ANDS" /> as
            sequence <b>0000</b>, the first envelope in your product&apos;s
            permanent <Term k="Dossier ID">dossier</Term>.
          </div>
          <div className="field-row">
            <div>
              <label>Applicant (your company name)</label>
              <input
                value={form.applicant || ""}
                onChange={(e) => set("applicant", e.target.value)}
                placeholder="Acme Pharma Inc."
              />
            </div>
            <div>
              <label>Drug product</label>
              <input
                value={form.drug_product ?? sig.drug_product ?? ""}
                onChange={(e) => set("drug_product", e.target.value)}
                placeholder="Drugazole 10 mg tablet"
              />
            </div>
          </div>
        </>
      )}

      {stage.key === "content" && (
        <>
          <div className="teach">
            Put the right document in the right slot. An <Term k="eCTD" /> has 5
            modules — only <Term k="Module 1" /> is Canada-specific (cover
            letter, forms, the bilingual Product Monograph). For an ANDS, Module 5
            holds your <Term k="bioequivalence">bioequivalence</Term> reports and
            Module 3 your <Term k="CMC" />. A misplaced document bounces the whole
            package — drag each document onto its slot and watch the tower fill.
          </div>
          <div className="cta-row">
            <a className="builder-link"
              href={`/dossiers/${encodeURIComponent(view.journey.dossier_id)}/m/1`}
              onClick={async (e) => {
                // register the dossier (idempotent) so the module builder and
                // Application Viewer have a real record + sequence 0000
                e.preventDefault();
                const did = view.journey.dossier_id;
                try {
                  await dossierApi.createDossier({
                    dossier_id: did,
                    title: sig.drug_product || form.drug_product || did,
                    cs_be_only: true,
                  });
                } catch { /* self-heal in DossierProvider covers failures */ }
                window.location.href = `/dossiers/${encodeURIComponent(did)}/m/1`;
              }}>
              Open the Module builder →
            </a>
            <span className="nexthint">
              Build Modules 1–5 — upload or author every document with guidance
            </span>
          </div>
          <div className="mut" style={{ fontSize: 13, marginTop: 10 }}>
            {view.content.gate?.complete
              ? "✓ All required documents are in — you can continue."
              : `${view.content.gate?.missing?.length || 0} required document(s) still needed across the modules.`}
          </div>
        </>
      )}

      {stage.key === "validate" && (
        <>
          <div className="teach">
            Health Canada re-validates everything on receipt, so we check first.
            Continuing runs the <b>full technical validation</b> on your
            assembled dossier — eCTD backbone, leaf checksums, and PDF
            conformance on the real bytes. Zero errors is the gate (warnings
            are allowed); anything wrong comes back as a plain-language list.
          </div>
          {sig.validation?.ran && (
            <div className={`notice ${sig.validation.errors ? "bad" : "ok"}`}>
              {sig.validation.errors
                ? `✗ ${sig.validation.errors} error(s) to fix`
                : `✓ Validation passed — ${sig.validation.checked ?? 0} document(s) checked, ${sig.validation.warnings ?? 0} warning(s).`}
              {sig.validation.real === false ? " (simulated)" : ""}
            </div>
          )}
        </>
      )}

      {stage.key === "fees" && (
        <>
          <div className="teach">
            We calculate your ANDS fee for the current fiscal year (it&apos;s
            re-indexed every April 1, so we always show the live figure — never a
            memorized number). If you qualify for{" "}
            <Term k="small business">small-business status</Term>, get it granted{" "}
            <b>before</b> you file — filing first forfeits the discount, and your
            first-ever submission is fully waived.
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              style={{ width: "auto" }}
              checked={!!form.sb_granted}
              onChange={(e) => set("sb_granted", e.target.checked)}
            />
            <span>My small-business status is already granted</span>
          </label>
          {form.sb_granted === false && (
            <div className="notice warn">
              ⚠ Not granted yet? Apply for small-business status before filing or
              you forfeit the 50% reduction / first-submission waiver.
            </div>
          )}
        </>
      )}

      {stage.key === "review" && (
        <>
          <div className="teach">
            Before it leaves your organization, the submission is routed for
            internal approval. An ANDS also needs the Sponsor Attestation
            Checklist — note it&apos;s requested from Health Canada by email, not
            on the public forms page, so don&apos;t discover it missing at
            screening.
          </div>
          {sig.reviews?.approved && (
            <div className="notice ok">
              ✓ QA review recorded{sig.reviews.real
                ? " in the governance audit trail" : ""} — reviewer:{" "}
              {sig.reviews.reviewer || "sponsor QA"}.
            </div>
          )}
        </>
      )}

      {stage.key === "sign" && (
        <>
          <div className="teach">
            An authorized person applies the regulated e-signature behind a QA
            gate, recorded with a tamper-evident audit trail (who signed, when).
            Signing unlocks transmission.
          </div>
          {sig.esign?.signed && (
            <div className="notice ok">
              ✓ Signed by {sig.esign.signer || "authorized signer"}
              {sig.esign.manifest_id
                ? ` — tamper-evident manifest ${String(sig.esign.manifest_id).slice(0, 10)}… over ${sig.esign.artifact_count} artifact(s).`
                : "."}
            </div>
          )}
        </>
      )}

      {stage.key === "transmit" && <TransmitStep sig={sig} />}

      {stage.key === "track" && (
        <>
          <TrackStep />
          <TrackView sessionId={view.id} />
        </>
      )}

      {(localErr || false) && <div className="notice bad">{localErr}</div>}

      {/* one primary CTA + a Next: pointer */}
      {stage.cta && (
        <div className="cta-row">
          <button
            onClick={() => go()}
            disabled={
              busy || (stage.key === "content" && !view.content.gate.complete)
            }
          >
            {busy ? "Working…" : `${cta} →`}
          </button>
          {stage.key === "content" && !view.content.gate.complete && (
            <span className="nexthint">
              Place the required documents to continue
            </span>
          )}
          {stage.next_label &&
            !(stage.key === "content" && !view.content.gate.complete) && (
              <span className="nexthint">
                Next: <b>{stage.next_label}</b>
              </span>
            )}
        </div>
      )}
    </div>
  );
}

function DossierStep({
  form,
  set,
}: {
  form: Record<string, any>;
  set: (k: string, v: any) => void;
}) {
  const [assess, setAssess] = useState<any>(null);
  async function check() {
    try {
      setAssess(
        await api.assessDossierId({
          dossier_id: form.dossier_id || "",
          branch: form.branch || "pharmaceutical",
        })
      );
    } catch {
      /* ignore */
    }
  }
  return (
    <>
      <div className="teach">
        Your <Term k="Dossier ID" /> is the permanent file number for this
        product (one letter + 6–7 digits, like <b>e123456</b>). You&apos;ll reuse
        it forever — every future change goes in the same folder. Request it at
        most 8 weeks before you file (a maximum, not a deadline).
      </div>
      <div className="field-row">
        <div>
          <label>Dossier ID</label>
          <input
            value={form.dossier_id || ""}
            onChange={(e) => set("dossier_id", e.target.value)}
            onBlur={check}
            placeholder="e123456"
          />
        </div>
        <div>
          <label>Product type</label>
          <select
            value={form.branch || "pharmaceutical"}
            onChange={(e) => set("branch", e.target.value)}
          >
            <option value="pharmaceutical">Pharmaceutical / biologic</option>
            <option value="veterinary">Veterinary</option>
            <option value="medical-device">Medical device</option>
            <option value="master-file-ectd">Master File (eCTD)</option>
          </select>
        </div>
      </div>
      {assess && assess.format_ok === false && (
        <div className="notice bad">{assess.format_error}</div>
      )}
      {assess && assess.format_ok === true && (
        <div className="notice ok">✓ Valid Dossier ID format.</div>
      )}
    </>
  );
}

function TransmitStep({ sig }: { sig: Record<string, any> }) {
  const tx = sig.transmission || {};
  const sent = !!sig.transmission;
  // real transmission records per-ack flags; the simulation implies all three
  const chain = [
    { k: "FDA MDN", termKey: "MDN",
      d: "First receipt: the FDA ESG confirms your transmission physically arrived at the shared gateway. This proves delivery, not acceptance. A Canadian ANDS gets an FDA-side receipt because CESG rides the shared FDA ESG infrastructure.",
      done: tx.real ? !!tx.mdn_received : sent },
    { k: "FDA ACK", termKey: "ACK",
      d: "Second receipt: the FDA ESG accepted the package for routing. Still an FDA-side receipt — legitimate, because Canada's CESG shares the FDA ESG. Don't stop here.",
      done: tx.real ? !!tx.fda_ack_received : sent },
    { k: "HC ACK (Core ID)", termKey: "Core ID",
      d: "Third and final receipt: Health Canada itself acknowledges your submission and issues the Core ID. This is the real proof Health Canada has it.",
      done: tx.real ? !!tx.hc_ack_received : sent },
  ];
  return (
    <>
      <div className="teach">
        You transmit through the{" "}
        <Term k="CESG">Common Electronic Submissions Gateway (CESG)</Term> —
        Health Canada&apos;s official channel for sending an <Term k="eCTD" />.
        CESG runs on the shared US <Term k="FDA-ESG" /> infrastructure, so you
        register once as an FDA ESG Trading Partner, install a certificate, and
        tag the package &ldquo;HC&rdquo; to route it to Health Canada. Over
        10&nbsp;GB goes on physical media; send one sequence at a time and wait
        for the acknowledgement before the next.
      </div>
      <div className="notice">
        Because CESG uses the shared FDA gateway, a Canadian ANDS legitimately
        produces <b>FDA-side receipts first</b>, then the Health Canada one. You
        get <b>three receipts, in order</b> — don&apos;t stop at the{" "}
        <Term k="ACK">FDA ACK</Term>. (Per Health Canada&apos;s CESG guidance,
        canada.ca.)
      </div>
      <div className="tiles" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        {chain.map((c) => (
          <div key={c.k} className={`tile ${c.done ? "pass" : "todo"}`} title={c.d}>
            <span className="d" aria-hidden>{c.done ? "✓" : "○"}</span>
            <span className="sr-only">
              {c.done ? "received" : "pending"}: {c.d}{" "}
            </span>
            <Term k={c.termKey}>{c.k}</Term>
          </div>
        ))}
      </div>
      {tx.real && tx.core_id && (
        <div className="notice ok">
          ✓ Transmitted for real through the transmission service — state{" "}
          <b>{tx.state}</b>, Core ID <b>{tx.core_id}</b>.
        </div>
      )}
    </>
  );
}

function TrackStep() {
  return (
    <div className="teach">
      Now Health Canada reviews. Screening (~45 days) is a completeness check —
      an <Term k="SDN" /> means &ldquo;something&apos;s missing, 45 days to send
      it&rdquo;. Then the science review (~180 days for an ANDS); a{" "}
      <Term k="clarifax" /> asks you to clarify data you already filed. The
      decisions: <Term k="NOC" /> (approved — you get a DIN), <Term k="NOD" />,
      or <Term k="NON" />. Remember the <Term k="clock">review clock</Term> counts
      only Health Canada&apos;s time and pauses while they wait on you.
    </div>
  );
}

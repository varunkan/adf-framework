"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { auth } from "@/lib/auth";
import { dossierApi } from "@/lib/dossierApi";
import type {
  ContentAuthors,
  EsignManifest,
  EsignVerification,
  EvalidatorAttestation,
} from "@/lib/dossierTypes";
import type { JourneyView, Stage } from "@/lib/types";
import { toast } from "sonner";
import {
  PenLine,
  ShieldCheck,
  ShieldAlert,
  FileCheck2,
  Users,
} from "lucide-react";
import { Term } from "./Term";
import { DrugIntake } from "./DrugIntake";
import { TrackView } from "./TrackView";
import { Disclosure } from "./Disclosure";

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

  // journey · J3 hard eValidator gate · when a real dossier exists, read its
  // recorded USER-ATTESTED external eValidator result so the transmit gate
  // can honor an attested PASS (and hard-stop on an attested FAIL).
  const [attestation, setAttestation] =
    useState<EvalidatorAttestation | null>(null);
  useEffect(() => {
    if (stage.key !== "transmit" || !view.journey.dossier_id) {
      setAttestation(null);
      return;
    }
    let live = true;
    dossierApi
      .getEvalidatorAttestation(view.journey.dossier_id)
      .then((r) => {
        if (live) setAttestation(r.attestation);
      })
      .catch(() => {
        if (live) setAttestation(null);
      });
    return () => {
      live = false;
    };
  }, [stage.key, view.journey.dossier_id]);
  const attPass = attestation?.result === "pass";
  const attFail = attestation?.result === "fail";
  // the filer's in-form attestation (fallback when no dossier record exists)
  const formAttested =
    !!form.evalidator_confirmed &&
    (form.evalidator_result ?? "pass") === "pass";
  const transmitGateOpen = attPass || (!attFail && formAttested);

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
          : // journey · J3 · a dossier-recorded attested PASS travels with the
            // advance too, so the gate holds even when the journey service
            // cannot reach the dossier service itself. Honest: this is the
            // filer's own recorded attestation, never a tool claim.
            stage.key === "transmit" && attPass
          ? {
              evalidator_confirmed: true,
              evalidator_result: "pass",
              validator_name: attestation?.validator_name || "",
              ...form,
            }
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
      {/* journey · J12/J8 · the step count derives from the live spine, never
          a hardcoded total (it drifted to "of 10" when stages changed). */}
      <div className="eyebrow">
        <span aria-hidden>{stage.icon}</span>
        Step {stage.n} of {view.journey.stages.length - 1}{" "}
        {stage.reg ? `· ${stage.reg}` : ""}
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

      {/* journey · J8 bilingual M1/PM stage · n=5 (round-9 BLOCKER,
          labelling_specialist): a NAMED, dedicated step — EN/FR parity,
          French translation review, mock-ups, PM XML validation — instead of
          a footnote inside document assembly. */}
      {stage.key === "bilingual" && (
        <>
          <div className="teach">
            For a generic manufacturer this is half the pain: the bilingual{" "}
            <Term k="Product Monograph" /> lives at <b>1.3.1</b> in{" "}
            <Term k="Module 1" /> and a missing EN <b>or</b> FR version is a{" "}
            <b>transmission blocker</b>. Confirm the EN + FR parity review
            (same content, both languages), the French translation review, and
            your PM/label mock-up review here. PM <b>XML validation</b> against
            Health Canada&apos;s schema runs in the dossier&apos;s Monograph
            panel.
          </div>
          {sig.bilingual?.confirmed ? (
            <div className="notice ok">
              ✓ Bilingual review recorded — EN/FR parity and French
              translation confirmed
              {sig.bilingual.reviewer ? ` by ${sig.bilingual.reviewer}` : ""}
              {sig.bilingual.pm_xml_validated ? " · PM XML validated" : ""}.
            </div>
          ) : (
            <div className="card" style={{ padding: 14, marginTop: 4 }}>
              <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={!!form.en_fr_parity}
                  onChange={(e) => set("en_fr_parity", e.target.checked)}
                />
                <span style={{ fontSize: 13 }}>
                  EN + FR Product Monograph parity reviewed — both languages
                  present and equivalent
                </span>
              </label>
              <label
                style={{ display: "flex", gap: 8, alignItems: "center",
                  marginTop: 8 }}
              >
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={!!form.translation_reviewed}
                  onChange={(e) => set("translation_reviewed", e.target.checked)}
                />
                <span style={{ fontSize: 13 }}>
                  French translation reviewed by a qualified reviewer
                </span>
              </label>
              <label
                style={{ display: "flex", gap: 8, alignItems: "center",
                  marginTop: 8 }}
              >
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={form.mockups_state === "reviewed"}
                  onChange={(e) =>
                    set("mockups_state", e.target.checked ? "reviewed" : "")
                  }
                />
                <span style={{ fontSize: 13 }}>
                  PM / label mock-ups reviewed (optional here — recorded)
                </span>
              </label>
              <label
                style={{ display: "flex", gap: 8, alignItems: "center",
                  marginTop: 8 }}
              >
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={!!form.pm_xml_validated}
                  onChange={(e) => set("pm_xml_validated", e.target.checked)}
                />
                <span style={{ fontSize: 13 }}>
                  PM XML validated against HC&apos;s schema (run it from the
                  Monograph panel)
                </span>
              </label>
              <label style={{ marginTop: 10 }}>
                Reviewer (who performed the bilingual review)
              </label>
              <input
                value={form.reviewer || ""}
                onChange={(e) => set("reviewer", e.target.value)}
                placeholder="e.g. M. Tremblay, Labelling"
              />
              {view.journey.dossier_id && (
                <div className="cta-row" style={{ marginTop: 10 }}>
                  <a
                    className="chip"
                    href={`/dossiers/${encodeURIComponent(view.journey.dossier_id)}/m/1`}
                  >
                    Open Module 1 / Monograph panel (files, EN/FR status, PM
                    XML validate) →
                  </a>
                </div>
              )}
              <div className="mut" style={{ fontSize: 11.5, marginTop: 8 }}>
                Honest scope: the mock-up <b>files</b> and the PM XML validate
                affordance live in the dossier builder&apos;s Monograph panel —
                this step records <b>your review</b> on the journey and its
                audit ledger.
              </div>
            </div>
          )}
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
          {/* journey · J16 reviewer read-only share (round-9 minor, n=2;
              ra_junior). HONEST SUBSET, limit stated in-UI: the link opens
              the read-only Application Viewer behind WORKSPACE sign-in —
              public tokenized share links are not built. */}
          {view.journey.dossier_id ? (
            <ReviewerShare dossierId={view.journey.dossier_id} />
          ) : (
            <div className="mut" style={{ fontSize: 12, marginTop: 10 }}>
              Share with your reviewer: once the submission exists, a
              read-only Application Viewer link appears here for your
              senior&apos;s sign-off review.
            </div>
          )}
        </>
      )}

      {stage.key === "sign" && (
        <EsignStep
          sig={sig}
          dossierId={view.journey.dossier_id}
          form={form}
          set={set}
          busy={busy}
          onSign={(d) => go(d)}
        />
      )}

      {stage.key === "transmit" && (
        <TransmitStep
          sig={sig}
          attestation={attestation}
          form={form}
          set={set}
        />
      )}

      {stage.key === "track" && (
        <>
          <TrackStep />
          <TrackView sessionId={view.id} />
        </>
      )}

      {(localErr || false) && <div className="notice bad">{localErr}</div>}

      {/* one primary CTA + a Next: pointer. The sign step owns its own primary
          action (the e-signature capture below), so we suppress the generic CTA
          button there and show only the Next pointer. */}
      {stage.cta && stage.key !== "sign" && (
        <div className="cta-row">
          <button
            onClick={() => go()}
            disabled={
              busy ||
              (stage.key === "content" && !view.content.gate.complete) ||
              // journey · J8 · the bilingual step needs both required reviews
              (stage.key === "bilingual" &&
                !sig.bilingual?.confirmed &&
                !(form.en_fr_parity && form.translation_reviewed)) ||
              // journey · J3 · HARD GATE: no transmit without a confirmed
              // eValidator run (dossier-attested pass, or attested here)
              (stage.key === "transmit" &&
                !sig.transmission &&
                !transmitGateOpen)
            }
          >
            {busy ? "Working…" : `${cta} →`}
          </button>
          {stage.key === "content" && !view.content.gate.complete && (
            <span className="nexthint">
              Place the required documents to continue
            </span>
          )}
          {stage.key === "bilingual" &&
            !sig.bilingual?.confirmed &&
            !(form.en_fr_parity && form.translation_reviewed) && (
              <span className="nexthint">
                Confirm the EN/FR parity and French translation reviews to
                continue
              </span>
            )}
          {stage.key === "transmit" &&
            !sig.transmission &&
            !transmitGateOpen && (
              <span className="nexthint">
                Hard gate: confirm your eValidator run above before
                transmitting
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
      {stage.key === "sign" && stage.next_label && sig.esign?.signed && (
        <div className="cta-row">
          <span className="nexthint">
            Next: <b>{stage.next_label}</b>
          </span>
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

// journey · J16 reviewer read-only share · a copyable workspace-auth link to
// the read-only Application Viewer, with the limit stated plainly.
function ReviewerShare({ dossierId }: { dossierId: string }) {
  const [copied, setCopied] = useState(false);
  const path = `/dossiers/${encodeURIComponent(dossierId)}/viewer`;
  return (
    <div className="card" style={{ padding: 12, marginTop: 12 }}>
      <div className="eyebrow" style={{ display: "flex", gap: 6,
        alignItems: "center" }}>
        <Users size={13} aria-hidden /> Share with your reviewer
      </div>
      <p className="mut" style={{ fontSize: 12, margin: "6px 0 8px" }}>
        Your senior reviews the assembled submission in the <b>read-only
        Application Viewer</b> (backbone, leaves, lifecycle — no edit
        affordances), then records the sign-off here.
      </p>
      <div className="cta-row">
        <a className="chip" href={path}>
          Open the read-only Application Viewer →
        </a>
        <button
          className="ghost"
          style={{ fontSize: 12 }}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(
                `${window.location.origin}${path}`);
              setCopied(true);
              setTimeout(() => setCopied(false), 2500);
            } catch {
              toast.error("Copy failed — copy the address from the viewer tab.");
            }
          }}
        >
          {copied ? "✓ Link copied" : "Copy reviewer link"}
        </button>
      </div>
      <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>
        Honest limit: the link requires <b>sign-in to this workspace</b> —
        public tokenized share links for external reviewers are not built.
      </div>
    </div>
  );
}

function TransmitStep({
  sig,
  attestation,
  form,
  set,
}: {
  sig: Record<string, any>;
  attestation: EvalidatorAttestation | null;
  form: Record<string, any>;
  set: (k: string, v: any) => void;
}) {
  const tx = sig.transmission || {};
  const sent = !!sig.transmission;
  const attPass = attestation?.result === "pass";
  const attFail = attestation?.result === "fail";
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
  const received = chain.filter((c) => c.done).length;
  return (
    <>
      <div className="teach">
        You transmit through the{" "}
        <Term k="CESG">Common Electronic Submissions Gateway (CESG)</Term> —
        Health Canada&apos;s official channel for sending an <Term k="eCTD" />.
        Send one sequence at a time and wait for the acknowledgement before the
        next.
      </div>

      {/* journey · J3 hard eValidator gate (round-9 BLOCKER, n=5): transmit
          is a HARD GATE on a confirmed eValidator run — enforced server-side
          (422 without it), mirrored here. Honesty: the result is always the
          FILER's attested run; ANDS Studio never claims to have run HC's
          eValidator. */}
      {!sent && (
        <div className="card" style={{ padding: 14, marginTop: 4 }}>
          <div className="eyebrow" style={{ display: "flex", gap: 6,
            alignItems: "center" }}>
            <ShieldCheck size={14} aria-hidden /> Hard gate: confirmed
            eValidator run
          </div>
          {attPass ? (
            <div className="notice ok" style={{ marginTop: 8 }}>
              ✓ eValidator run attested as <b>PASS</b>
              {attestation?.validator_name
                ? ` — ${attestation.validator_name}` : ""}
              {attestation?.validated_on
                ? ` (${attestation.validated_on})` : ""}
              . External, user-attested result recorded on the dossier — the
              gate is satisfied.
            </div>
          ) : attFail ? (
            <div className="notice bad" style={{ marginTop: 8 }}>
              ✗ Your attested eValidator run is recorded as <b>FAIL</b> —
              resolve the findings, re-export, re-run eValidator and re-attest
              on the validation surface before transmitting. Transmission is
              blocked until then.
            </div>
          ) : (
            <>
              <p className="mut" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
                No eValidator attestation is recorded yet. Run an eValidator on
                the <b>exported package</b>, then attest your result here — it
                is recorded as your attestation on the audit ledger.
              </p>
              <label style={{ marginTop: 10 }}>Validator you ran</label>
              <input
                value={form.validator_name || ""}
                onChange={(e) => set("validator_name", e.target.value)}
                placeholder="e.g. Lorenz eValidator, GlobalSubmit VALIDATE"
              />
              <label style={{ marginTop: 10 }}>Result</label>
              <select
                value={form.evalidator_result ?? "pass"}
                onChange={(e) => set("evalidator_result", e.target.value)}
              >
                <option value="pass">Pass — no errors against HC criteria</option>
                <option value="fail">Fail — findings remain</option>
              </select>
              <label style={{ display: "flex", gap: 8,
                alignItems: "flex-start", marginTop: 10 }}>
                <input
                  type="checkbox"
                  style={{ width: "auto", marginTop: 3 }}
                  checked={!!form.evalidator_confirmed}
                  onChange={(e) => set("evalidator_confirmed", e.target.checked)}
                />
                <span style={{ fontSize: 13 }}>
                  I confirm I ran an eValidator on the exported package and I
                  attest the result above. (Recorded as my attestation — not a
                  tool claim.)
                </span>
              </label>
              {(form.evalidator_result ?? "pass") === "fail" && (
                <div className="notice bad" style={{ marginTop: 8 }}>
                  A failed run blocks transmission — fix the findings,
                  re-export and re-run before attesting a pass.
                </div>
              )}
            </>
          )}
          {/* J3: where to get eValidator, whether it costs money, and what to
              do when it disagrees — stated plainly, no expander. */}
          <div className="mut" style={{ fontSize: 11.5, marginTop: 10,
            lineHeight: 1.5 }}>
            <b>Where &amp; cost:</b> Health Canada publishes the eCTD{" "}
            <b>validation criteria free on canada.ca</b>, but ships no free
            desktop eValidator — the commonly used validators (e.g. Lorenz
            eValidator) are <b>commercially licensed</b> (your publisher or
            CRO usually holds a licence). <b>If eValidator disagrees</b> with
            ANDS Studio&apos;s readiness verdict, trust eValidator: fix the
            findings, re-export, re-run.
          </div>
        </div>
      )}

      {/* journey · J23 accountability on HC rejection (round-9 OPEN, n=1;
          startup_founder): plain copy on WHO is accountable and what record
          exists if Health Canada rejects or screens out the filing. */}
      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div className="eyebrow">If Health Canada rejects or screens out</div>
        <p className="mut" style={{ fontSize: 12, margin: "6px 0 0",
          lineHeight: 1.55 }}>
          Health Canada can screen out or reject a submission (e.g. an{" "}
          <Term k="SDN" />, refusal at screening, or a negative decision) even
          after every in-app check passes — our checks are structural, and
          acceptance is always HC&apos;s call. <b>Accountability for the
          filing&apos;s content sits with you, the sponsor</b>: ANDS Studio
          prepares, checks and records the package but does not assume
          regulatory responsibility for HC&apos;s decision. If it happens, you
          hold the full record to respond: the three transmission receipts,
          the append-only Part-11 audit ledger, the validation reports and the
          signed e-signature manifest.
        </p>
      </div>
      {/* Round-6 WS-A: one primary thing — the receipt progress — with the
          CESG detail + the three receipt tiles collapsed behind an expander.
          Nothing is hidden; the summary shows the live count and the toggle. */}
      <Disclosure
        showLabel="Show the three receipts"
        hideLabel="Hide the three receipts"
        summary={
          <>
            <b>Transmission receipts: {received} of 3 received</b> — you get
            three, in order (two FDA-side, then Health Canada&apos;s). Don&apos;t
            stop at the <Term k="ACK">FDA ACK</Term>.
          </>
        }
      >
        <div className="notice">
          Because CESG uses the shared FDA gateway, a Canadian ANDS legitimately
          produces <b>FDA-side receipts first</b>, then the Health Canada one.
          CESG runs on the shared US <Term k="FDA-ESG" /> infrastructure — you
          register once as an FDA ESG Trading Partner, install a certificate, and
          tag the package &ldquo;HC&rdquo;. Over 10&nbsp;GB goes on physical
          media. (Per Health Canada&apos;s CESG guidance, canada.ca.)
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
      </Disclosure>
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
    <>
      <div className="teach">
        Now Health Canada reviews. Screening (~45 days) is a completeness check —
        an <Term k="SDN" /> means &ldquo;something&apos;s missing, 45 days to send
        it&rdquo;. Then the science review (~180 days for an ANDS); a{" "}
        <Term k="clarifax" /> asks you to clarify data you already filed. The
        decisions: <Term k="NOC" /> (approved — you get a DIN), <Term k="NOD" />,
        or <Term k="NON" />. Remember the <Term k="clock">review clock</Term> counts
        only Health Canada&apos;s time and pauses while they wait on you.
      </div>
      {/* journey · J23 · the accountability statement travels to the tracking
          step too — deficiencies land here, and the answer to "who's
          accountable?" should be one glance away. */}
      <p className="mut" style={{ fontSize: 12, margin: "8px 0 0" }}>
        If HC screens out or rejects: accountability for the filing sits with
        you, the sponsor — ANDS Studio holds the reconstructable record
        (receipts, Part-11 ledger, validation reports, signed manifest), and
        the response paths below walk each notice.
      </p>
    </>
  );
}

// ADOPT-PART11-ESIGN: a REAL 21 CFR Part 11-aligned e-signature, demonstrated —
// capture (signer identity + meaning + explicit REASON + attest), then the
// signed manifest (signer, UTC, reason, tamper-evident hash, leaf count) and a
// live "verify signature" affordance that re-checks the checksummed leaves.
// Honesty: this is Part-11-ALIGNED and verifiable — NOT an external
// certification / eValidator claim.
function fmtWhen(at?: string): string {
  if (!at) return "";
  const d = new Date(at);
  return isNaN(d.getTime()) ? at : d.toISOString().replace(".000", "");
}

// TIER2-ROLE-SEP: a plain-language segregation-of-duties notice on the sign
// step. It shows WHO authored the content vs WHO is about to sign, and WARNS
// when they are the same identity — a Part-11 signature is most defensible when
// the signer is a DISTINCT authorized approver from the author(s). Honesty:
// this compares recorded author/signer identities; it is NOT an SSO/IdP claim.
function SegregationOfDutiesNotice({
  authors,
  authorshipKnown,
  conflicting,
  conflict,
  signer,
  enforced,
}: {
  authors: string[];
  authorshipKnown: boolean;
  conflicting: string[];
  conflict: boolean;
  signer: string;
  // TIER3-SOD-ENFORCE: does this workspace ENFORCE separation? When it does, a
  // conflict is a hard block, not merely advisory.
  enforced: boolean;
}) {
  const tone = conflict ? "warn" : authorshipKnown ? "ok" : "mut";
  const bg =
    tone === "warn" ? "#fff7ed" : tone === "ok" ? "#f0fdf4" : "transparent";
  const border =
    tone === "warn" ? "#fdba74" : tone === "ok" ? "#bbf7d0" : "var(--line)";
  const Icon = conflict ? ShieldAlert : authorshipKnown ? ShieldCheck : Users;
  const iconColor = conflict ? "#c2410c" : authorshipKnown ? "#16a34a" : "#64748b";
  return (
    <div
      className="card"
      style={{
        padding: 12,
        marginTop: 12,
        background: bg,
        borderColor: border,
      }}
    >
      <div
        className="eyebrow"
        style={{ display: "flex", gap: 6, alignItems: "center" }}
      >
        <Icon size={14} aria-hidden color={iconColor} /> Segregation of duties
        <span
          className={enforced ? "chip ready" : "chip"}
          style={{ fontSize: 10, marginLeft: "auto" }}
        >
          {enforced ? "Enforced by workspace" : "Advisory"}
        </span>
      </div>
      <div style={{ fontSize: 13, marginTop: 6 }}>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr",
          gap: "2px 10px" }}>
          <span className="mut">Author(s)</span>
          <span>
            {authorshipKnown ? (
              authors.map((a, i) => (
                <b
                  key={a}
                  style={{
                    color:
                      conflicting.some(
                        (c) => c.trim().toLowerCase() === a.trim().toLowerCase()
                      )
                        ? "#c2410c"
                        : undefined,
                  }}
                >
                  {a}
                  {i < authors.length - 1 ? ", " : ""}
                </b>
              ))
            ) : (
              <span className="mut">not recorded</span>
            )}
          </span>
          <span className="mut">Signer</span>
          <span>
            <b style={{ color: conflict ? "#c2410c" : undefined }}>
              {signer.trim() || "—"}
            </b>
          </span>
        </div>
      </div>
      {conflict && enforced ? (
        <div style={{ fontSize: 12.5, marginTop: 8, color: "#9a3412" }}>
          <b>
            Blocked — the signer is also an author of this content.
          </b>{" "}
          Your workspace <b>enforces segregation of duties</b>: this signature
          cannot be applied. A <b>distinct authorized approver</b> (not one of
          the author(s)) must sign, so the approval is an independent check. The
          block is enforced server-side and recorded on the Part-11 audit trail.
        </div>
      ) : conflict ? (
        <div style={{ fontSize: 12.5, marginTop: 8, color: "#9a3412" }}>
          <b>Heads up — the signer is also an author of this content.</b> A 21
          CFR Part 11 e-signature is most defensible when the person who
          approves/authorizes is a <b>distinct authorized approver</b> from the
          author(s), so the approval is an independent check
          (segregation&nbsp;of&nbsp;duties). You can still sign — the outcome is
          recorded on the Part-11 manifest and audit trail — but a distinct
          approver is stronger. If your workspace enforces separation, this
          signature will be blocked.
        </div>
      ) : authorshipKnown ? (
        <div className="mut" style={{ fontSize: 12, marginTop: 8 }}>
          The signer is distinct from the recorded author(s) — segregation of
          duties is satisfied. This outcome is recorded on the Part-11 manifest.
        </div>
      ) : (
        <div className="mut" style={{ fontSize: 12, marginTop: 8 }}>
          No author identity is recorded for this content, so separation of
          duties can&apos;t be proven from the record. The signer/author
          comparison is recorded either way.
        </div>
      )}
      <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>
        This compares the recorded author &amp; signer identities. It is a
        role-separation check — not a single-sign-on / identity-provider
        verification.
      </div>
    </div>
  );
}

function EsignStep({
  sig,
  dossierId,
  form,
  set,
  busy,
  onSign,
}: {
  sig: Record<string, any>;
  dossierId: string;
  form: Record<string, any>;
  set: (k: string, v: any) => void;
  busy: boolean;
  onSign: (data: Record<string, any>) => Promise<void>;
}) {
  const signed = !!sig.esign?.signed;
  const suggestedSigner = sig.applicant || sig.esign?.signer || "";
  const signer = form.signer ?? suggestedSigner;
  const reason = form.reason ?? "";
  const meaning = form.meaning ?? "approved";
  const attested = !!form.attest;

  // the durable signed manifest (full detail: hash, leaves, UTC) — loaded once
  // the signature exists so the panel shows the REAL recorded record.
  const [manifest, setManifest] = useState<EsignManifest | null>(null);
  useEffect(() => {
    if (!signed || !dossierId) return;
    dossierApi
      .getEsign(dossierId)
      .then((r) => setManifest(r.manifest))
      .catch(() => setManifest(null));
  }, [signed, dossierId]);

  // TIER2-ROLE-SEP: the recorded author(s) of the content being signed, so the
  // sign step can show signer vs author(s) and WARN when they are the same
  // identity (a segregation-of-duties conflict). Loaded before signing.
  const [authors, setAuthors] = useState<ContentAuthors | null>(null);
  useEffect(() => {
    if (signed || !dossierId) return;
    dossierApi
      .contentAuthors(dossierId)
      .then(setAuthors)
      .catch(() => setAuthors(null));
  }, [signed, dossierId]);
  // TIER3-SOD-ENFORCE: does THIS workspace enforce segregation of duties? When
  // it does, a signer-is-author conflict is a HARD BLOCK (the server rejects the
  // signature) — so the sign button is disabled and the notice says "blocked",
  // not "heads up". Best-effort: if the policy read fails we fall back to
  // advisory (the server remains the authority either way).
  const [enforceSod, setEnforceSod] = useState(false);
  useEffect(() => {
    if (signed) return;
    auth
      .tenantSecurity()
      .then((s) => setEnforceSod(!!s.require_sod))
      .catch(() => setEnforceSod(false));
  }, [signed]);
  // same-identity comparison mirrors the server: case/whitespace-insensitive.
  const norm = (s: string) => (s || "").trim().toLowerCase();
  const authorList = authors?.authors ?? [];
  const conflicting = authorList.filter((a) => norm(a) === norm(signer));
  const sodConflict = !!signer.trim() && conflicting.length > 0;
  const authorshipKnown = authorList.length > 0;

  const meanings: { k: string; label: string }[] = [
    { k: "approved", label: "Approved — I approve this package" },
    { k: "reviewed", label: "Reviewed — I have reviewed this package" },
    { k: "authored", label: "Authored — I am the author of this content" },
    { k: "authorized", label: "Authorized — I authorize its transmission" },
  ];

  return (
    <>
      <div className="teach">
        An authorized person applies the regulated e-signature behind a QA gate.
        This is a real <b>21 CFR Part 11-aligned</b> e-signature: it records your
        identity, a UTC timestamp, the <b>meaning</b> of the signing, and a{" "}
        <b>tamper-evident hash</b> bound over every checksummed{" "}
        <Term k="eCTD" /> leaf — written immutably to the audit trail. Signing
        unlocks transmission.
      </div>

      {!signed && (
        <div className="card" style={{ padding: 14, marginTop: 4 }}>
          <div className="eyebrow" style={{ display: "flex", gap: 6,
            alignItems: "center" }}>
            <PenLine size={14} aria-hidden /> E-signature capture
          </div>
          <label style={{ marginTop: 8 }}>Signer (your name / identity)</label>
          <input
            value={signer}
            onChange={(e) => set("signer", e.target.value)}
            placeholder="e.g. Dr. Vera Signer, VP Regulatory Affairs"
          />
          <label style={{ marginTop: 10 }}>Meaning of signature</label>
          <select
            value={meaning}
            onChange={(e) => set("meaning", e.target.value)}
          >
            {meanings.map((m) => (
              <option key={m.k} value={m.k}>
                {m.label}
              </option>
            ))}
          </select>
          <label style={{ marginTop: 10 }}>
            Reason for signing (your attestation, in your words)
          </label>
          <textarea
            value={reason}
            rows={2}
            onChange={(e) => set("reason", e.target.value)}
            placeholder="I attest this ANDS is complete, reviewed, and authorized to transmit to Health Canada."
          />

          <SegregationOfDutiesNotice
            authors={authorList}
            authorshipKnown={authorshipKnown}
            conflicting={conflicting}
            conflict={sodConflict}
            signer={signer}
            enforced={enforceSod}
          />

          <label
            style={{ display: "flex", gap: 8, alignItems: "flex-start",
              marginTop: 10 }}
          >
            <input
              type="checkbox"
              style={{ width: "auto", marginTop: 3 }}
              checked={attested}
              onChange={(e) => set("attest", e.target.checked)}
            />
            <span style={{ fontSize: 13 }}>
              I understand that applying my electronic signature is the legal
              equivalent of my handwritten signature, that it carries the meaning
              above, and that it is recorded immutably with my identity and a UTC
              timestamp.
            </span>
          </label>
          <div className="mut" style={{ fontSize: 11.5, marginTop: 8 }}>
            Part-11 <b>aligned</b> and verifiable — immutable, meaning-bearing,
            re-checkable. ANDS Studio does not claim external certification.
          </div>
          <div className="cta-row" style={{ marginTop: 12 }}>
            <button
              onClick={() =>
                onSign({ signer: signer.trim(), reason: reason.trim(), meaning })
              }
              disabled={
                busy ||
                !signer.trim() ||
                !reason.trim() ||
                !attested ||
                (enforceSod && sodConflict)
              }
            >
              {busy ? "Signing…" : "Apply e-signature →"}
            </button>
            {/* TIER3-SOD-ENFORCE: when the workspace enforces separation, a
                signer-is-author conflict is a hard block — the server rejects it
                too, so we disable the button and say so up front. */}
            {enforceSod && sodConflict ? (
              <span className="nexthint">
                Blocked by workspace policy: a distinct authorized approver
                (not an author) must sign
              </span>
            ) : (!signer.trim() || !reason.trim() || !attested) ? (
              <span className="nexthint">
                Enter your name, a reason, and confirm the attestation to sign
              </span>
            ) : null}
          </div>
        </div>
      )}

      {signed && (
        <SignedManifestPanel
          sig={sig}
          dossierId={dossierId}
          manifest={manifest}
        />
      )}
    </>
  );
}

function SignedManifestPanel({
  sig,
  dossierId,
  manifest,
}: {
  sig: Record<string, any>;
  dossierId: string;
  manifest: EsignManifest | null;
}) {
  const [verify, setVerify] = useState<EsignVerification | null>(null);
  const [verifying, setVerifying] = useState(false);

  const signer = manifest?.signer || sig.esign?.signer || "authorized signer";
  const at = manifest?.at || sig.esign?.signed_at;
  const reason = manifest?.reason || sig.esign?.reason;
  const meaning = manifest?.meaning || sig.esign?.meaning;
  const hash = manifest?.manifest_id || sig.esign?.manifest_id;
  const leafCount =
    manifest?.leaf_count ?? sig.esign?.leaf_count ?? sig.esign?.artifact_count;

  async function runVerify() {
    if (!dossierId) return;
    setVerifying(true);
    try {
      const r = await dossierApi.verifyEsign(dossierId);
      setVerify(r);
      if (r.tampered) {
        toast.error("Signature invalidated — signed content changed.");
      } else if (r.verified) {
        toast.success("Signature verified — no signed leaf has changed.");
      }
    } catch (e) {
      toast.error(String((e as Error)?.message || e));
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="card" style={{ padding: 14, marginTop: 4 }}>
      <div
        className="eyebrow"
        style={{ display: "flex", gap: 6, alignItems: "center" }}
      >
        <FileCheck2 size={14} aria-hidden /> Signed e-signature manifest
      </div>
      <dl className="kv" style={{ margin: "8px 0 0", display: "grid",
        gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontSize: 13 }}>
        <dt className="mut">Signer</dt>
        <dd style={{ margin: 0 }}><b>{signer}</b></dd>
        <dt className="mut">Signed (UTC)</dt>
        <dd style={{ margin: 0 }}>{fmtWhen(at) || "—"}</dd>
        <dt className="mut">Meaning</dt>
        <dd style={{ margin: 0 }}>{meaning || "approved"}</dd>
        <dt className="mut">Reason</dt>
        <dd style={{ margin: 0 }}>{reason || "—"}</dd>
        <dt className="mut">Manifest hash</dt>
        <dd style={{ margin: 0, fontFamily: "monospace", wordBreak: "break-all" }}>
          {hash || "—"}
        </dd>
        <dt className="mut">Leaves signed</dt>
        <dd style={{ margin: 0 }}>
          {leafCount ?? 0} checksummed leaf
          {(leafCount ?? 0) === 1 ? "" : "s"}
        </dd>
        {manifest?.segregation_of_duties && (
          <>
            <dt className="mut">Segregation of duties</dt>
            <dd style={{ margin: 0 }}>
              {manifest.segregation_of_duties.conflict ? (
                <span style={{ color: "#c2410c" }}>
                  <b>Signer is also an author</b>
                  {manifest.segregation_of_duties.conflicting_authors.length
                    ? ` (${manifest.segregation_of_duties.conflicting_authors.join(
                        ", "
                      )})`
                    : ""}{" "}
                  — recorded on the manifest
                </span>
              ) : manifest.segregation_of_duties.authorship_known ? (
                <span style={{ color: "#16a34a" }}>
                  <b>Separated</b> — signer distinct from author(s)
                </span>
              ) : (
                <span className="mut">
                  Author not recorded — separation not provable
                </span>
              )}
            </dd>
          </>
        )}
      </dl>

      <div className="mut" style={{ fontSize: 11.5, marginTop: 10 }}>
        This signature and the immutable audit event (who / what / when / why)
        are recorded on the dossier&apos;s durable{" "}
        <a href={`/dossiers/${encodeURIComponent(dossierId)}/audit`}>
          Part-11 audit trail
        </a>
        . The hash binds the exact leaf set above — any later change to a signed
        leaf is detectable below.
      </div>

      <div className="cta-row" style={{ marginTop: 12 }}>
        <button className="ghost" onClick={runVerify} disabled={verifying}>
          {verifying ? "Verifying…" : "Verify signature"}
        </button>
      </div>

      {verify && verify.signed && !verify.tampered && (
        <div
          className="notice ok"
          style={{ marginTop: 10, display: "flex", gap: 8,
            alignItems: "flex-start" }}
        >
          <ShieldCheck size={16} aria-hidden style={{ marginTop: 1 }} />
          <span>
            Signature verified. All {verify.leaf_count} signed leaf
            {(verify.leaf_count ?? 0) === 1 ? "" : "s"} still match the
            checksums bound at signing — the package is unmodified since{" "}
            {signer} signed.
          </span>
        </div>
      )}
      {verify && verify.tampered && (
        <div
          className="notice bad"
          style={{ marginTop: 10, display: "flex", gap: 8,
            alignItems: "flex-start" }}
        >
          <ShieldAlert size={16} aria-hidden style={{ marginTop: 1 }} />
          <div>
            <b>Signature invalidated.</b> A signed leaf changed after signing:
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {verify.findings.map((f, i) => (
                <li key={i}>{f.message}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

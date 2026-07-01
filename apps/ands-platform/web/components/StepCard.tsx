"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { JourneyView, Stage } from "@/lib/types";
import { Term } from "./Term";
import { DrugIntake } from "./DrugIntake";
import { ContentSlots } from "./ContentSlots";
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
      await onAdvance(stage.key, data ?? form);
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
            <Term k="Company ID" />. You need it before you can transmit. If you
            don&apos;t have one yet, request it from the Office of Submission and
            Intellectual Property.
          </div>
          <label>Your Health Canada Company ID</label>
          <input
            value={form.company_id || ""}
            onChange={(e) => set("company_id", e.target.value)}
            placeholder="e.g. 12345"
            inputMode="numeric"
          />
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
          <ContentSlots
            sessionId={view.id}
            content={view.content}
            onUpdate={onView}
          />
        </>
      )}

      {stage.key === "validate" && (
        <>
          <div className="teach">
            Health Canada re-validates everything on receipt, so we check first.
            Zero errors is the gate (warnings are allowed). If anything&apos;s
            wrong, you get a plain-language list of how to fix it.
          </div>
          <label>Validation errors found (simulated for this walk)</label>
          <input
            type="number"
            min={0}
            value={form.errors ?? 0}
            onChange={(e) => set("errors", Number(e.target.value))}
          />
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
        <div className="teach">
          Before it leaves your organization, the submission is routed for
          internal approval. An ANDS also needs the Sponsor Attestation
          Checklist — note it&apos;s requested from Health Canada by email, not
          on the public forms page, so don&apos;t discover it missing at
          screening.
        </div>
      )}

      {stage.key === "sign" && (
        <div className="teach">
          An authorized person applies the regulated e-signature behind a QA
          gate, recorded with a tamper-evident audit trail (who signed, when).
          Signing unlocks transmission.
        </div>
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
  const sent = !!sig.transmission;
  const chain = [
    { k: "FDA MDN", d: "FDA gateway received your message" },
    { k: "FDA ACK", d: "FDA gateway accepted it" },
    { k: "HC ACK (Core ID)", d: "Health Canada actually has it — this is the proof" },
  ];
  return (
    <>
      <div className="teach">
        Health Canada has no portal of its own. Transmission rides on the US{" "}
        <Term k="FDA-ESG" /> gateway (<Term k="CESG" />): you register as an FDA
        ESG Trading Partner, install a certificate, and tag the package
        &ldquo;HC&rdquo;. Over 10&nbsp;GB goes on physical media; send one
        sequence at a time and wait for the acknowledgement before the next.
      </div>
      <div className="notice">
        You get <b>three receipts, in order</b> — don&apos;t stop at the FDA ACK:
      </div>
      <div className="tiles" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        {chain.map((c, i) => {
          const done = sent && i < 3;
          return (
            <div key={c.k} className={`tile ${done ? "pass" : "todo"}`} title={c.d}>
              <span className="d" aria-hidden>{done ? "✓" : "○"}</span>
              <span className="sr-only">{done ? "received" : "pending"}: </span>
              {c.k}
            </div>
          );
        })}
      </div>
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

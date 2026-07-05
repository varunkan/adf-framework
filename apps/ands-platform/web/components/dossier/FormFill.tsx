"use client";
// FORMS-WEB: the dynamic, schema-driven form that makes EVERY eCTD content
// section form-fillable — not just upload. Given a section's declarative form
// schema (fetched from /section-form-schema/{section}), it renders each field
// by its type, offers a per-PROSE-field "Draft with AI" affordance (the same
// honest AI path as chat drafting), pre-fills the dossier's known facts + a
// worked example, and generates the document into the section's eCTD leaf via
// the existing generate/author flow (which then shows the provenance chip +
// "not yet filable — review required" gate on the saved-doc card).
//
// HONEST: a per-field AI draft is a DRAFT the filer must review; a worked
// example left in place keeps the section blocked (the server re-derives it).
import { useEffect, useRef, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { FormField, FormSchema, SectionNode } from "@/lib/dossierTypes";
import { Sparkles, AlertTriangle, HelpCircle } from "lucide-react";
import { opMeta } from "@/lib/leafStatus";
import { ReviewPanel } from "./ReviewPanel";

// Fields the dossier context pre-fills as the filer's OWN facts (never a worked
// example) — these render as plain editable values, not ghost placeholders.
const FACT_KEYS = new Set([
  "drug_product",
  "dossier_id",
  "company_id",
  "sponsor",
  "din",
  "sequence",
  "activity_type",
]);

export function FormFill({
  node,
  op,
  dossierId,
  onDone,
  onError,
}: {
  node: SectionNode;
  op?: string;
  dossierId: string;
  onDone: (c: any, msg: string) => void;
  onError: (e: string) => void;
}) {
  const [schema, setSchema] = useState<FormSchema | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  // worked-example ghosts: shown as greyed placeholders on empty sample fields,
  // never saved as the filer's content (the server re-derives + blocks them).
  const [ghosts, setGhosts] = useState<Record<string, string>>({});
  const [sampleKeys, setSampleKeys] = useState<Set<string>>(new Set());
  const [review, setReview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  // which prose field is currently streaming an AI draft (name) — one at a time
  const [drafting, setDrafting] = useState<string>("");

  const set = (k: string, v: string) =>
    setFields((f) => ({ ...f, [k]: v }));

  // Fetch the declarative schema AND the realistic pre-fill together. Real
  // dossier facts become editable values; each worked-example (sample) key
  // becomes a GHOST placeholder on an empty field so it is not saved content.
  useEffect(() => {
    let live = true;
    setSchema(null);
    setLoadErr("");
    setReview(null);
    Promise.all([
      dossierApi.sectionFormSchema(node.section),
      dossierApi.formSample(dossierId, node.section).catch(() => null),
    ])
      .then(([s, sample]) => {
        if (!live) return;
        setSchema(s.schema);
        const sk = new Set<string>(sample?.sample_keys || []);
        const all = sample?.fields || {};
        const real: Record<string, string> = {};
        const ghost: Record<string, string> = {};
        for (const [k, v] of Object.entries(all)) {
          if (sk.has(k)) ghost[k] = v as string; // worked example → ghost
          else real[k] = v as string; // dossier's own fact → editable value
        }
        setFields(real);
        setGhosts(ghost);
        setSampleKeys(sk);
      })
      .catch((e) => {
        if (!live) return;
        setLoadErr(String(e));
      });
    return () => {
      live = false;
    };
  }, [dossierId, node.section]);

  // Any sample-key field left blank falls back to its ghost example on generate.
  // Whether the fill still carries worked-example values is decided SERVER-SIDE
  // (it re-derives which fields equal the example and blocks until confirmed) —
  // the client does not send, and the server does not trust, a sample-origin
  // flag. So an unreplaced example is always caught.
  function filledFields(): Record<string, string> {
    const merged: Record<string, string> = { ...fields };
    for (const k of sampleKeys) {
      if (!((merged[k] || "").trim()) && ghosts[k]) merged[k] = ghosts[k];
    }
    return merged;
  }

  // The generate payload: the flat field map (bespoke generators read flat ctx
  // keys) PLUS a `form` map (the universal "structured" generator reads
  // ctx["form"]). Sending both keeps every generator_key working uniformly.
  function payload(): Record<string, any> {
    const f = filledFields();
    return { ...f, form: f };
  }

  async function runReview(): Promise<boolean> {
    try {
      const r = await dossierApi.formReview(dossierId, node.section, filledFields());
      setReview(r);
      return r.passed;
    } catch (e) {
      onError(String(e));
      return false;
    }
  }

  async function generate() {
    setBusy(true);
    try {
      const c = await dossierApi.generate(dossierId, node.section, payload());
      onDone(
        c,
        `${schema?.title || node.title} authored — review it against the ` +
          "Health Canada guidance and confirm it as your content before filing."
      );
      await runReview(); // surface the HC content review right after authoring
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Stream an AI draft into ONE prose field (the same honest AI path as chat
  // drafting). Replaces the field's value token-by-token as it arrives.
  async function draftField(name: string) {
    setDrafting(name);
    set(name, "");
    try {
      let acc = "";
      for await (const chunk of dossierApi.streamDraftField(
        dossierId,
        node.section,
        name
      )) {
        if (chunk.error) {
          onError(chunk.error);
          break;
        }
        if (chunk.delta) {
          acc += chunk.delta;
          set(name, acc);
        }
      }
    } catch (e) {
      onError(String(e));
    } finally {
      setDrafting("");
    }
  }

  if (loadErr)
    return (
      <div className="notice bad" role="alert" style={{ marginTop: 10 }}>
        Could not load this section&apos;s form — {loadErr}
      </div>
    );
  if (!schema)
    return (
      <div className="mut" style={{ fontSize: 13, marginTop: 10 }}>
        Loading the form…
      </div>
    );

  // The still-unreplaced worked-example fields — flag each inline + warn before
  // authoring so the greyed placeholder cannot be silently filed.
  const unreplaced = [...sampleKeys].filter((k) => !((fields[k] || "").trim()));
  const unreplacedLabels = unreplaced.map(
    (k) => schema.fields.find((f) => f.name === k)?.label || k
  );

  return (
    <div className="author-form form-fill">
      <p className="mut" style={{ fontSize: 13 }}>
        <b>Fill the form</b> to produce a PDF/A leaf placed at this section&apos;s
        eCTD position (lifecycle operation:{" "}
        <i>{opMeta(op)?.word ?? "new leaf"}</i>). Your dossier&apos;s known facts
        are pre-filled. Free-text fields carry a{" "}
        <b>Draft with AI</b> button — the draft is a starting point you must
        review, never a filable value.
      </p>

      {unreplaced.length > 0 && (
        <div className="notice warn" role="status" style={{ fontSize: 12 }}>
          <AlertTriangle
            size={14}
            aria-hidden
            style={{ verticalAlign: "-2px", marginRight: 4 }}
          />
          <b>
            {unreplaced.length} field{unreplaced.length > 1 ? "s" : ""} still
            show the example
          </b>{" "}
          and will fall back to the greyed example text if you author now:{" "}
          {unreplacedLabels.join(", ")}. Replace{" "}
          {unreplaced.length > 1 ? "them" : "it"} with your product&apos;s real
          data — until you do, this section stays <b>not filable</b>.
        </div>
      )}

      {schema.fields.map((field) => (
        <FieldRow
          key={field.name}
          field={field}
          value={fields[field.name] || ""}
          ghost={ghosts[field.name]}
          isSample={sampleKeys.has(field.name)}
          isFact={FACT_KEYS.has(field.name)}
          drafting={drafting === field.name}
          anyDrafting={!!drafting}
          onChange={(v) => set(field.name, v)}
          onDraft={() => draftField(field.name)}
        />
      ))}

      <div className="cta-row">
        <button onClick={generate} disabled={busy || !!drafting}>
          {busy ? "Authoring…" : `Author ${schema.title} →`}
        </button>
        <button
          className="ghost"
          onClick={runReview}
          disabled={busy || !!drafting}
        >
          Review vs Health Canada
        </button>
      </div>
      <ReviewPanel review={review} />
    </div>
  );
}

// One field row — rendered by the schema's declared type, with inline HC help
// and (for a prose field) a "Draft with AI" affordance.
function FieldRow({
  field,
  value,
  ghost,
  isSample,
  isFact,
  drafting,
  anyDrafting,
  onChange,
  onDraft,
}: {
  field: FormField;
  value: string;
  ghost?: string;
  isSample: boolean;
  isFact: boolean;
  drafting: boolean;
  anyDrafting: boolean;
  onChange: (v: string) => void;
  onDraft: () => void;
}) {
  const helpId = `help-${field.name}`;
  const stillExample = isSample && !value.trim();
  // sample fields show their example as a ghost placeholder; a fact/plain field
  // uses its declared placeholder.
  const placeholder = isSample
    ? `e.g. ${ghost || field.sample || ""}`
    : field.placeholder;

  const common = {
    id: field.name,
    value,
    placeholder,
    "aria-describedby": helpId,
    "aria-invalid": (stillExample || undefined) as boolean | undefined,
    "aria-required": (field.required || undefined) as boolean | undefined,
    onChange: (
      e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
    ) => onChange(e.target.value),
  };

  return (
    <div className="form-field">
      <label htmlFor={field.name}>
        {field.label}
        {field.required && (
          <span className="req" aria-hidden style={{ color: "var(--warn)" }}>
            {" "}
            *
          </span>
        )}
        {field.bilingual && (
          <span className="applic optional" style={{ marginLeft: 6 }}>
            EN + FR
          </span>
        )}
        {isSample &&
          (stillExample ? (
            <span
              className="applic optional"
              style={{ color: "var(--warn)", borderColor: "var(--warn)", marginLeft: 6 }}
            >
              example — replace this
            </span>
          ) : (
            <span
              className="applic optional"
              style={{ color: "var(--ok)", marginLeft: 6 }}
            >
              example replaced ✓
            </span>
          ))}
        {isFact && value.trim() && (
          <span className="applic optional" style={{ marginLeft: 6 }}>
            from your dossier
          </span>
        )}
      </label>

      {field.type === "textarea" ? (
        <textarea rows={field.prose ? 4 : 2} {...common} />
      ) : field.type === "select" ? (
        <select {...common}>
          <option value="">— choose —</option>
          {(field.options || []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={
            field.type === "date"
              ? "date"
              : field.type === "email"
              ? "email"
              : field.type === "number"
              ? "number"
              : "text"
          }
          {...common}
        />
      )}

      {field.help && (
        <div id={helpId} className="field-help mut">
          <HelpCircle size={12} aria-hidden style={{ verticalAlign: "-2px", marginRight: 4 }} />
          {field.help}
        </div>
      )}

      {stillExample && ghost && (
        <div className="mut" style={{ fontSize: 12, marginTop: 2 }}>
          Greyed example: <i>{ghost}</i> — this is <b>not</b> your content until
          you type over it.
        </div>
      )}

      {/* per-PROSE-field AI draft — the honest per-field affordance. Disabled
          while any field is drafting so only one streams at a time. */}
      {field.prose && (
        <div style={{ marginTop: 6 }}>
          <button
            type="button"
            className="ghost draft-field-btn"
            onClick={onDraft}
            disabled={anyDrafting}
            aria-busy={drafting || undefined}
          >
            <Sparkles size={13} aria-hidden />{" "}
            {drafting ? "Drafting…" : "Draft with AI"}
          </button>
        </div>
      )}
    </div>
  );
}

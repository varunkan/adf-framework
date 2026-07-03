"use client";
// Register a marketed product post-NOC: dossier × product × DIN × country.
import { useState } from "react";
import { DRUG_TYPES, registryApi, type Registration } from "./registryApi";
import { Term } from "@/components/Term";

export function RegisterForm({
  onCreated,
}: {
  onCreated: (reg: Registration) => void;
}) {
  const [product, setProduct] = useState("");
  const [dossierId, setDossierId] = useState("");
  const [din, setDin] = useState("");
  const [country, setCountry] = useState("CA");
  const [drugType, setDrugType] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    if (!product.trim()) {
      setErr("Product name is required");
      return;
    }
    if (!dossierId.trim()) {
      setErr("Dossier ID is required");
      return;
    }
    if (din.trim() && !/^\d{8}$/.test(din.trim())) {
      setErr("A DIN is exactly 8 digits (e.g. 02248808)");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const reg = await registryApi.create({
        product: product.trim(),
        country: country.trim() || "CA",
        dossier_id: dossierId.trim(),
        din: din.trim(),
        drug_type: drugType,
      });
      setProduct("");
      setDossierId("");
      setDin("");
      setDrugType("");
      onCreated(reg);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card glass" style={{ maxWidth: 720, marginTop: 8 }}>
      <div className="field-row">
        <div>
          <label>Product name</label>
          <input value={product} onChange={(e) => setProduct(e.target.value)}
            placeholder="Drugazole 10 mg tablet" />
        </div>
        <div>
          <label>Dossier ID</label>
          <input value={dossierId} onChange={(e) => setDossierId(e.target.value)}
            placeholder="e123456" />
        </div>
      </div>
      <div className="field-row" style={{ marginTop: 10 }}>
        <div>
          <label>DIN (8 digits)</label>
          <input value={din} onChange={(e) => setDin(e.target.value)}
            placeholder="02248808" inputMode="numeric" maxLength={8}
            aria-describedby="din-live" />
          {/* live validation — a DIN only exists once Health Canada issues
              it at NOC, so blank is CORRECT before then, and anything
              non-blank must be exactly 8 digits */}
          <div id="din-live" aria-live="polite"
            style={{ fontSize: 12, marginTop: 4 }}
            className={!din.trim() || /^\d{8}$/.test(din.trim()) ? "mut" : ""}>
            {!din.trim()
              ? "Issued by Health Canada at NOC — leave blank until then."
              : /^\d{8}$/.test(din.trim())
              ? "✓ Valid DIN format."
              : `✗ A DIN is exactly 8 digits (${din.trim().length}/8${
                  /\D/.test(din.trim()) ? ", digits only" : ""})`}
          </div>
        </div>
        <div>
          <label>Country</label>
          <input value={country} onChange={(e) => setCountry(e.target.value)}
            placeholder="CA" maxLength={2} />
        </div>
        <div>
          <label>Drug type</label>
          <select value={drugType} onChange={(e) => setDrugType(e.target.value)}>
            <option value="">— not set —</option>
            {DRUG_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>
      <p className="mut" style={{ fontSize: 12, margin: "10px 0 0" }}>
        New registrations start as <b>Submitted</b>; move them to NOC-Issued
        and Marketed as Health Canada progresses. Leave the <Term k="DIN" />{" "}
        blank until it is issued with the <Term k="NOC" />.
      </p>
      {err && <div className="notice bad" style={{ marginTop: 10 }}>{err}</div>}
      <div className="cta-row">
        <button onClick={submit} disabled={busy}>
          {busy ? "Registering…" : "Register product →"}
        </button>
      </div>
    </div>
  );
}

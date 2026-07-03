"use client";
import { useCallback, useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { MonographStatus, PmXmlValidation } from "@/lib/dossierTypes";

// WS7 — BILINGUAL + XML PRODUCT MONOGRAPH (addresses labelling_specialist
// "no French/bilingual PM"). Surfaces, from the dossier service:
//   • the bilingual EN/FR Product Monograph status (REQ-098) at heading 1.3.1 —
//     both languages present? which is blocking? (GET /monograph/status)
//   • an XML Product Monograph validate affordance (REQ-099) — paste the built
//     XML PM and check it against the HC schema/stylesheet rules
//     (POST /monograph/xml/validate).
// Only mounted in the Module-1 builder. Every value is read from the backend.

const LANG_LABEL: Record<string, string> = { en: "English", fr: "French" };

export function MonographPanel({ dossierId }: { dossierId: string }) {
  const [status, setStatus] = useState<MonographStatus | null>(null);
  const [error, setError] = useState("");
  const [xml, setXml] = useState("");
  const [xmlResult, setXmlResult] = useState<PmXmlValidation | null>(null);
  const [xmlBusy, setXmlBusy] = useState(false);
  const [showXml, setShowXml] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await dossierApi.monographStatus(dossierId));
      setError("");
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }, [dossierId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function validateXml() {
    if (!xml.trim()) return;
    setXmlBusy(true);
    try {
      setXmlResult(await dossierApi.validatePmXml(xml));
      setError("");
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setXmlBusy(false);
    }
  }

  const pair = status?.pair;

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <div className="mut" style={{ fontSize: 12 }}>
          Product Monograph (1.3.1)
        </div>
        {status && (
          <span
            className={`chip ${status.blocking ? "blocked" : "ready"}`}
            style={{ marginLeft: "auto", fontSize: 11 }}
          >
            {status.blocking ? "Blocked" : "Bilingual complete"}
          </span>
        )}
      </div>

      {error && (
        <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>
          Monograph status unavailable — {error}
        </div>
      )}

      {pair && (
        <div style={{ marginTop: 8, display: "flex", gap: 6, fontSize: 12 }}>
          {(["en", "fr"] as const).map((lang) => {
            const leaf = pair[lang];
            return (
              <span
                key={lang}
                className={`chip ${leaf ? "ready" : "blocked"}`}
                style={{ fontSize: 11 }}
                title={
                  leaf
                    ? `${LANG_LABEL[lang]} PM present — v${leaf.version}: ${leaf.title}`
                    : `${LANG_LABEL[lang]} Product Monograph leaf is missing`
                }
              >
                {leaf ? "✓" : "○"} {LANG_LABEL[lang]}
                {leaf ? ` v${leaf.version}` : ""}
              </span>
            );
          })}
        </div>
      )}

      {status?.findings?.length ? (
        <div style={{ marginTop: 6 }}>
          {status.findings.map((f, i) => (
            <div
              key={i}
              className={f.severity === "blocking" ? "notice bad" : "mut"}
              style={{ fontSize: 11, marginTop: 3 }}
            >
              {f.severity === "blocking" ? "⛔ " : "⚠ "}
              {f.message}
            </div>
          ))}
        </div>
      ) : null}

      <div style={{ marginTop: 10, borderTop: "1px solid var(--line, #2222)", paddingTop: 8 }}>
        <button
          className="ghost"
          style={{ fontSize: 11, padding: "4px 9px" }}
          onClick={() => setShowXml((v) => !v)}
        >
          {showXml ? "Hide XML PM check" : "XML Product Monograph (REQ-099)"}
        </button>
        {showXml && (
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            <div className="mut" style={{ fontSize: 11 }}>
              Health Canada is phasing in a mandatory structured XML Product
              Monograph. Paste the built XML PM to validate it against the
              schema/stylesheet rules before transmission.
            </div>
            <textarea
              aria-label="XML Product Monograph"
              placeholder="<pm>…</pm>"
              value={xml}
              onChange={(e) => setXml(e.target.value)}
              rows={4}
              style={{ fontSize: 11, padding: "6px 8px", fontFamily: "monospace" }}
            />
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <button
                style={{ fontSize: 12, padding: "6px 10px" }}
                onClick={validateXml}
                disabled={xmlBusy || !xml.trim()}
              >
                {xmlBusy ? "Validating…" : "Validate XML PM"}
              </button>
              {xmlResult && (
                <span
                  className={`chip ${xmlResult.blocking ? "blocked" : "ready"}`}
                  style={{ fontSize: 11 }}
                >
                  {xmlResult.blocking
                    ? "Not valid"
                    : xmlResult.findings.length
                      ? "Valid (with warnings)"
                      : "Valid"}
                </span>
              )}
            </div>
            {xmlResult?.findings?.length ? (
              <div>
                {xmlResult.findings.slice(0, 8).map((f, i) => (
                  <div
                    key={i}
                    style={{ display: "flex", gap: 6, alignItems: "baseline", marginTop: 3 }}
                  >
                    <code style={{ fontSize: 10 }}>{f.rule}</code>
                    <span style={{ fontSize: 11 }}>{f.message}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

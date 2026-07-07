"use client";
// Round-9 (operations MAJOR, n=2; labelling_specialist): "is any of this
// available in French, and does it flag when a French product monograph or
// mock-up is missing?" — an explicit bilingual-coverage indicator on the
// operations surfaces. HONESTY IS THE PRODUCT: we state exactly how far
// French coverage extends today rather than imply a bilingual UI that does
// not exist. The missing-FR flag itself lives on the portfolio module tower
// (M1 labelling line) and on each dossier's Module 1 pages.
export function BilingualNote() {
  return (
    <details style={{ marginTop: 8, maxWidth: "78ch" }}>
      <summary className="mut" style={{ cursor: "pointer", fontSize: 12 }}>
        FR / Français — language coverage, stated plainly
      </summary>
      <div className="notice" style={{ fontSize: 12, marginTop: 6 }}>
        <b>What is bilingual today:</b> dossier content — the EN/FR product
        monograph pair at 1.3.1 (a missing FR PM is a transmission blocker on
        the dossier) and French labelling uploads; the portfolio module tower
        flags Module 1 labelling with a missing French version.{" "}
        <b>What is not:</b> this interface, the audit trail and the CSV status
        reports are <b>English-only</b>. A fully French UI for Quebec sponsors
        is not built and has no committed date — we say that plainly rather
        than overclaim.
      </div>
    </details>
  );
}

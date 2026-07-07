// The Health Canada content-review panel — required-element / suggested-edit
// findings surfaced after authoring a section's form. Shared by the in-app
// author flow (SectionPanel) and the dynamic FormFill form.
export function ReviewPanel({ review }: { review: any }) {
  if (!review) return null;
  const f = review.findings || [];
  return (
    <div className={`notice ${review.passed ? "ok" : "bad"}`} style={{ marginTop: 10 }}>
      {/* Round-9 (builder_forms, n=4): a green "no blocking content gaps"
          reads as a compliance pass — it is a completeness HEURISTIC. Say so
          on the face, in the same honest voice as the eValidator caveat. */}
      <b>Content review:</b>{" "}
      {review.passed
        ? "no obvious gaps found — advisory only."
        : `${review.error_count} to fix, ${review.warning_count} to check.`}
      {review.passed && (
        <div className="mut" style={{ fontSize: 11, marginTop: 2 }}>
          A content-completeness check against Health Canada&apos;s required
          elements — not a screening clearance or regulatory acceptance.
        </div>
      )}
      {f.length > 0 && (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          {f.map((x: any, i: number) => (
            <li key={i} style={{ marginBottom: 6, fontSize: 12 }}>
              <b>
                {x.severity === "error" ? "✗" : "⚠"} {x.message}
              </b>
              <div className="mut">
                ↳ {x.suggested_edit}{" "}
                {x.hc_url && (
                  <a href={x.hc_url} target="_blank" rel="noopener noreferrer">
                    HC guidance ↗
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

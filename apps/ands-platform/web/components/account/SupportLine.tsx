"use client";
// onboarding — visible support contact on MFA setup + reset screens (n=2).
// Round-9 item 16 (minor). HONESTY GUARDRAIL: no staffed phone line exists
// today, so none is invented — the real channel (email) is stated, the demo
// build's no-outbound-email limitation is stated, and the phone line is
// labelled roadmap, not claimed live.
import type { CSSProperties } from "react";

export function SupportLine({ style }: { style?: CSSProperties }) {
  return (
    <p className="mut" style={{ fontSize: 12, margin: 0, ...style }}>
      Stuck on this step? Email{" "}
      <a href="mailto:support@ands.studio">support@ands.studio</a> — a human
      replies within 1 business day. (Demo build: outbound email is disabled
      here.) A staffed phone line is on the roadmap — not yet available.
    </p>
  );
}

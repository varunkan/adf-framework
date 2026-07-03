// WS4.3 — a single honest source of truth for not-yet-built capabilities and
// their target quarters. Rendered on the Account page (Roadmap card) and linked
// to from the sign-in SSO affordance. Anchors here (id) are used as URL hashes,
// e.g. /roadmap#sso, so the SSO link lands on the exact entry.

export interface RoadmapEntry {
  id: string;
  title: string;
  targetQuarter: string;
  status: "planned" | "in-design";
  detail: string;
}

// Keep dates HONEST — these are stated targets, not shipped features. Today is
// 2026-07-03, so the near horizon is Q3/Q4 2026 and H1 2027.
export const ROADMAP: RoadmapEntry[] = [
  {
    id: "sso",
    title: "Single sign-on (SAML 2.0 / OIDC)",
    targetQuarter: "Q1 2027",
    status: "planned",
    detail:
      "Sign in with your organisation's identity provider (Azure AD / Entra, " +
      "Okta, Google Workspace) with SCIM provisioning. Not built yet — today " +
      "accounts are per-workspace email + password with TOTP MFA (and an " +
      "optional workspace-wide MFA mandate) as the second factor.",
  },
  {
    id: "scim",
    title: "Automated user provisioning (SCIM 2.0)",
    targetQuarter: "Q1 2027",
    status: "planned",
    detail:
      "De-provision leavers and sync group membership from your IdP. Ships " +
      "alongside SSO; until then, workspace admins invite and remove members " +
      "manually.",
  },
  {
    id: "audit-siem",
    title: "Audit-log streaming to your SIEM",
    targetQuarter: "Q4 2026",
    status: "in-design",
    detail:
      "Forward the append-only audit event stream to Splunk / Sentinel / an " +
      "S3 sink. Today the full audit trail is viewable and exportable in-app " +
      "(CSV / JSON / plain-text) on this page.",
  },
];

export const ssoEntry = (): RoadmapEntry =>
  ROADMAP.find((e) => e.id === "sso")!;

# ANDS Studio — Independent RA-Officer Certification (SIGN-OFF)

**Evaluator (persona):** Priya Raghavan, Director of Regulatory Affairs,
Northline Regulatory Partners — a Canadian CRO filing for 12 competing sponsors.
**Method:** adversarial, hands-on evaluation over five rounds — the persona
read the code, drove the live app in the browser, and probed the running mesh
directly with `curl` (fresh workspaces each round), filing complete sample ANDS
submissions and attempting cross-tenant attacks.

## Verdict (Round 5): FULLY SATISFIED — "I would purchase." 11/11 pass, 0 open findings.

### The five-round loop (adversarial hardening)

| Round | Verdict | Findings raised → resolution |
|------|---------|------------------------------|
| 1 | not satisfied | 2 blockers (anonymous API access; dossier cross-tenant leak) + 2 majors (export not valid eCTD 3.2.2; malformed REP RT) — all fixed |
| 2 | not satisfied | 1 blocker: registry leaked (isolation applied only to the dossier service) → **all six remaining services tenant-partitioned** |
| 3 | not satisfied (12/14) | 2 blockers (`/documents/{doc_id}`, `/archive` binder family) + 1 major (backends trusted `X-Tenant-Id` with no caller auth) — all fixed |
| 4 | satisfied *with reservations* (8/9) | 1 major: Part-11 audit trail written with empty tenant → permanently blank — fixed |
| 5 | **fully satisfied — would purchase (11/11)** | none |

### What the sign-off verified (Round 5, hands-on)

- **Part-11 audit trail is alive**: every event stamped with the acting tenant
  **and** actor; the browser audit page renders the `by <email>` chip; a rival
  tenant sees none of it.
- **Tenant isolation on every surface**: anonymous → 401; cross-tenant → 404;
  **direct-to-backend forged `X-Tenant-Id` (no gateway token) → 401** on dossier,
  registry, and governance.
- **eCTD 3.2.2 / CA-M1 v2.2 export**: real `<ectd:ectd>` + DOCTYPE + `util/dtd`,
  `<ca:ectd-ca dtd-version="2.2">`, checksummed leaves; the 0001 response
  sequence carries only the replaced leaf with a `<modified-file>` back-ref and
  no dangling entries.
- **REP RT**: COMPANY_NAME = sponsor (not the product), PRODUCT_NAME = product,
  Company ID present, DIN empty pre-NOC.
- **Validation is a real gate**: passes clean PDFs, rejects non-`%PDF` bytes with
  rule `CA-E-7001`.
- HttpOnly session cookie; guided journey; AI drafting; module builder;
  portfolio / registry / correspondence surfaces.

### Honest scope the evaluator explicitly accepted (not defects)

- Real CESG transmission needs an FDA-ESG/gateway account — the product
  prepares, validates, signs, **simulates** the MDN→FDA→HC chain through the real
  transmission state machine, and **exports the transmissible WebTrader package**.
- Annual notification is a clearly-labelled client-side reminder.
- The binder share link is an intentional unguessable-token capability.
- Production would add mTLS / service-mesh auth at ingress; the internal mesh
  token is the app-layer equivalent enforced here.

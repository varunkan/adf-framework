// Client over the same-origin /api/registry proxy → the registry service.
// Shapes mirror services/registry/app/{registry,api}.py (REQ-111).

export const STATUSES = [
  "Submitted",
  "NOC-Issued",
  "Marketed",
  "Suspended",
  "Cancelled",
] as const;
export type RegistrationStatus = (typeof STATUSES)[number];

// Mirror of the service's status state machine — used only to decide which
// transition buttons to OFFER; the service remains the enforcer (409/422).
export const TRANSITIONS: Record<RegistrationStatus, RegistrationStatus[]> = {
  Submitted: ["NOC-Issued", "Cancelled"],
  "NOC-Issued": ["Marketed", "Suspended", "Cancelled"],
  Marketed: ["Suspended", "Cancelled"],
  Suspended: ["Marketed", "Cancelled"],
  Cancelled: [],
};

export const DRUG_TYPES = [
  "prescription",
  "non-prescription",
  "disinfectant",
  "biocide",
] as const;

// A Right-to-Sell obligation exists once the product is marketable.
export const RTS_STATUSES: RegistrationStatus[] = [
  "NOC-Issued",
  "Marketed",
  "Suspended",
];

export interface Registration {
  id: string;
  product: string;
  country: string;
  dossier_id: string;
  din: string | null;
  drug_type: string | null;
  status: RegistrationStatus;
  created_at: string;
  updated_at: string;
}

export type RightToSell =
  | { applies: false; reason: string }
  | {
      applies: true;
      drug_type: string | null;
      din: string | null;
      due_date: string;
      fiscal_year: string;
      fee_owner: string;
      overdue: boolean;
    };

const BASE = "/api/registry";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const b = await res.json();
      // problem+json: title/detail plus an optional per-field errors list
      const rules = Array.isArray(b.errors)
        ? b.errors.map((e: { message?: string }) => e.message).filter(Boolean)
        : [];
      detail =
        [b.title, b.detail, ...rules].filter(Boolean).join(": ") || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const registryApi = {
  list: () =>
    j<{ registrations: Registration[]; count: number }>("/registrations"),

  create: (body: {
    product: string;
    country: string;
    dossier_id: string;
    din?: string;
    drug_type?: string;
  }) =>
    j<Registration>("/registrations", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  setStatus: (id: string, status: RegistrationStatus) =>
    j<Registration>("/registrations/status", {
      method: "POST",
      body: JSON.stringify({ id, status }),
    }),

  rightToSell: (id: string, asOf: string) =>
    j<RightToSell>(
      `/registrations/${encodeURIComponent(id)}/right-to-sell?as_of=${encodeURIComponent(asOf)}`
    ),

  // annual notification checklist — server-tracked per workspace + year;
  // each tick records who signed it and when (round-4 panel fix)
  annualChecklist: (year = 0) =>
    j<{ year: number; items: ChecklistItem[]; count: number }>(
      `/annual-checklist${year ? `?year=${year}` : ""}`),

  setAnnualItem: (itemKey: string, done: boolean, year = 0) =>
    j<{ year: number; item: ChecklistItem }>("/annual-checklist/items", {
      method: "POST",
      body: JSON.stringify({ item_key: itemKey, done, year }),
    }),
};

export interface ChecklistItem {
  item_key: string;
  label: string;
  done: boolean;
  signed_by: string | null;
  signed_at: string | null;
}

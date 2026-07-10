const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export type ValidationError = { rule: string; message: string };

export type Submission = {
  id: number;
  applicant: string;
  drug_product: string;
  dossier_id: string;
  submission_type: string;
  sequence: string;
  contact_email: string;
  created_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? JSON.stringify(body.detail) : res.statusText);
  }
  return res.json() as Promise<T>;
}

export function validateIntake(payload: Record<string, string>) {
  return request<{ valid: boolean; errors: ValidationError[] }>(
    "/api/validate",
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function createSubmission(payload: Record<string, string>) {
  return request<Submission>("/api/submissions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listSubmissions() {
  return request<{ submissions: Submission[] }>("/api/submissions");
}

export function healthCheck() {
  return request<{ status: string; service: string }>("/api/health");
}

export function getAndsFee() {
  return request<Record<string, unknown>>("/api/fees/ands");
}

export function configureEsg(config: Record<string, unknown>) {
  return request<Record<string, unknown>>("/api/transmission/configure", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export function testEsgRoundTrip(config: Record<string, unknown>) {
  return request<Record<string, unknown>>("/api/transmission/test-round-trip", {
    method: "POST",
    body: JSON.stringify({ config, acks: { mdn_received: true, fda_ack_received: true, hc_ack_received: true } }),
  });
}

export { API_URL };

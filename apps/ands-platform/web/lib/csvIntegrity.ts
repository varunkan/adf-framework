// Round-9 (operations MAJOR, n=5): CSV exports as documented inspection
// artifacts — a stable versioned schema line, an all-UTC statement, and a
// SHA-256 integrity manifest embedded in the file itself.
//
// Verification procedure (stated in the manifest line so it travels with the
// evidence): remove the final "#manifest" line, hash the remaining bytes
// (UTF-8, LF line endings) with SHA-256, compare. Any edit to any row breaks
// the hash. This is tamper-EVIDENCE on the copy; the server-side append-only
// audit trail remains the official record — the export is a convenience copy.

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function withIntegrityManifest(
  csvRows: string,
  schema: string,       // e.g. "ands.audit-export"
  version: string,      // bump when columns change — a published contract
): Promise<string> {
  const header =
    `#schema ${schema}@${version} · all timestamps UTC (ISO-8601) · ` +
    `convenience copy — the server-side append-only audit trail is the ` +
    `official record\n`;
  const body = header + csvRows + "\n";
  const hash = await sha256Hex(body);
  return (
    body +
    `#manifest sha256=${hash} · verify: strip this line, SHA-256 the rest ` +
    `(UTF-8, LF)\n`
  );
}

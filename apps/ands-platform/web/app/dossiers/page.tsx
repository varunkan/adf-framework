"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { dossierApi } from "@/lib/dossierApi";
import { Term } from "@/components/Term";
import { TopNav } from "@/components/TopNav";
import { Modal } from "@/components/Modal";
import { SetRealDossierIdModal } from "@/components/dossier/SetRealDossierIdModal";
import { auth } from "@/lib/auth";
import { dueMeta } from "@/lib/deadline";
import { withIntegrityManifest } from "@/lib/csvIntegrity";
import { toast } from "sonner";
// R9-CATALOG: the round-9 catalog surface — named due-date clocks, REP request
// status, lifecycle/validation columns, bilingual fields, access proof, cost
// anchor, calendar, bulk import and typed-name e-signature capture.
import { catalogApi, type CatalogListItem, type EsignCapture }
  from "@/components/dossier/catalogApi";
import { DueClockCell } from "@/components/dossier/DueClock";
import { AccessProofPanel } from "@/components/dossier/AccessProofPanel";
import { CostTimelineAnchor } from "@/components/dossier/CostTimelineAnchor";
import { DueCalendar } from "@/components/dossier/DueCalendar";
import { BulkDossierImport } from "@/components/dossier/BulkDossierImport";
import { SponsorScope, ALL_SPONSORS, matchesSponsor }
  from "@/components/SponsorScope";

// The three Health Canada abbreviated/supplemental pathways this tool models.
// comparative-BE (cs_be_only) is an ANDS-only property, not a submission type.
// R9-CATALOG "Submission types and CS-BE undefined at the point of choice"
// (n=10): each option carries a plain-language definition AND an example,
// rendered under the dropdown — no hovering needed to pick correctly.
const SUBMISSION_TYPES = [
  { code: "ANDS", label: "ANDS — Abbreviated New Drug Submission (generic)",
    def: "Your first filing for a generic copy of an already-approved drug.",
    example: "Example: filing generic atorvastatin 20 mg tablets against " +
      "Lipitor as the Canadian reference product." },
  { code: "SANDS", label: "SANDS — Supplement to an ANDS (post-NOC change)",
    def: "A change to a generic you already have approved (post-NOC).",
    example: "Example: adding a new manufacturing site or a new strength to " +
      "your approved generic." },
  { code: "SNDS", label: "SNDS — Supplement to a New Drug Submission",
    def: "A change to an innovator (brand) product's existing approval.",
    example: "Example: a brand sponsor adding a new indication to an " +
      "approved product." },
] as const;

// TIER-A: the dosage form drives the Health-Canada comparative-evidence route
// for a generic. requiresBe=false forms open a biowaiver / non-PK route, which
// makes the 5.3.1 BE study + 1.6 CS-BE summary CONDITIONAL rather than required.
// Mirrors journey.drug_intake.DOSAGE_FORMS (kept in sync; the catalog is the
// authoritative source, this is the create-form fallback).
const DOSAGE_FORMS = [
  { code: "ir_solid_oral", label: "Immediate-release solid oral (tablet/capsule)",
    requiresBe: true },
  { code: "mr_solid_oral", label: "Modified-release solid oral", requiresBe: true },
  { code: "oral_solution", label: "Oral solution / aqueous liquid",
    requiresBe: false },
  { code: "parenteral_solution", label: "Parenteral (injectable) aqueous solution",
    requiresBe: false },
  { code: "complex_parenteral",
    label: "Complex parenteral (long-acting injectable / microsphere / liposome)",
    requiresBe: true },
  { code: "ophthalmic_otic_solution", label: "Ophthalmic / otic solution",
    requiresBe: false },
  { code: "orally_inhaled", label: "Orally inhaled product", requiresBe: true },
  { code: "topical_local", label: "Topical / locally-acting (dermal)",
    requiresBe: false },
  { code: "other", label: "Other / not sure", requiresBe: true },
] as const;
const GENERIC_FAMILY = new Set(["ANDS", "SANDS"]);

// TIER-B: the product class. inScope=true is ANDS Studio's core generic small-
// molecule chemical-drug authoring; the others are real Health Canada regimes
// with different directorates/instruments — surfaced honestly, never hollow.
// Mirrors journey.product_class (the catalog is authoritative; this is the
// create-form fallback so the banner shows without a round-trip).
const PRODUCT_CLASSES = [
  { code: "small_molecule", label: "Small-molecule chemical drug", inScope: true,
    note: "" },
  { code: "biologic", label: "Biologic (Schedule D)", inScope: false,
    note: "A biologic is reviewed by the BRDD and filed as an NDS/SNDS, not an "
      + "ANDS. ANDS Studio gives you the correct eCTD shell, validation and fees, "
      + "but the science is authored to the biologics guidance." },
  { code: "biosimilar", label: "Biosimilar (subsequent-entry biologic)",
    inScope: false,
    note: "A biosimilar is NOT a generic: Health Canada authorizes it through a "
      + "full New Drug Submission (NDS) with a similarity package vs. the "
      + "reference biologic — the ANDS bioequivalence pathway does not apply." },
  { code: "radiopharmaceutical", label: "Radiopharmaceutical (Schedule C)",
    inScope: false,
    note: "A radiopharmaceutical carries the additional Part C, Division 3 "
      + "requirements under BRDD review, which ANDS Studio does not model — "
      + "treat its output as the eCTD shell only." },
  { code: "veterinary", label: "Veterinary drug", inScope: false,
    note: "A veterinary drug is reviewed by the Veterinary Drugs Directorate "
      + "through its own stream, not the human-drug ANDS pathway." },
  { code: "disinfectant", label: "Surface disinfectant / biocide", inScope: false,
    note: "A surface disinfectant is an NNHPD-assessed DIN (transitioning to the "
      + "Biocides Regulations), not an ANDS/NDS eCTD review — outside ANDS "
      + "Studio's authoring model." },
  { code: "natural_health_product", label: "Natural health product (NHP)",
    inScope: false,
    note: "An NHP is regulated under the Natural Health Products Regulations "
      + "(NPN, not a DIN) by the NNHPD — an entirely separate regime." },
] as const;

// R9-CATALOG "Archive/delete reason is pure free text" (n=2): a controlled
// vocabulary keeps archive reasons auditable and consistent; free-text detail
// stays available but optional.
const ARCHIVE_REASONS = [
  "Duplicate created in error",
  "Test / practice dossier",
  "Data entry error",
  "Product program discontinued",
  "Client engagement ended",
  "Superseded by another dossier",
  "Other (state below)",
] as const;

type SortKey =
  | "dossier_id" | "title" | "status" | "submission_type"
  | "sponsor" | "owner" | "soonest_due";

type ArchivedItem = CatalogListItem & {
  archived_at?: string;
  archived_by?: string;
  archive_reason?: string;
};

// R9-CATALOG "Placeholder-ID warning too easy to forget" (n=4): the
// placeholder's AGE, computed from the dossier's creation stamp.
function placeholderAgeDays(d: CatalogListItem): number | null {
  if (!d.created_at) return null;
  const t = Date.parse(d.created_at);
  if (isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}

// R9-CATALOG "Audit trail is asserted but not viewable or exportable" (n=4):
// one-click per-dossier audit-trail CSV export straight from the catalog /
// archived list — same integrity-manifested artifact as the audit page.
async function exportAuditCsv(dossierId: string) {
  try {
    const body = await dossierApi.getHistory(dossierId);
    const events = body.events || [];
    if (!events.length) {
      toast.info(`${dossierId} — no audit events recorded yet`);
      return;
    }
    const esc = (s: unknown) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const rows = [
      ["seq", "at", "action", "actor", "reason", "dossier_id", "detail"],
      ...events.map((e) => [
        e.seq, e.timestamp, e.event_type, e.actor || "", e.reason || "",
        e.dossier_id, JSON.stringify(e.data || {}),
      ]),
    ];
    const csv = await withIntegrityManifest(
      rows.map((r) => r.map(esc).join(",")).join("\n"),
      "ands.audit-export", "1");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `audit-${dossierId}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    toast.error(String((e as Error)?.message || e));
  }
}

// R9-CATALOG "No bilingual/French support surfaced anywhere on the page"
// (n=2): the governed bilingual-PM language badge (EN+FR pair at Module 1
// heading 1.3.1 — mirrors the monograph engine verbatim).
function BilingualBadge({ d }: { d: CatalogListItem }) {
  const b = d.bilingual_pm;
  if (!b || b.status === "none") {
    return (
      <span className="mut" style={{ fontSize: 12 }}
        title="No Product Monograph leaves registered yet — the bilingual EN+FR pair check starts once a PM is added (a missing FR or EN blocks transmission).">
        no PM yet
      </span>
    );
  }
  const cls = b.status === "complete" ? "ready" : "blocked";
  const word = b.status === "complete" ? "EN+FR complete" : "EN+FR blocked";
  return (
    <span className={`chip ${cls}`} style={{ fontSize: 11 }}
      title={`Bilingual Product Monograph status (governed pair at 1.3.1): EN ${b.en ? "present" : "missing"} · FR ${b.fr ? "present" : "missing"}. A missing FR (or EN) is a transmission blocker.`}>
      {word}
    </span>
  );
}

// R9-CATALOG "REP Dossier ID Request flow unexplained and untracked" (n=7):
// the per-dossier REP request status chip on the tile/row. HONEST: a PREPARED
// request — never a transmission to Health Canada.
function RepRequestChip({ d }: { d: CatalogListItem }) {
  const rep = d.rep_request;
  if (!rep) return null;
  const when = rep.requested_at
    ? new Date(rep.requested_at).toLocaleDateString() : "";
  return (
    <span className="chip" style={{ fontSize: 11 }}
      title={`REP Dossier ID Request prepared in-app${when ? ` on ${when}` : ""}${rep.requested_by ? ` by ${rep.requested_by}` : ""} — recorded intent only; NOT transmitted to Health Canada. File it via REP/CESG, then set the real ID here.`}>
      REP request prepared{when ? ` · ${when}` : ""}
    </span>
  );
}

// R9-CATALOG "List view lacks sequence/lifecycle and validation status" (n=4):
// the last structural-check summary + the user-attested eValidator state.
// HONEST: structural check, never an HC eValidator pass.
function ValidationCellBody({ d }: { d: CatalogListItem }) {
  const s = d.structural;
  const ev = d.evalidator;
  if (!s) return <span className="mut">—</span>;
  return (
    <span style={{ display: "inline-flex", gap: 4, flexDirection: "column" }}>
      <span className={s.passed ? "mut" : "bad-text"} style={{ fontSize: 12 }}
        title="Live structural check (same engine as the builder's validation card) — structural/technical checks only, NOT Health Canada's official eValidator.">
        {s.passed ? "structural: no issues"
          : `structural: ${s.error_count} error${s.error_count === 1 ? "" : "s"}`}
        {s.warning_count ? ` · ${s.warning_count} warn` : ""}
      </span>
      <span className="mut" style={{ fontSize: 11 }}
        title={ev?.cleared
          ? `eValidator: cleared per the user-attested external result${ev?.validated_on ? ` (${ev.validated_on})` : ""}.`
          : "eValidator: not yet cleared — run Health Canada's official eValidator externally and attest the result on the dossier."}>
        {ev?.cleared ? "eValidator: attested clear" : "eValidator: not cleared"}
      </span>
    </span>
  );
}

export default function DossiersHome() {
  const router = useRouter();
  const [items, setItems] = useState<CatalogListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [did, setDid] = useState("");
  const [title, setTitle] = useState("");
  // R9-CATALOG bilingual (n=2): governed EN/FR product names + labelling owner
  const [titleFr, setTitleFr] = useState("");
  const [labellingOwner, setLabellingOwner] = useState("");
  // R7: submission type is chosen at creation (no longer hardcoded ANDS/CS-BE);
  // cs_be_only is an ANDS-only comparative-BE property, sponsor/owner feed the
  // portfolio list view (WS6 fields already round-trip to the index).
  const [subType, setSubType] = useState<string>("ANDS");
  const [csBeOnly, setCsBeOnly] = useState(true);
  // TIER-A: dosage form → comparative-evidence route (generic families only)
  const [dosageForm, setDosageForm] = useState<string>("ir_solid_oral");
  // TIER-B: product class → honest out-of-core scope banner
  const [productClass, setProductClass] = useState<string>("small_molecule");
  const [sponsor, setSponsor] = useState("");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // R7 catalog list/table view — triage dozens of dossiers across sponsors.
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [sortKey, setSortKey] = useState<SortKey>("soonest_due");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filterText, setFilterText] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [myEmail, setMyEmail] = useState<string>("");
  // R9-CATALOG "Flat dossier list won't scale" (n=2): explicit per-client
  // sponsor scope + group-by-client tiles on the catalog itself.
  const [sponsorScope, setSponsorScope] = useState<string>(ALL_SPONSORS);
  const [groupByClient, setGroupByClient] = useState(false);
  useEffect(() => {
    auth.me().then((m) => setMyEmail((m?.name || m?.email || "").toLowerCase()))
      .catch(() => {});
  }, []);

  // in-app modal state (replaces native confirm/prompt)
  const [delTarget, setDelTarget] = useState<string | null>(null);
  const [delTyped, setDelTyped] = useState("");
  // R9-CATALOG (n=2): controlled-vocabulary reason + optional free-text detail
  const [delReasonCode, setDelReasonCode] = useState<string>("");
  const [delDetail, setDelDetail] = useState("");
  // R9-CATALOG (n=6): typed-name e-signature on archive (recorded verbatim on
  // the durable ledger — typed-name capture, not a cryptographic certificate)
  const [delSignName, setDelSignName] = useState("");
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalErr, setModalErr] = useState("");

  // R9-CATALOG (n=6): restore also captures a typed-name e-signature
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);
  const [restoreSignName, setRestoreSignName] = useState("");

  // R9-CATALOG (n=6): Owner (PM) reassignment — accountability label; the
  // old/new values + reason land on the durable ledger.
  const [ownerTarget, setOwnerTarget] = useState<string | null>(null);
  const [ownerValue, setOwnerValue] = useState("");
  const [ownerReason, setOwnerReason] = useState("");

  // POLISH-ID-BEFORE-409: the set-real-ID + REP flow now lives in the shared
  // SetRealDossierIdModal (reused by the builder chrome). Seed it with any
  // known sponsor/company for the target dossier.
  const [renameSeedCompany, setRenameSeedCompany] = useState("");
  const [renameSeedSponsor, setRenameSeedSponsor] = useState("");

  // recoverable archive (soft-deleted dossiers) — restore with undo
  const [showArchived, setShowArchived] = useState(false);
  const [archived, setArchived] = useState<ArchivedItem[]>([]);

  const load = useCallback(async () => {
    try {
      setItems((await catalogApi.listDossiers()).dossiers);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const loadArchived = useCallback(async () => {
    try {
      setArchived((await catalogApi.listArchived()).dossiers);
    } catch (er) {
      setErr(String(er));
    }
  }, []);

  function openDelete(e: React.MouseEvent, dossierId: string) {
    e.preventDefault();  // the tile is a Link — don't navigate
    e.stopPropagation();
    setDelTarget(dossierId);
    setDelTyped("");
    setDelReasonCode("");
    setDelDetail("");
    setDelSignName("");
    setModalErr("");
  }

  // the auditable reason string: controlled vocabulary + optional detail
  function delReason(): string {
    const code = delReasonCode.trim();
    const detail = delDetail.trim();
    if (!code) return "";
    return detail ? `${code} — ${detail}` : code;
  }

  async function confirmDelete() {
    if (!delTarget) return;
    setModalBusy(true);
    setModalErr("");
    try {
      // send the typed Dossier ID as confirm_id — the server re-checks it
      // (a direct API DELETE cannot bypass this typed-confirmation gate).
      // R9-CATALOG (n=6): the typed-name e-signature rides on the durable
      // archive event.
      const esign: EsignCapture = {
        signed_name: delSignName.trim(),
        meaning: `I authorize archiving dossier ${delTarget}`,
      };
      await catalogApi.archiveDossier(delTarget, delReason(),
        delTyped.trim(), esign);
      toast.success(`${delTarget} archived — recoverable from the archive`);
      setDelTarget(null);
      await load();
      if (showArchived) await loadArchived();
    } catch (er) {
      setModalErr(String(er));
    } finally {
      setModalBusy(false);
    }
  }

  async function confirmRestore() {
    if (!restoreTarget) return;
    setModalBusy(true);
    setModalErr("");
    try {
      const esign: EsignCapture = {
        signed_name: restoreSignName.trim(),
        meaning: `I authorize restoring dossier ${restoreTarget}`,
      };
      await catalogApi.restoreDossier(restoreTarget,
        "restored from dossier manager", esign);
      toast.success(`${restoreTarget} restored`);
      setRestoreTarget(null);
      await Promise.all([load(), loadArchived()]);
    } catch (er) {
      setModalErr(String(er));
    } finally {
      setModalBusy(false);
    }
  }

  async function confirmOwner() {
    if (!ownerTarget) return;
    setModalBusy(true);
    setModalErr("");
    try {
      await catalogApi.setOwner(ownerTarget, ownerValue.trim(),
        ownerReason.trim());
      toast.success(`${ownerTarget} — owner ${ownerValue.trim() ? `set to ${ownerValue.trim()}` : "unassigned"}`);
      setOwnerTarget(null);
      await load();
    } catch (er) {
      setModalErr(String(er));
    } finally {
      setModalBusy(false);
    }
  }

  function usePlaceholder() {
    // 'd' prefix = draft: work starts now, the real HC ID replaces it later
    setDid("d" + String(Math.floor(100000 + Math.random() * 900000)));
    setErr("");
  }

  function openRename(e: React.MouseEvent, oldId: string) {
    e.preventDefault();
    e.stopPropagation();
    setRenameTarget(oldId);
    // seed the REP helper with any known sponsor/company for this dossier
    const d = items.find((it) => it.dossier_id === oldId);
    setRenameSeedCompany((d as { company_id?: string })?.company_id || "");
    setRenameSeedSponsor((d as { sponsor?: string })?.sponsor || "");
  }

  // R9-CATALOG "No bulk create/import or keyboard-fast entry" (n=1): andAnother
  // keeps the form open + refocuses the ID field for rapid serial entry.
  async function create(andAnother = false) {
    if (!/^[a-z]\d{6,7}$/.test(did.trim())) {
      setErr("Dossier ID must be one letter + 6–7 digits (e.g. e123456)");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await catalogApi.createDossier({
        dossier_id: did.trim(),
        title,
        // R9-CATALOG bilingual (n=2): governed FR name + labelling owner
        title_fr: titleFr.trim() || undefined,
        labelling_owner: labellingOwner.trim() || undefined,
        submission_type: subType,
        // cs_be_only only means something on the ANDS path; force false otherwise
        cs_be_only: subType === "ANDS" ? csBeOnly : false,
        // TIER-A: the dosage form is a generic-family property (drives the
        // comparative-evidence route); default the innovator paths to solid oral
        dosage_form_class: GENERIC_FAMILY.has(subType) ? dosageForm : "ir_solid_oral",
        // TIER-B: the product class (for the honest out-of-core scope note)
        product_class: productClass,
        sponsor: sponsor.trim() || undefined,
        owner: owner.trim() || undefined,
      });
      toast.success(`Dossier ${did.trim()} created`);
      if (andAnother) {
        setDid("");
        setTitle("");
        setTitleFr("");
        setBusy(false);
        await load();
        // keyboard-fast: straight back to the ID field for the next row
        (document.getElementById("new-dossier-id") as HTMLInputElement | null)
          ?.focus();
        return;
      }
      router.push(`/dossiers/${encodeURIComponent(did.trim())}/m/1`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  // R7: honest per-tile submission label. CS-BE is shown ONLY when the dossier
  // is actually a comparative-BE ANDS (cs_be_only) — never hardcoded.
  function typeLabel(d: CatalogListItem): string {
    const t = d.submission_type || "ANDS";
    return t === "ANDS" && d.cs_be_only ? `${t} · CS-BE` : t;
  }

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir((v) => (v === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir("asc"); }
  }

  const rows = useMemo(() => {
    const q = filterText.trim().toLowerCase();
    let out = items.filter((d) => {
      if (mineOnly && myEmail &&
          (d.owner || "").toLowerCase() !== myEmail) return false;
      // R9-CATALOG (n=2): explicit per-client sponsor scope on the catalog
      if (!matchesSponsor(d, sponsorScope)) return false;
      if (!q) return true;
      return [d.dossier_id, d.title, d.title_fr, d.submission_type, d.sponsor,
        d.owner, d.labelling_owner]
        .some((v) => String(v || "").toLowerCase().includes(q));
    });
    const val = (d: CatalogListItem): string | number => {
      switch (sortKey) {
        case "status": {
          const applic = d.tower.filter((t) => t.state !== "na").length;
          const passed = d.tower.filter((t) => t.state === "pass").length;
          return d.gate?.complete ? 1e6 : (applic ? passed / applic : 0);
        }
        case "submission_type": return typeLabel(d);
        case "soonest_due":
          // no deadline sorts last on asc (Infinity), first on desc
          return d.soonest_due ? Date.parse(d.soonest_due) : Number.MAX_SAFE_INTEGER;
        case "title": return (d.title || "").toLowerCase();
        case "sponsor": return (d.sponsor || "").toLowerCase();
        case "owner": return (d.owner || "").toLowerCase();
        default: return (d.dossier_id || "").toLowerCase();
      }
    };
    out = [...out].sort((a, b) => {
      const va = val(a), vb = val(b);
      const c = va < vb ? -1 : va > vb ? 1 : 0;
      return sortDir === "asc" ? c : -c;
    });
    return out;
  }, [items, filterText, mineOnly, myEmail, sponsorScope, sortKey, sortDir]);

  // R9-CATALOG (n=2): grouped/foldered tiles — client buckets for the grid
  const grouped = useMemo(() => {
    if (!groupByClient) return null;
    const m = new Map<string, CatalogListItem[]>();
    for (const d of rows) {
      const s = (d.sponsor || "").trim() || "Unassigned (no REP sponsor set)";
      m.set(s, [...(m.get(s) || []), d]);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows, groupByClient]);

  const sortArrow = (k: SortKey) =>
    sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "";

  // one dossier tile (grid view) — shared by flat + grouped rendering
  function tile(d: CatalogListItem) {
    const passed = d.tower.filter((t) => t.state === "pass").length;
    const applic = d.tower.filter((t) => t.state !== "na").length;
    const age = d.dossier_id.startsWith("d") ? placeholderAgeDays(d) : null;
    return (
      <Link key={d.dossier_id} href={`/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`}
        className="card glass dossier-tile">
        <div className="d-id">
          {d.dossier_id}
        </div>
        {/* R9-CATALOG "Placeholder-ID warning too easy to forget" (n=4): the
            tile escalates from a chip to a banner STRIP showing the
            placeholder's age; the dossier page adds the recurring
            acknowledgment nag. Export/transmission stay hard-blocked. */}
        {d.dossier_id.startsWith("d") && (
          <div className="notice warn" role="status"
            style={{ padding: "6px 10px", fontSize: 12, margin: "6px 0",
              display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span>
              <b>Placeholder ID</b>
              {age !== null ? ` — day ${age + 1}` : ""} · NOT a Health Canada
              Dossier ID; export/transmission blocked until the real ID
              (issued via REP) is set.
            </span>
            <button className="chip placeholder-id" style={{ fontSize: 11 }}
              onClick={(e) => openRename(e, d.dossier_id)}>
              Set real ID ✎
            </button>
          </div>
        )}
        <div className="d-title">
          {d.title}
          {/* R9-CATALOG bilingual (n=2): the governed FR name, when captured */}
          {d.title_fr && (
            <span className="mut" style={{ display: "block", fontSize: 12 }}
              title="Governed French product name (paired with the English name)">
              FR: {d.title_fr}
            </span>
          )}
        </div>
        <div className="d-meta mut">
          {typeLabel(d)}
          {d.sponsor ? ` · ${d.sponsor}` : ""}
        </div>
        <div className="progress"><i style={{
          width: `${applic ? (passed / applic) * 100 : 0}%` }} /></div>
        {/* WS1-c: completeness is NOT a filing verdict. Never render
            "Ready to file" from module-completion — that green badge
            must come from a real eCTD validation pass (in the builder/
            journey), not this catalog roll-up. */}
        <span className={`chip ${d.gate?.complete ? "" : "blocked"}`}
          title={d.gate?.complete
            ? "All required modules built — structural completeness only, NOT a validation pass. Open the module builder and run eCTD validation before filing."
            : "Some required modules are not yet built"}>
          {d.gate?.complete
            ? `${passed}/${applic} modules built — validate to file`
            : `${passed}/${applic} modules built`}
        </span>
        <div style={{ display: "flex", gap: 6, alignItems: "center",
          flexWrap: "wrap", marginTop: 6 }}>
          {/* R9-CATALOG (n=7): REP request status on the tile itself */}
          <RepRequestChip d={d} />
          {/* R9-CATALOG (n=8): the named-clock due date, editable in place */}
          <DueClockCell d={d} onSaved={load} compact />
          {/* R9-CATALOG (n=4): per-dossier audit trail — view + export */}
          <button className="ghost" style={{ fontSize: 11, padding: "1px 6px" }}
            title={`View the immutable Part-11 audit trail for ${d.dossier_id}`}
            onClick={(e) => { e.preventDefault(); e.stopPropagation();
              router.push(`/dossiers/${encodeURIComponent(d.dossier_id)}/audit`); }}>
            Audit
          </button>
          <button className="ghost" style={{ fontSize: 11, padding: "1px 6px" }}
            title={`Export ${d.dossier_id}'s audit trail as an integrity-manifested CSV (for SOP records / inspections)`}
            onClick={(e) => { e.preventDefault(); e.stopPropagation();
              exportAuditCsv(d.dossier_id); }}>
            Export audit
          </button>
        </div>
        <button className="tile-delete" title={`Delete ${d.dossier_id}`}
          aria-label={`Delete dossier ${d.dossier_id}`}
          onClick={(e) => openDelete(e, d.dossier_id)}>✕</button>
      </Link>
    );
  }

  return (
    <>
      <TopNav subtitle="dossier manager" />
      <main className="dossier-home">
        <div style={{ display: "flex", alignItems: "baseline", gap: 12,
          flexWrap: "wrap" }}>
          <h1>Your product dossiers</h1>
          <span className="spacer" />
          <div className="seg" role="group" aria-label="View mode">
            <button className={viewMode === "grid" ? "on" : ""}
              aria-pressed={viewMode === "grid"}
              onClick={() => setViewMode("grid")}>Grid</button>
            <button className={viewMode === "list" ? "on" : ""}
              aria-pressed={viewMode === "list"}
              onClick={() => setViewMode("list")}>List</button>
          </div>
          {/* R9-CATALOG "'Trash' wording clashes with compliance-grade
              archive" (n=1): it is an Archive — recoverable records, not
              trash. */}
          <button className="ghost" onClick={() => {
            const next = !showArchived;
            setShowArchived(next);
            if (next) loadArchived();
          }}>
            {showArchived ? "Hide archive" : "View archive"}
          </button>
          <button onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancel" : "New dossier +"}
          </button>
        </div>
        <p className="mut" style={{ maxWidth: "64ch" }}>
          A <Term k="Dossier ID" /> is the permanent file for one product at Health
          Canada. Open a dossier to build its <Term k="eCTD" />{" "}
          <Term k="Module 1">Module 1–5</Term> — upload or author
          every document with full guidance on each section. Everything on this
          page belongs to your workspace alone: client workspaces are isolated
          end-to-end (per-workspace data partitions, tenant-checked on every
          request, cross-client access is structurally impossible) — see the
          proof and auditor exports in the Access &amp; isolation panel below.
        </p>
        {/* R9-CATALOG bilingual (n=2): honest French signposting — what IS
            first-class vs. what is not built yet. */}
        <p className="mut" style={{ maxWidth: "72ch", fontSize: 12.5 }}>
          <b>Bilingual (EN/FR):</b> French Product Monographs are first-class —
          the governed EN+FR pair at Module 1 (1.3.1) is checked and a missing
          French PM blocks transmission; bilingual form fields carry an
          EN&nbsp;+&nbsp;FR badge. Honest limit: the application interface
          itself is English-only today — a French UI is not built yet, and we
          say so rather than imply otherwise.
        </p>

        {creating && (
          <div className="card glass" style={{ maxWidth: 560, marginTop: 8 }}
            onKeyDown={(e) => {
              // R9-CATALOG (n=1): keyboard-fast entry — Enter creates & adds
              // another (Cmd/Ctrl+Enter creates & opens).
              if (e.key === "Enter" &&
                  (e.target as HTMLElement).tagName !== "BUTTON" &&
                  (e.target as HTMLElement).tagName !== "SELECT") {
                e.preventDefault();
                create(!(e.metaKey || e.ctrlKey));
              }
            }}>
            <h2 style={{ margin: "0 0 4px", fontSize: 17 }}>New dossier</h2>
            <div className="field-row">
              <div>
                <label>Dossier ID</label>
                <input id="new-dossier-id" value={did}
                  onChange={(e) => setDid(e.target.value)}
                  placeholder="e123456" />
                <p className="mut" style={{ fontSize: 12, margin: "4px 0 0" }}>
                  Format: one letter + 6–7 digits (e.g. <code>e123456</code>).
                  A <code>d…</code> placeholder marks a draft ID until Health
                  Canada issues the real one.
                </p>
                {/* R9-CATALOG "Dossier ID validation is format-only" (n=5):
                    say exactly what IS enforced — and what cannot be. */}
                <p className="mut" style={{ fontSize: 12, margin: "4px 0 0" }}>
                  Enforced at create: the format above, <b>uniqueness in this
                  workspace</b> (a live or archived dossier with the same ID is
                  rejected — restore the archived one instead), and your
                  workspace&apos;s admin-configured ID convention if one is
                  set. Honest limit: the pattern is modeled on REP&apos;s
                  issued-ID format — ANDS Studio cannot verify an ID against
                  Health Canada&apos;s REP records.
                </p>
              </div>
              <div>
                {/* R9-CATALOG bilingual (n=2): governed EN + FR product names */}
                <label>Product name (English)</label>
                <input value={title} onChange={(e) => setTitle(e.target.value)}
                  placeholder="Drugazole 10 mg tablet" />
                <label style={{ marginTop: 12 }}>Product name (French){" "}
                  <span className="mut" style={{ fontWeight: 400 }}>
                    (optional here; required for labelling)</span></label>
                <input value={titleFr}
                  onChange={(e) => setTitleFr(e.target.value)}
                  placeholder="Drugazole comprimé de 10 mg" />
              </div>
            </div>
            <div className="field-row">
              <div>
                <label>Submission type</label>
                <select value={subType}
                  onChange={(e) => setSubType(e.target.value)}
                  style={{ width: "100%" }}>
                  {SUBMISSION_TYPES.map((t) => (
                    <option key={t.code} value={t.code}>{t.label}</option>
                  ))}
                </select>
                {/* R9-CATALOG "Submission types and CS-BE undefined at the
                    point of choice" (n=10): every option's definition +
                    example is visible here — no hovering needed; the chosen
                    one is highlighted. */}
                <ul style={{ listStyle: "none", margin: "6px 0 0", padding: 0,
                  display: "grid", gap: 4 }}>
                  {SUBMISSION_TYPES.map((t) => (
                    <li key={t.code} style={{ fontSize: 12, lineHeight: 1.45,
                      opacity: subType === t.code ? 1 : 0.65 }}>
                      <b>{t.code}</b> — {t.def}{" "}
                      <span className="mut">{t.example}</span>
                    </li>
                  ))}
                </ul>
                {subType === "ANDS" && (
                  <label style={{ display: "flex", alignItems: "flex-start",
                    gap: 6, fontSize: 12, marginTop: 6, fontWeight: 400 }}>
                    <input type="checkbox" checked={csBeOnly}
                      style={{ width: "auto", marginTop: 2 }}
                      onChange={(e) => setCsBeOnly(e.target.checked)} />
                    <span>
                      {/* R9-CATALOG (n=10): CS-BE spelled out in full inline */}
                      <b>Comparative Studies – Bioequivalence</b>{" "}
                      (<Term k="CS-BE" />) path — your ANDS relies on
                      comparative BE studies only, which suppresses the
                      nonclinical/clinical summary sections. Example: a
                      standard generic tablet supported by a fasting/fed BE
                      study.
                    </span>
                  </label>
                )}
                {/* TIER-A: dosage form → comparative-evidence route. Shown for
                    the generic families (ANDS/SANDS) since it decides whether a
                    comparative BE (PK) study is required or a biowaiver may
                    apply — surfaced here, at the point of choice. */}
                {GENERIC_FAMILY.has(subType) && (
                  <div style={{ marginTop: 10 }}>
                    <label>Dosage form <span className="mut"
                      style={{ fontWeight: 400 }}>(comparative-evidence route)</span></label>
                    <select value={dosageForm}
                      onChange={(e) => setDosageForm(e.target.value)}
                      style={{ width: "100%" }}>
                      {DOSAGE_FORMS.map((d) => (
                        <option key={d.code} value={d.code}>{d.label}</option>
                      ))}
                    </select>
                    {(() => {
                      const d = DOSAGE_FORMS.find((x) => x.code === dosageForm);
                      if (!d) return null;
                      return d.requiresBe ? (
                        <p style={{ fontSize: 12, lineHeight: 1.45, margin: "6px 0 0" }}>
                          A comparative <b>bioequivalence (PK) study</b> is required
                          — sections 5.3.1 (study report) and 1.6 (CS-BE summary)
                          stay required.
                        </p>
                      ) : (
                        <p style={{ fontSize: 12, lineHeight: 1.45, margin: "6px 0 0" }}>
                          A <b>biowaiver / non-PK route</b> may apply — Health Canada
                          may waive the in-vivo BE study, so 5.3.1 and 1.6 become{" "}
                          <b>conditional</b>. You confirm the route for your product.
                        </p>
                      );
                    })()}
                  </div>
                )}
                {/* TIER-B: product class → honest scope. ANDS Studio authors a
                    GENERIC small-molecule chemical drug; other classes are real
                    HC regimes with different directorates/instruments. Say so at
                    the point of choice rather than pretending or offering a
                    hollow option. */}
                <div style={{ marginTop: 10 }}>
                  <label>Product class <span className="mut"
                    style={{ fontWeight: 400 }}>(regulatory scope)</span></label>
                  <select value={productClass}
                    onChange={(e) => setProductClass(e.target.value)}
                    style={{ width: "100%" }}>
                    {PRODUCT_CLASSES.map((p) => (
                      <option key={p.code} value={p.code}>{p.label}</option>
                    ))}
                  </select>
                  {(() => {
                    const p = PRODUCT_CLASSES.find((x) => x.code === productClass);
                    if (!p || p.inScope) return null;
                    return (
                      <div className="notice warn"
                        style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
                        <b>Outside ANDS Studio&apos;s core scope.</b> {p.note}
                      </div>
                    );
                  })()}
                </div>
              </div>
              <div>
                <label>Client / sponsor <span className="mut"
                  style={{ fontWeight: 400 }}>(optional)</span></label>
                <input value={sponsor} onChange={(e) => setSponsor(e.target.value)}
                  placeholder="Acme Pharma Inc." />
                <label style={{ marginTop: 12 }}>Owner (PM) <span className="mut"
                  style={{ fontWeight: 400 }}>(optional)</span></label>
                <input value={owner} onChange={(e) => setOwner(e.target.value)}
                  placeholder="j.smith@cro.example" />
                {/* R9-CATALOG (n=6): state plainly whether Owner drives
                    permissions. */}
                <p className="mut" style={{ fontSize: 12, margin: "4px 0 0" }}>
                  Owner is an <b>accountability label</b> (reassignable later
                  from the List view) — permissions come from workspace roles,
                  never from this field.
                </p>
                {/* R9-CATALOG bilingual (n=2): the accountable labelling owner */}
                <label style={{ marginTop: 12 }}>Labelling owner{" "}
                  <span className="mut" style={{ fontWeight: 400 }}>
                    (optional — who owns EN/FR labelling)</span></label>
                <input value={labellingOwner}
                  onChange={(e) => setLabellingOwner(e.target.value)}
                  placeholder="m.tremblay@cro.example" />
              </div>
            </div>
            <p className="mut" style={{ fontSize: 13, margin: "14px 0 0" }}>
              Health Canada issues your Dossier ID when you file a Dossier ID
              Request through <Term k="REP" /> (via your <Term k="CESG" />{" "}
              account).{" "}
              <button className="ghost" style={{ fontSize: 12, padding: "0 4px" }}
                onClick={usePlaceholder}>
                No ID yet? Start with a placeholder →
              </button>{" "}
              You can set the real ID any time; validation reminds you before
              filing.
            </p>
            <div className="cta-row" style={{ gap: 8, flexWrap: "wrap" }}>
              <button onClick={() => create(false)} disabled={busy}>
                {busy ? "Creating…" : "Create & open →"}
              </button>
              {/* R9-CATALOG (n=1): serial keyboard-fast entry (also Enter) */}
              <button className="ghost" onClick={() => create(true)}
                disabled={busy} title="Create this dossier and keep the form open for the next one (Enter does this too)">
                Create & add another (Enter)
              </button>
            </div>
            {/* R9-CATALOG (n=1): CSV bulk import for dozens at once */}
            <div style={{ marginTop: 12, borderTop: "1px solid var(--line)",
              paddingTop: 10 }}>
              <BulkDossierImport onDone={load} />
            </div>
          </div>
        )}

        {err && <div className="notice bad">{err}</div>}

        {/* R9-CATALOG "'Isolated end-to-end' claim asserted, not proven"
            (n=5): the proof — per-client access view + auditor exports. */}
        <AccessProofPanel items={items} />

        {loading ? (
          <div className="mut" style={{ marginTop: 20 }}>Loading dossiers…</div>
        ) : items.length === 0 ? (
          <div className="notice" style={{ marginTop: 16 }}>
            No dossiers yet. Create one to start building a submission.
          </div>
        ) : (
          <>
            {/* R9-CATALOG "Flat dossier list won't scale" (n=2): the explicit
                per-client/sponsor scope switcher, first-class on the catalog */}
            <SponsorScope items={items} value={sponsorScope}
              onChange={setSponsorScope} count={rows.length} />

            {/* R7 triage bar — search + "just my dossiers" for multi-sponsor PMs */}
            <div style={{ display: "flex", gap: 12, alignItems: "center",
              flexWrap: "wrap", margin: "14px 0 4px" }}>
              <input value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder="Filter by product, ID, type, client or owner…"
                aria-label="Filter dossiers"
                style={{ flex: "1 1 260px", maxWidth: 420 }} />
              {myEmail && (
                <label style={{ display: "flex", alignItems: "center", gap: 6,
                  fontSize: 13 }}>
                  <input type="checkbox" checked={mineOnly}
                    style={{ width: "auto" }}
                    onChange={(e) => setMineOnly(e.target.checked)} />
                  Just my dossiers
                </label>
              )}
              {/* R9-CATALOG (n=2): grouped/foldered tiles per client */}
              <label style={{ display: "flex", alignItems: "center", gap: 6,
                fontSize: 13 }}>
                <input type="checkbox" checked={groupByClient}
                  style={{ width: "auto" }}
                  onChange={(e) => setGroupByClient(e.target.checked)} />
                Group by client
              </label>
              <span className="mut" style={{ fontSize: 12 }}>
                {rows.length} of {items.length}
              </span>
            </div>

            {rows.length === 0 ? (
              <div className="notice" style={{ marginTop: 12 }}>
                No dossiers match your filter.
              </div>
            ) : viewMode === "grid" ? (
              grouped ? (
                <div style={{ display: "grid", gap: 14 }}>
                  {grouped.map(([client, ds]) => (
                    <section key={client} aria-label={`Client ${client}`}>
                      <div style={{ display: "flex", gap: 8,
                        alignItems: "baseline", margin: "8px 0 6px" }}>
                        <b style={{ fontSize: 14 }}>{client}</b>
                        <span className="mut" style={{ fontSize: 12 }}>
                          {ds.length} dossier{ds.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="dossier-grid">{ds.map(tile)}</div>
                    </section>
                  ))}
                </div>
              ) : (
                <div className="dossier-grid">{rows.map(tile)}</div>
              )
            ) : (
              <div className="table-wrap" style={{ overflowX: "auto",
                marginTop: 8 }}>
                <table className="dossier-table">
                  <thead>
                    <tr>
                      {([
                        ["dossier_id", "Dossier ID"],
                        ["title", "Product"],
                        ["status", "Status"],
                        ["submission_type", "Type"],
                        ["sponsor", "Client / sponsor"],
                        ["owner", "Owner"],
                        ["soonest_due", "Soonest due"],
                      ] as [SortKey, string][]).map(([k, lbl]) => (
                        <th key={k}>
                          <button className="th-sort" onClick={() => toggleSort(k)}
                            aria-label={`Sort by ${lbl}`}>
                            {lbl}{sortArrow(k)}
                          </button>
                        </th>
                      ))}
                      {/* R9-CATALOG (n=4): sequence/lifecycle + validation
                          columns; (n=2): language + labelling owner */}
                      <th>Seq / lifecycle</th>
                      <th>Validation</th>
                      <th>Language</th>
                      <th>Labelling owner</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((d) => {
                      const passed = d.tower.filter((t) => t.state === "pass").length;
                      const applic = d.tower.filter((t) => t.state !== "na").length;
                      const age = d.dossier_id.startsWith("d")
                        ? placeholderAgeDays(d) : null;
                      return (
                        <tr key={d.dossier_id}
                          onClick={() => router.push(
                            `/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`)}
                          style={{ cursor: "pointer" }}>
                          <td style={{ fontFamily: "ui-monospace,monospace" }}>
                            {d.dossier_id}
                            {d.dossier_id.startsWith("d") && (
                              <span className="chip placeholder-id" style={{ marginLeft: 6,
                                fontSize: 12 }} title="Placeholder ID — NOT a Health Canada Dossier ID; export/transmission blocked until the real ID is set">
                                {/* R9-CATALOG (n=4): show the placeholder's age */}
                                ⚠ placeholder{age !== null ? ` · day ${age + 1}` : ""}
                              </span>
                            )}
                            {/* R9-CATALOG (n=7): REP request status on the row */}
                            <span style={{ display: "block", marginTop: 2 }}>
                              <RepRequestChip d={d} />
                            </span>
                          </td>
                          <td>
                            {d.title}
                            {d.title_fr && (
                              <span className="mut" style={{ display: "block",
                                fontSize: 11.5 }}
                                title="Governed French product name">
                                FR: {d.title_fr}
                              </span>
                            )}
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            {/* R9-CATALOG (n=4): the chip now LINKS to the
                                validation step (module builder's validation
                                card, which names the profile + rule version
                                it runs against). Wording/tooltip preserved:
                                completeness is NOT a validation pass. */}
                            <Link href={`/dossiers/${encodeURIComponent(d.dossier_id)}/m/1`}
                              className={`chip ${d.gate?.complete ? "" : "blocked"}`}
                              title={d.gate?.complete
                                ? "Modules built (structural completeness) — not a validation pass; validate before filing. Opens the validation card (profile + ruleset version shown there)."
                                : "Some required modules not yet built. Opens the module builder."}>
                              {d.gate?.complete ? `${passed}/${applic} built` : `${passed}/${applic}`}
                            </Link>
                          </td>
                          <td>{typeLabel(d)}</td>
                          <td>{d.sponsor || <span className="mut">—</span>}</td>
                          <td onClick={(e) => e.stopPropagation()}>
                            {d.owner || <span className="mut">—</span>}
                            {/* R9-CATALOG (n=6): reassignable Owner (PM) —
                                accountability label; change is ledgered */}
                            <button className="ghost"
                              style={{ fontSize: 11, padding: "0 4px",
                                marginLeft: 4 }}
                              title={`Reassign the Owner (PM) for ${d.dossier_id} — an accountability label (permissions come from workspace roles); the change + reason land on the audit trail`}
                              aria-label={`Reassign owner for ${d.dossier_id}`}
                              onClick={() => { setOwnerTarget(d.dossier_id);
                                setOwnerValue(d.owner || "");
                                setOwnerReason(""); setModalErr(""); }}>
                              ✎
                            </button>
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            {/* R9-CATALOG (n=8): named-clock due date,
                                editable in place */}
                            <DueClockCell d={d} onSaved={load} />
                          </td>
                          <td>
                            {/* R9-CATALOG (n=4): eCTD lifecycle position */}
                            <span className="mut" style={{ fontSize: 12 }}
                              title={`Active working sequence ${d.lifecycle?.active_sequence || "0000"} of ${d.lifecycle?.sequence_count ?? 1} · regulatory purpose: ${d.lifecycle?.purpose || "initial"}`}>
                              seq {d.lifecycle?.active_sequence || "0000"}
                              {" "}({d.lifecycle?.purpose || "initial"}
                              {(d.lifecycle?.sequence_count ?? 1) > 1
                                ? ` · ${d.lifecycle?.sequence_count} seqs` : ""})
                            </span>
                          </td>
                          <td><ValidationCellBody d={d} /></td>
                          <td><BilingualBadge d={d} /></td>
                          <td>
                            {d.labelling_owner
                              || <span className="mut">—</span>}
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <span style={{ display: "inline-flex", gap: 4 }}>
                              {/* R9-CATALOG (n=4): audit view/export actions */}
                              <button className="ghost" style={{ fontSize: 11,
                                padding: "1px 6px" }}
                                title={`View the immutable Part-11 audit trail for ${d.dossier_id}`}
                                onClick={() => router.push(
                                  `/dossiers/${encodeURIComponent(d.dossier_id)}/audit`)}>
                                Audit
                              </button>
                              <button className="ghost" style={{ fontSize: 11,
                                padding: "1px 6px" }}
                                title="Export the audit trail (integrity-manifested CSV)"
                                onClick={() => exportAuditCsv(d.dossier_id)}>
                                Export
                              </button>
                              <button className="tile-delete" style={{
                                position: "static", opacity: 1 }}
                                title={`Delete ${d.dossier_id}`}
                                aria-label={`Delete dossier ${d.dossier_id}`}
                                onClick={(e) => openDelete(e, d.dossier_id)}>✕</button>
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* R9-CATALOG "No cost/timeline anchor for a filing" (n=2) — sourced
            Fees-Order figures + typical HC service standards. */}
        <CostTimelineAnchor />
        {/* R9-CATALOG "No portfolio-level rollup" (n=2): the missing due-date
            CALENDAR (rollup cards/exports live on Portfolio). */}
        <DueCalendar items={items} />

        {showArchived && (
          <section className="card glass" style={{ marginTop: 20, padding: 16 }}>
            {/* R9-CATALOG (n=1): 'Archive', not 'trash' — recoverable,
                compliance-grade records. */}
            <h2 style={{ margin: 0, fontSize: 17 }}>Archive (recoverable)</h2>
            <p className="mut" style={{ fontSize: 13, margin: "6px 0 0",
              maxWidth: "72ch" }}>
              Deleting a dossier archives it here rather than destroying it —
              nothing is purged. Restore any archived dossier to return it to
              your working list; every delete and restore is on the audit trail.
            </p>
            {archived.length === 0 ? (
              <div className="mut" style={{ marginTop: 12, fontSize: 13 }}>
                No archived dossiers.
              </div>
            ) : (
              <ul style={{ listStyle: "none", margin: "12px 0 0", padding: 0,
                display: "flex", flexDirection: "column", gap: 8 }}>
                {archived.map((a) => {
                  const adm = dueMeta(a.soonest_due);
                  return (
                    <li key={a.dossier_id} className="card" style={{
                      padding: "10px 14px", display: "flex", gap: 12,
                      alignItems: "baseline", flexWrap: "wrap" }}>
                      <b>{a.dossier_id}</b>
                      <span className="mut" style={{ fontSize: 13 }}>{a.title}</span>
                      {/* R9-CATALOG (n=8): the named-clock due flag reaches
                          the archived view too */}
                      {adm && (
                        <span className={adm.overdue ? "bad-text"
                          : adm.soon ? "warn-text" : "mut"}
                          style={{ fontSize: 12 }}
                          title={`${a.soonest_due_meta?.clock_type || "client-set target"}${a.soonest_due_meta?.item_title ? ` · ${a.soonest_due_meta.item_title}` : ""} · ${adm.iso}`}>
                          {adm.label}
                        </span>
                      )}
                      <span className="spacer" style={{ marginLeft: "auto" }} />
                      <span className="mut" style={{ fontSize: 12,
                        flexBasis: "100%" }}>
                        archived {a.archived_at ? new Date(a.archived_at)
                          .toLocaleString() : "—"}
                        {a.archived_by ? ` · by ${a.archived_by}` : ""}
                        {a.archive_reason ? ` · reason: ${a.archive_reason}` : ""}
                      </span>
                      {/* R9-CATALOG (n=4): audit actions on the archived list */}
                      <button className="ghost" style={{ fontSize: 12 }}
                        title={`View the immutable Part-11 audit trail for ${a.dossier_id}`}
                        onClick={() => router.push(
                          `/dossiers/${encodeURIComponent(a.dossier_id)}/audit`)}>
                        View audit trail
                      </button>
                      <button className="ghost" style={{ fontSize: 12 }}
                        title="Export the audit trail (integrity-manifested CSV)"
                        onClick={() => exportAuditCsv(a.dossier_id)}>
                        Export audit trail
                      </button>
                      <button onClick={() => { setRestoreTarget(a.dossier_id);
                        setRestoreSignName(""); setModalErr(""); }}>
                        Restore ↩
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        )}
      </main>

      {delTarget && (
        <Modal
          title="Delete this dossier?"
          onClose={() => setDelTarget(null)}
          footer={
            <>
              <button className="ghost" onClick={() => setDelTarget(null)}>
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={
                  modalBusy || delTyped.trim() !== delTarget ||
                  !delReason() || !delSignName.trim()
                }
              >
                {modalBusy ? "Archiving…" : "Sign & archive dossier"}
              </button>
            </>
          }
        >
          <p className="mut" style={{ fontSize: 13, marginTop: 0 }}>
            This does <b>not</b> permanently destroy the dossier — it moves{" "}
            <b>{delTarget}</b> and all of its documents to the recoverable
            archive, where it can be <b>restored with undo</b>. The action is
            recorded on the append-only audit trail.
          </p>
          <label style={{ fontSize: 13 }}>
            Type the Dossier ID <code>{delTarget}</code> to confirm
          </label>
          <input
            value={delTyped}
            autoFocus
            onChange={(e) => setDelTyped(e.target.value)}
            placeholder={delTarget}
            style={{ width: "100%", marginTop: 4 }}
          />
          {/* R9-CATALOG "Archive/delete reason is pure free text" (n=2):
              controlled vocabulary + optional free-text detail — reasons stay
              auditable and consistent. Reason remains REQUIRED. */}
          <label style={{ fontSize: 13, marginTop: 10, display: "block" }}>
            Reason for change (required)
          </label>
          <select value={delReasonCode}
            onChange={(e) => setDelReasonCode(e.target.value)}
            style={{ width: "100%", marginTop: 4 }}>
            <option value="">— select a reason —</option>
            {ARCHIVE_REASONS.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <input
            value={delDetail}
            onChange={(e) => setDelDetail(e.target.value)}
            placeholder="optional detail (recorded verbatim on the trail)"
            style={{ width: "100%", marginTop: 6 }}
          />
          {/* R9-CATALOG (n=6): typed-name e-signature capture. HONEST: a
              typed-name record (name + UTC + meaning on the ledger), not a
              cryptographic certificate. */}
          <label style={{ fontSize: 13, marginTop: 10, display: "block" }}>
            E-signature — type your full name (required)
          </label>
          <input
            value={delSignName}
            onChange={(e) => setDelSignName(e.target.value)}
            placeholder="your full name"
            style={{ width: "100%", marginTop: 4 }}
          />
          <p className="mut" style={{ fontSize: 12, margin: "4px 0 0" }}>
            Signing meaning: &ldquo;I authorize archiving dossier{" "}
            {delTarget}&rdquo;. Recorded verbatim (typed-name capture) with
            actor + UTC on the durable audit ledger.
          </p>
          {modalErr && (
            <div className="notice bad" style={{ marginTop: 10 }}>{modalErr}</div>
          )}
        </Modal>
      )}

      {restoreTarget && (
        <Modal
          title={`Restore ${restoreTarget}?`}
          onClose={() => setRestoreTarget(null)}
          footer={
            <>
              <button className="ghost" onClick={() => setRestoreTarget(null)}>
                Cancel
              </button>
              <button onClick={confirmRestore}
                disabled={modalBusy || !restoreSignName.trim()}>
                {modalBusy ? "Restoring…" : "Sign & restore"}
              </button>
            </>
          }
        >
          <p className="mut" style={{ fontSize: 13, marginTop: 0 }}>
            Returns <b>{restoreTarget}</b> to the working catalog. The restore
            is recorded on the audit trail; the original archive record is
            never erased.
          </p>
          {/* R9-CATALOG (n=6): typed-name e-signature capture on restore */}
          <label style={{ fontSize: 13, display: "block" }}>
            E-signature — type your full name (required)
          </label>
          <input
            value={restoreSignName}
            autoFocus
            onChange={(e) => setRestoreSignName(e.target.value)}
            placeholder="your full name"
            style={{ width: "100%", marginTop: 4 }}
          />
          <p className="mut" style={{ fontSize: 12, margin: "4px 0 0" }}>
            Signing meaning: &ldquo;I authorize restoring dossier{" "}
            {restoreTarget}&rdquo;. Recorded verbatim (typed-name capture) on
            the durable audit ledger.
          </p>
          {modalErr && (
            <div className="notice bad" style={{ marginTop: 10 }}>{modalErr}</div>
          )}
        </Modal>
      )}

      {ownerTarget && (
        <Modal
          title={`Reassign owner — ${ownerTarget}`}
          onClose={() => setOwnerTarget(null)}
          footer={
            <>
              <button className="ghost" onClick={() => setOwnerTarget(null)}>
                Cancel
              </button>
              <button onClick={confirmOwner}
                disabled={modalBusy || !ownerReason.trim()}>
                {modalBusy ? "Saving…" : "Save owner"}
              </button>
            </>
          }
        >
          {/* R9-CATALOG (n=6): Owner drives ACCOUNTABILITY, not permissions —
              stated at the point of change; old/new land on the ledger. */}
          <p className="mut" style={{ fontSize: 13, marginTop: 0 }}>
            Owner (PM) is an <b>accountability label</b> — who answers for this
            dossier. It never grants or removes permissions (workspace roles
            do). The change and your reason are recorded on the audit trail.
          </p>
          <label style={{ fontSize: 13 }}>New owner (empty = unassign)</label>
          <input value={ownerValue} autoFocus
            onChange={(e) => setOwnerValue(e.target.value)}
            placeholder="p.nair@cro.example"
            style={{ width: "100%", marginTop: 4 }} />
          <label style={{ fontSize: 13, marginTop: 10, display: "block" }}>
            Reason (required)
          </label>
          <input value={ownerReason}
            onChange={(e) => setOwnerReason(e.target.value)}
            placeholder="e.g. PM handover at sponsor request"
            style={{ width: "100%", marginTop: 4 }} />
          {modalErr && (
            <div className="notice bad" style={{ marginTop: 10 }}>{modalErr}</div>
          )}
        </Modal>
      )}

      {renameTarget && (
        <SetRealDossierIdModal
          dossierId={renameTarget}
          seedCompany={renameSeedCompany}
          seedSponsor={renameSeedSponsor}
          onClose={() => setRenameTarget(null)}
          onRenamed={async () => {
            setRenameTarget(null);
            await load();
          }}
        />
      )}
    </>
  );
}

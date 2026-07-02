"use client";
import Link from "next/link";
import { UserChip } from "@/components/UserChip";
import { useParams } from "next/navigation";
import { useDossier } from "./DossierContext";

const MODULES = ["1", "2", "3", "4", "5"];

export function DossierHeader() {
  const { dossierId, index, content } = useDossier();
  const params = useParams();
  const active = String((params as any)?.module || "");
  const towerByMod = Object.fromEntries((content?.tower || []).map((t) => [t.module, t]));

  return (
    <header className="topbar">
      <span className="brand">
        <span className="dot" aria-hidden />
        <Link href="/dossiers" style={{ color: "inherit" }}>ANDS&nbsp;Studio</Link>
        <small>· {index?.title || dossierId}</small>
      </span>
      <nav className="module-tabs" aria-label="Modules">
        {MODULES.map((m) => {
          const t = towerByMod[m];
          const state = t?.state || "todo";
          return (
            <Link key={m}
              href={`/dossiers/${encodeURIComponent(dossierId)}/m/${m}`}
              className={`mtab ${state} ${active === m ? "active" : ""}`}
              aria-current={active === m ? "page" : undefined}>
              <span className={`d ${state}`} aria-hidden>
                {state === "pass" ? "✓" : state === "na" ? "—" : "●"}
              </span>
              M{m}
            </Link>
          );
        })}
      </nav>
      <span className="spacer" />
      <UserChip />
      <Link className="chip" href={`/dossiers/${encodeURIComponent(dossierId)}/viewer`}>
        Application Viewer
      </Link>
      <Link className="chip" href={`/dossiers/${encodeURIComponent(dossierId)}/audit`}>Audit</Link>
      <Link className="chip" href="/portfolio">Portfolio</Link>
      <Link className="chip" href="/">Journey</Link>
    </header>
  );
}

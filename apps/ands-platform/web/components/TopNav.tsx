"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, FolderTree, LayoutGrid, BadgeCheck, Mail, BookOpen } from "lucide-react";
import { UserChip } from "./UserChip";

// eCTD-native nav: a dossier IS the Module 1-5 tree (FolderTree); the registry
// tracks DIN / marketed status (BadgeCheck); correspondence is HC notices
// (Mail); Help is the regulatory reference (BookOpen).
const NAV = [
  { href: "/", label: "Journey", icon: Compass, exact: true },
  { href: "/dossiers", label: "Dossiers", icon: FolderTree },
  { href: "/portfolio", label: "Portfolio", icon: LayoutGrid },
  { href: "/registry", label: "Registry", icon: BadgeCheck },
  { href: "/correspondence", label: "Correspondence", icon: Mail },
  { href: "/help", label: "Help", icon: BookOpen },
];

// Shared, iconified top nav used on every authenticated page — single source of
// truth (was duplicated + inconsistent per page). Highlights the active route.
export function TopNav({ subtitle, extra }: { subtitle?: string; extra?: React.ReactNode }) {
  const path = usePathname() || "/";
  return (
    <header className="topbar">
      <Link href="/" className="brand" style={{ textDecoration: "none", color: "inherit" }}>
        <span className="dot" aria-hidden />
        ANDS&nbsp;Studio{subtitle ? <small>· {subtitle}</small> : null}
      </Link>
      <nav className="topnav" aria-label="Primary">
        {NAV.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? path === href : path === href || path.startsWith(href + "/");
          return (
            <Link key={href} href={href}
              className={`chip nav-chip${active ? " nav-chip-active" : ""}`}
              aria-current={active ? "page" : undefined}>
              <Icon size={14} aria-hidden /> {label}
            </Link>
          );
        })}
      </nav>
      <span className="spacer" />
      {extra}
      <UserChip />
    </header>
  );
}

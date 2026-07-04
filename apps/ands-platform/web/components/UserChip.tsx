"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ChevronDown, ShieldCheck, LogOut } from "lucide-react";
import { auth, tenantName, type Principal } from "@/lib/auth";
import { toast } from "sonner";

export function UserChip() {
  const router = useRouter();
  const [me, setMe] = useState<Principal | null>(null);

  useEffect(() => {
    auth.me().then(setMe).catch(() => setMe(null));
  }, []);

  if (!me) return null;
  // workspace name comes from the account record (server), with the old
  // localStorage value only as a fallback for sessions predating the field
  const tenant = me.tenant_name || tenantName();
  const initial = (me.email.trim()[0] || "?").toUpperCase();

  async function signOut() {
    await auth.logout();
    toast.success("Signed out");
    router.push("/login");
    router.refresh();
  }

  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button className="user-chip" aria-label="Account menu">
          <span className="uc-avatar" aria-hidden>{initial}</span>
          <span className="uc-meta">
            <b className="uc-id">{me.email}</b>
            {tenant ? <small className="mut">{tenant}</small> : null}
          </span>
          <ChevronDown size={14} className="mut uc-caret" aria-hidden />
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content className="menu" sideOffset={8} align="end">
          <div className="menu-head">
            <b>{me.email}</b>
            {tenant ? <small className="mut">{tenant}</small> : null}
          </div>
          <Dropdown.Item className="menu-item" onSelect={() => router.push("/account")}>
            <ShieldCheck size={15} aria-hidden /> Account &amp; security
          </Dropdown.Item>
          <Dropdown.Separator className="menu-sep" />
          <Dropdown.Item className="menu-item danger" onSelect={signOut}>
            <LogOut size={15} aria-hidden /> Sign out
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

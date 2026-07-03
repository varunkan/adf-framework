"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { auth, tenantName, type Principal } from "@/lib/auth";

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
  return (
    <span className="user-chip">
      <Link className="uc-id" href="/account"
        title="Account & security (workspace, MFA)"
        style={{ textDecoration: "none", color: "inherit" }}>
        <b>{me.email}</b>
        {tenant ? <small className="mut"> · {tenant}</small> : null}
      </Link>
      <button className="ghost uc-out" title="Sign out"
        onClick={async () => { await auth.logout(); router.push("/login"); router.refresh(); }}>
        Sign out
      </button>
    </span>
  );
}

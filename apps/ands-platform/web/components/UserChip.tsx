"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth, tenantName, type Principal } from "@/lib/auth";

export function UserChip() {
  const router = useRouter();
  const [me, setMe] = useState<Principal | null>(null);
  const [tenant, setTenant] = useState("");

  useEffect(() => {
    auth.me().then((p) => { setMe(p); setTenant(tenantName()); })
      .catch(() => setMe(null));
  }, []);

  if (!me) return null;
  return (
    <span className="user-chip">
      <span className="uc-id">
        <b>{me.email}</b>
        {tenant ? <small className="mut"> · {tenant}</small> : null}
      </span>
      <button className="ghost uc-out" title="Sign out"
        onClick={async () => { await auth.logout(); router.push("/login"); router.refresh(); }}>
        Sign out
      </button>
    </span>
  );
}

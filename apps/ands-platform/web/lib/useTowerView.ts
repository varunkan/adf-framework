"use client";
// WS6: persisted preference for the submission-tower presentation. Round-4
// PM/CDMO personas called the 3D tower a gimmick that "undermines regulatory
// seriousness" — so the 3D view becomes OPTIONAL (not removed): a filer can
// switch to a plain, printable module→requirement checklist and that choice
// sticks across navigation and sessions (localStorage).
// Round-6 WS-A (density reduction): the CALM default is now the plain
// printable checklist — the 3D tower is opt-in ("too dense / a construction
// site"). The choice still persists; a filer who prefers 3D toggles once.
import { useEffect, useState } from "react";

export type TowerView = "tower" | "checklist";
const KEY = "ands.towerView";

export function useTowerView(): [TowerView, (v: TowerView) => void] {
  // default to the plain checklist (calm) until a stored choice loads —
  // reading localStorage during SSR/first paint would hydration-mismatch.
  const [view, setView] = useState<TowerView>("checklist");
  useEffect(() => {
    try {
      const v = window.localStorage.getItem(KEY);
      if (v === "checklist" || v === "tower") setView(v);
    } catch { /* storage unavailable — keep default */ }
  }, []);
  const set = (v: TowerView) => {
    setView(v);
    try { window.localStorage.setItem(KEY, v); } catch { /* ignore */ }
  };
  return [view, set];
}

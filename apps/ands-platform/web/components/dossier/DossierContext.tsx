"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { ContentState, DossierIndex } from "@/lib/dossierTypes";

interface DossierCtx {
  dossierId: string;
  index: DossierIndex | null;
  content: ContentState | null;
  loading: boolean;
  error: string;
  setContent: (c: ContentState) => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<DossierCtx | null>(null);

export function DossierProvider({
  dossierId,
  children,
}: {
  dossierId: string;
  children: React.ReactNode;
}) {
  const [index, setIndex] = useState<DossierIndex | null>(null);
  const [content, setContent] = useState<ContentState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const full = await dossierApi.getDossier(dossierId);
      setIndex(full.index);
      setContent(full.content);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <Ctx.Provider
      value={{ dossierId, index, content, loading, error, setContent, refresh }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useDossier(): DossierCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useDossier must be used within a DossierProvider");
  return c;
}

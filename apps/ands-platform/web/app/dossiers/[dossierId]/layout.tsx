"use client";
import { DossierProvider } from "@/components/dossier/DossierContext";
import { DossierHeader } from "@/components/dossier/DossierHeader";

export default function DossierLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { dossierId: string };
}) {
  const id = decodeURIComponent(params.dossierId);
  return (
    <DossierProvider dossierId={id}>
      <DossierHeader />
      {children}
    </DossierProvider>
  );
}

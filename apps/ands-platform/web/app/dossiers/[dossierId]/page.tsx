import { redirect } from "next/navigation";

export default function DossierIndexPage({
  params,
}: {
  params: { dossierId: string };
}) {
  redirect(`/dossiers/${params.dossierId}/m/1`);
}

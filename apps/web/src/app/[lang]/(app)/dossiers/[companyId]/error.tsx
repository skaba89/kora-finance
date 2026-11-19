"use client";

import { useParams } from "next/navigation";

import { ErrorScreen } from "@/components/error-screen";

/** Boundary du dossier : le retour propose le tableau de bord du dossier courant. */
export default function CompanyError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const { companyId } = useParams<{ companyId: string }>();
  return <ErrorScreen error={error} reset={reset} backHref={`/dossiers/${companyId}`} />;
}

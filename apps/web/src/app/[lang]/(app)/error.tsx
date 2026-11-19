"use client";

import { ErrorScreen } from "@/components/error-screen";

/** Boundary de la zone applicative : la navigation (header, dossier courant) reste affichée. */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ErrorScreen error={error} reset={reset} backHref="/dossiers" />;
}

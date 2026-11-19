"use client";

import { ErrorScreen } from "@/components/error-screen";

/** Boundary racine sous [lang] : l'écran de connexion et les pages publiques. */
export default function LangError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ErrorScreen error={error} reset={reset} />;
}

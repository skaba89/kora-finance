"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { getClientDictionary } from "@/lib/i18n/client";

/**
 * Écran d'erreur applicatif, partagé par les trois boundaries
 * ([lang], (app), dossiers/[companyId]). Le layout parent reste affiché :
 * l'utilisateur ne perd ni sa navigation ni son contexte. Aucun détail
 * technique n'est exposé hors du bloc repliable réservé au support.
 */
export function ErrorScreen({
  error,
  reset,
  backHref,
}: {
  error: Error & { digest?: string };
  reset: () => void;
  backHref?: string;
}) {
  const { lang } = useParams<{ lang: string }>();
  const t = getClientDictionary(lang);

  useEffect(() => {
    // Journal console (digest utile avec les journaux serveur) — jamais
    // d'appel réseau : le boundary doit rester fiable même quand l'API tombe.
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-16 text-center">
      <p role="alert" className="text-2xl font-semibold tracking-tight">
        {t.errors.title}
      </p>
      <p className="text-muted-foreground text-sm">{t.errors.description}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Button onClick={reset}>{t.errors.retry}</Button>
        {backHref ? (
          <Button variant="outline" asChild>
            <Link href={backHref}>{t.errors.backToCompany}</Link>
          </Button>
        ) : null}
      </div>
      {error.digest || error.message ? (
        <details className="text-muted-foreground mt-2 w-full text-left text-xs">
          <summary className="cursor-pointer select-none">{t.errors.detailsSummary}</summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-2 whitespace-pre-wrap break-words">
            {error.digest ? `digest: ${error.digest}\n` : ""}
            {error.message}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

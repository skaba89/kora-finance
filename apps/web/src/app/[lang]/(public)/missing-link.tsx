import Link from "next/link";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { Dictionary } from "@/lib/i18n/server";

/** Lien absent ou tronqué (copie partielle depuis un client mail). */
export function MissingLink({ t, retryHref }: { t: Dictionary; retryHref?: string }) {
  return (
    <div className="flex flex-col gap-4">
      <Alert variant="destructive" role="alert">
        <AlertDescription>{t.auth.missingLink}</AlertDescription>
      </Alert>
      {retryHref ? (
        <Link href={retryHref} className="text-sm underline underline-offset-4">
          {t.auth.newRequest}
        </Link>
      ) : null}
    </div>
  );
}

import { getDictionary } from "@/lib/i18n/server";
import { WifiOff } from "lucide-react";

import { RetryButton } from "./retry-button";

export default async function OfflinePage() {
  const { t } = await getDictionary();
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <div className="rounded-2xl bg-warning/10 p-4 text-warning"><WifiOff aria-hidden="true" className="size-8" /></div>
      <h1 className="text-2xl font-semibold">{t.offline.title}</h1>
      <p className="text-muted-foreground">{t.offline.body}</p>
      <RetryButton label={t.offline.retry} />
      {/* Navigation complète : servie par le service worker sans réseau (pas de <Link>). */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a href="/hors-connexion/saisie" className="inline-flex min-h-11 items-center text-sm text-primary underline underline-offset-4">
        {t.offline.enterOffline}
      </a>
    </main>
  );
}

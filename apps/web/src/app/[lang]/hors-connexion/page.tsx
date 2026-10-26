import { getDictionary } from "@/lib/i18n/server";

import { RetryButton } from "./retry-button";

export default async function OfflinePage() {
  const { t } = await getDictionary();
  return (
    <main className="mx-auto flex max-w-md flex-1 flex-col justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">{t.offline.title}</h1>
      <p className="text-muted-foreground">{t.offline.body}</p>
      <RetryButton label={t.offline.retry} />
      {/* Navigation complète : servie par le service worker sans réseau (pas de <Link>). */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a href="/hors-connexion/saisie" className="text-sm underline underline-offset-4">
        {t.offline.enterOffline}
      </a>
    </main>
  );
}

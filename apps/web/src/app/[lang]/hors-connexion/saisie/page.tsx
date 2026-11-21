import type { Metadata } from "next";

import { editorLabels } from "@/components/ledger/labels";
import { OfflineEntry } from "@/components/offline/offline-entry";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.offline.pageTitle };
}

/**
 * Saisie hors connexion. Page publique et statique (aucune donnée serveur, aucune
 * session) : le service worker la conserve pour qu'elle s'ouvre sans réseau. Les données
 * viennent de l'appareil, préparé au préalable depuis le dossier (en ligne).
 */
export default async function OfflineEntryPage() {
  const { t, locale } = await getDictionary();
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-5xl flex-1 flex-col gap-6 px-4 py-6">
      <header className="flex flex-col gap-1">
        <p className="font-semibold tracking-tight text-primary">{t.common.appName}</p>
        <h1 className="text-2xl font-semibold">{t.offline.pageTitle}</h1>
        <p className="text-muted-foreground">{t.offline.pageSubtitle}</p>
      </header>
      <OfflineEntry labels={t.offline} guidedLabels={t.guided} editorLabels={editorLabels(t)} locale={locale} />
    </main>
  );
}

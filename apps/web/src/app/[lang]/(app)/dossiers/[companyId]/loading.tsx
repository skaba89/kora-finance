import { PageSkeleton } from "@/components/page-header";

/** Chargement d'un dossier : squelette de la navigation latérale et de la
 * page, identique aux états de suspension du layout du dossier — la
 * disposition ne bouge pas quand le contenu arrive. */
export default function Loading() {
  return (
    <div className="flex flex-1 flex-col gap-6 md:flex-row">
      <aside className="hidden md:block md:w-56 md:shrink-0">
        <div className="bg-muted h-64 animate-pulse rounded" aria-hidden />
      </aside>
      <section className="min-w-0 flex-1">
        <PageSkeleton />
      </section>
    </div>
  );
}

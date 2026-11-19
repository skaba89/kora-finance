import { PageSkeleton } from "@/components/page-header";

/** Chargement de l'espace connecté : le squelette reproduit l'en-tête et la
 * colonne de contenu de la disposition connectée — l'utilisateur voit une
 * page qui se construit, jamais un écran vide. */
export default function Loading() {
  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <div className="bg-muted h-6 w-32 animate-pulse rounded" aria-hidden />
          <div className="bg-muted h-8 w-40 animate-pulse rounded" aria-hidden />
        </div>
      </div>
      <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <PageSkeleton />
      </div>
    </div>
  );
}

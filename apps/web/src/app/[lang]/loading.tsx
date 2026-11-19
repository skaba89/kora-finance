import { PageSkeleton } from "@/components/page-header";

/** Chargement du segment racine : le squelette reprend la largeur et le
 * rythme du contenu final pour éviter tout saut visuel pendant la
 * résolution de la page. */
export default function Loading() {
  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <PageSkeleton />
    </div>
  );
}

import { connection } from "next/server";
import { Suspense } from "react";

import { ApiStatusBadge } from "@/components/api-status";
import { createApiClient } from "@/lib/api/client";
import { getApiHealth } from "@/lib/api/health";

async function ApiStatus() {
  // Statut lu à chaque requête, jamais figé au build.
  await connection();
  const health = await getApiHealth(createApiClient());
  return <ApiStatusBadge health={health} />;
}

export default function HomePage() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 py-12">
      <h1 className="text-3xl font-semibold tracking-tight">Kora Finance</h1>
      <p className="text-muted-foreground">
        Gestion financière et comptable pour les PME guinéennes, conforme au SYSCOHADA
        révisé.
      </p>
      <section className="flex items-center gap-3" aria-labelledby="statut-api">
        <h2 id="statut-api" className="text-sm font-medium">
          Statut de l&apos;API
        </h2>
        <Suspense fallback={<span className="text-sm">Vérification…</span>}>
          <ApiStatus />
        </Suspense>
      </section>
    </main>
  );
}

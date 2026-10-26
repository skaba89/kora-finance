"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { syncOfflineItemAction } from "@/lib/actions/offline";
import { interpolate } from "@/lib/i18n/interpolate";
import type { Dictionary } from "@/lib/i18n/server";
import { counts, type QueueItem } from "@/lib/offline/model";
import { listItems, offlineSupported, onChange, setCurrentUser } from "@/lib/offline/store";
import { syncPending } from "@/lib/offline/sync";

/** Envoi d'une saisie de la file par la Server Action (jamais de validation). */
export function sendItem(item: QueueItem) {
  return syncOfflineItemAction({ companyId: item.companyId, id: item.id, kind: item.kind, payload: item.payload });
}

/** Demande au service worker de rafraîchir la page de saisie hors connexion (nouvelle version). */
function refreshOfflineShell() {
  try {
    if (sessionStorage.getItem("kora-offline-shell") === "1") return;
    sessionStorage.setItem("kora-offline-shell", "1");
  } catch {
    // Stockage de session indisponible : rafraîchissement à chaque page, sans gravité.
  }
  void navigator.serviceWorker?.ready.then((registration) =>
    registration.active?.postMessage({ type: "refresh-offline-shell" }),
  );
}

/**
 * Présent sur toutes les pages connectées : retient l'utilisateur de l'appareil, envoie
 * les saisies faites hors connexion (au chargement et au retour du réseau) et signale
 * celles qui attendent ou ont été refusées.
 */
export function OfflineSync({ userId, labels }: { userId: string; labels: Dictionary["offline"] }) {
  const router = useRouter();
  const running = useRef(false);
  const [state, setState] = useState<{ pending: number; rejected: number; companyId: string | null }>({
    pending: 0,
    rejected: 0,
    companyId: null,
  });

  const refreshCounts = useCallback(async () => {
    const items = await listItems(userId);
    const { pending, rejected } = counts(items);
    const first = items.find((i) => i.status !== "synced");
    setState({ pending, rejected, companyId: first?.companyId ?? null });
  }, [userId]);

  const sync = useCallback(async () => {
    if (running.current || !navigator.onLine) return;
    running.current = true;
    try {
      const report = await syncPending(userId, sendItem);
      if (report.synced > 0) router.refresh();
    } finally {
      running.current = false;
      await refreshCounts();
    }
  }, [userId, router, refreshCounts]);

  useEffect(() => {
    if (!offlineSupported()) return;
    let active = true;
    void (async () => {
      await setCurrentUser(userId);
      if (!active) return;
      refreshOfflineShell();
      await sync();
    })().catch((error: unknown) => console.error("Synchronisation hors connexion impossible", error));
    const online = () => void sync().catch((error: unknown) => console.error(error));
    window.addEventListener("online", online);
    const stop = onChange(() => void refreshCounts().catch((error: unknown) => console.error(error)));
    return () => {
      active = false;
      window.removeEventListener("online", online);
      stop();
    };
  }, [userId, sync, refreshCounts]);

  if (state.pending === 0 && state.rejected === 0) return null;
  return (
    <div className="border-b bg-sky-50 text-sky-950" role="status">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        {state.pending > 0 ? <p>{interpolate(labels.banner, { n: state.pending })}</p> : null}
        {state.rejected > 0 ? <p>{interpolate(labels.bannerRejected, { n: state.rejected })}</p> : null}
        {state.companyId ? (
          <a href={`/dossiers/${state.companyId}/hors-connexion`} className="underline underline-offset-4">
            {labels.bannerLink}
          </a>
        ) : null}
      </div>
    </div>
  );
}

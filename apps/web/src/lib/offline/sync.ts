import { applyOutcome, expiredSynced, type QueueItem, type SyncOutcome, toSync } from "./model";
import { deleteItem, getItem, listItems, putItem } from "./store";

export type SyncReport = { synced: number; rejected: number; stopped: "auth" | "offline" | null };

type Send = (item: QueueItem) => Promise<SyncOutcome>;

/**
 * Envoie les saisies en attente de l'utilisateur, une par une et dans l'ordre. S'arrête
 * au premier problème de réseau (on réessaiera) ou de session (il faut se reconnecter).
 * Un verrou entre onglets (Web Locks) évite deux envois simultanés ; même sans lui,
 * l'identifiant de chaque saisie empêche tout doublon côté serveur.
 */
export async function syncPending(userId: string, send: Send, now: () => Date = () => new Date()): Promise<SyncReport> {
  const run = () => syncAll(userId, send, now);
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request(`kora-offline-sync:${userId}`, run);
  }
  return run();
}

async function syncAll(userId: string, send: Send, now: () => Date): Promise<SyncReport> {
  const items = await listItems(userId);
  for (const old of expiredSynced(items, now())) await deleteItem(old.id);

  const report: SyncReport = { synced: 0, rejected: 0, stopped: null };
  for (const item of toSync(items)) {
    let outcome: SyncOutcome;
    try {
      outcome = await send(item);
    } catch {
      // Server Action injoignable (réseau coupé, serveur redémarré) : plus tard.
      outcome = { status: "retry" };
    }
    if (outcome.status === "auth" || outcome.status === "retry") {
      report.stopped = outcome.status === "auth" ? "auth" : "offline";
      break;
    }
    const next = applyOutcome(item, outcome, now());
    // Saisie retirée pendant l'envoi : on ne la recrée pas sur l'appareil.
    if (next && (await getItem(userId, item.id))) await putItem(next);
    if (outcome.status === "synced") report.synced += 1;
    else report.rejected += 1;
  }
  return report;
}

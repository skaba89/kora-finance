import type { components } from "@/lib/api/schema";
import type { EntryIn, GuidedIn } from "@/lib/payloads";

/**
 * Saisie hors connexion : modèle et règles, sans accès au navigateur (testés en unitaire).
 *
 * Principe : hors connexion on SAISIT, on ne valide rien. Chaque saisie part dans une
 * file d'attente sur l'appareil ; au retour du réseau elle est envoyée et devient un
 * brouillon ordinaire, créé une seule fois grâce à son identifiant (idempotence).
 */

/** Durée de validité des données du dossier conservées sur l'appareil. */
export const SNAPSHOT_DAYS = 7;
/** Durée pendant laquelle une saisie synchronisée reste listée (lien vers le brouillon). */
export const SYNCED_RETENTION_DAYS = 7;

const DAY_MS = 24 * 60 * 60 * 1000;

export type SnapshotJournal = { id: string; code: string; label: string };
export type SnapshotAccount = { id: string; number: string; label: string };
export type SnapshotFiscalYear = { start_date: string; end_date: string };

/** Données d'un dossier nécessaires à la saisie, téléchargées à la demande (en ligne). */
export type Snapshot = {
  version: 1;
  userId: string;
  companyId: string;
  companyName: string;
  currency: string;
  fetchedAt: string;
  expiresAt: string;
  journals: SnapshotJournal[];
  accounts: SnapshotAccount[];
  /** Exercices ouverts : la date saisie est signalée si elle n'en fait pas partie. */
  openFiscalYears: SnapshotFiscalYear[];
  guided: components["schemas"]["GuidedOptions"];
};

export type QueueStatus = "pending" | "rejected" | "synced";

type Base = {
  /** Identifiant de l'écriture qui sera créée (clé d'idempotence). */
  id: string;
  userId: string;
  companyId: string;
  createdAt: string;
  updatedAt: string;
  status: QueueStatus;
  /** Refus du serveur (saisie à corriger ou à abandonner). */
  message?: string;
  errors?: string[];
  /** Brouillon créé (statut synced). */
  entryId?: string;
  syncedAt?: string;
};

export type QueueItem = (Base & { kind: "free"; payload: EntryIn }) | (Base & { kind: "guided"; payload: GuidedIn });

/** Résultat de l'envoi d'une saisie (Server Action de synchronisation). */
export type SyncOutcome =
  | { status: "synced"; entryId: string }
  | { status: "rejected"; message: string; errors: string[] }
  /** Réseau ou serveur indisponible : on réessaiera plus tard. */
  | { status: "retry" }
  /** Session expirée : il faut se reconnecter. */
  | { status: "auth" };

export function snapshotExpiry(fetchedAt: Date): string {
  return new Date(fetchedAt.getTime() + SNAPSHOT_DAYS * DAY_MS).toISOString();
}

export function isExpired(snapshot: Pick<Snapshot, "expiresAt">, now: Date): boolean {
  return Date.parse(snapshot.expiresAt) <= now.getTime();
}

/** Date hors de tout exercice ouvert : avertissement (le serveur tranchera). */
export function outsideOpenYears(date: string, years: SnapshotFiscalYear[]): boolean {
  return !years.some((y) => y.start_date <= date && date <= y.end_date);
}

/** Nouvel état d'une saisie après une tentative d'envoi ; null = inchangée. */
export function applyOutcome(item: QueueItem, outcome: SyncOutcome, now: Date): QueueItem | null {
  const at = now.toISOString();
  switch (outcome.status) {
    case "synced":
      return {
        ...item,
        status: "synced",
        entryId: outcome.entryId,
        syncedAt: at,
        updatedAt: at,
        message: undefined,
        errors: undefined,
      };
    case "rejected":
      return { ...item, status: "rejected", message: outcome.message, errors: outcome.errors, updatedAt: at };
    case "retry":
    case "auth":
      return null;
  }
}

/** Saisies à envoyer, dans l'ordre où elles ont été faites. */
export function toSync(items: QueueItem[]): QueueItem[] {
  return items.filter((i) => i.status === "pending").sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** Saisies synchronisées depuis plus longtemps que la durée de rétention. */
export function expiredSynced(items: QueueItem[], now: Date): QueueItem[] {
  return items.filter(
    (i) => i.status === "synced" && i.syncedAt !== undefined && Date.parse(i.syncedAt) + SYNCED_RETENTION_DAYS * DAY_MS <= now.getTime(),
  );
}

/** Montant affiché dans la liste : total des débits (libre) ou montant saisi (guidée). */
export function itemAmount(item: QueueItem): bigint {
  if (item.kind === "guided") return BigInt(item.payload.amount);
  return item.payload.lines.reduce((sum, line) => sum + BigInt(line.debit), 0n);
}

export function itemDate(item: QueueItem): string {
  return item.payload.entry_date;
}

export function itemLabel(item: QueueItem): string {
  return item.payload.label ?? "";
}

export type QueueCounts = { pending: number; rejected: number; synced: number };

export function counts(items: QueueItem[]): QueueCounts {
  return {
    pending: items.filter((i) => i.status === "pending").length,
    rejected: items.filter((i) => i.status === "rejected").length,
    synced: items.filter((i) => i.status === "synced").length,
  };
}

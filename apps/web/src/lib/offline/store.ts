import { newKey, type Sealed, seal, unseal } from "./crypto";
import type { QueueItem, Snapshot } from "./model";

/**
 * Stockage de la saisie hors connexion dans IndexedDB (navigateur uniquement).
 *
 * - `keys`      : clé AES non exportable de chaque utilisateur de l'appareil ;
 * - `snapshots` : données d'un dossier pour saisir (chiffrées), clé « user:company » ;
 * - `queue`     : saisies en attente, refusées ou synchronisées (chiffrées) ;
 * - `meta`      : dernier utilisateur connecté sur cet appareil (hors connexion, seule
 *                 sa file est montrée ; celle d'un autre compte reste invisible).
 * Seuls les identifiants, le statut et les dates restent en clair (index et purge).
 */

const DB_NAME = "kora-offline";
const VERSION = 1;
const CHANNEL = "kora-offline";

type SnapshotRecord = { key: string; userId: string; companyId: string; expiresAt: string } & Sealed;
type QueueRecord = { id: string; userId: string; companyId: string; status: QueueItem["status"] } & Sealed;

/** Saisie hors connexion possible : IndexedDB et WebCrypto exigent un contexte HTTPS. */
export function offlineSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof indexedDB !== "undefined" &&
    typeof crypto !== "undefined" &&
    crypto.subtle !== undefined
  );
}

let opening: Promise<IDBDatabase> | null = null;

function database(): Promise<IDBDatabase> {
  opening ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore("meta");
      db.createObjectStore("keys");
      db.createObjectStore("snapshots", { keyPath: "key" }).createIndex("userId", "userId");
      db.createObjectStore("queue", { keyPath: "id" }).createIndex("userId", "userId");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      opening = null;
      reject(request.error ?? new Error("IndexedDB indisponible"));
    };
  });
  return opening;
}

function done<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Opération IndexedDB refusée"));
  });
}

async function store(name: string, mode: IDBTransactionMode = "readonly"): Promise<IDBObjectStore> {
  return (await database()).transaction(name, mode).objectStore(name);
}

/** Prévient les autres onglets et composants qu'il faut relire la file. */
export function notifyChange(): void {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(CHANNEL);
  channel.postMessage("changed");
  channel.close();
  window.dispatchEvent(new Event(CHANNEL));
}

export function onChange(listener: () => void): () => void {
  window.addEventListener(CHANNEL, listener);
  const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL);
  if (channel) channel.onmessage = listener;
  return () => {
    window.removeEventListener(CHANNEL, listener);
    channel?.close();
  };
}

export async function setCurrentUser(userId: string): Promise<void> {
  await done((await store("meta", "readwrite")).put(userId, "currentUser"));
}

export async function currentUser(): Promise<string | null> {
  const value: unknown = await done((await store("meta")).get("currentUser"));
  return typeof value === "string" ? value : null;
}

const keyRequests = new Map<string, Promise<CryptoKey>>();

/**
 * Clé de l'utilisateur, créée au premier besoin. Lecture et création dans une même
 * transaction : deux onglets ne peuvent pas chacun écrire une clé (la seconde rendrait
 * illisible ce qui a été chiffré avec la première).
 */
function userKey(userId: string): Promise<CryptoKey> {
  let request = keyRequests.get(userId);
  if (!request) {
    request = (async () => {
      const existing: unknown = await done((await store("keys")).get(userId));
      if (existing instanceof CryptoKey) return existing;
      const fresh = await newKey();
      const keys = await store("keys", "readwrite");
      const found: unknown = await done(keys.get(userId));
      if (found instanceof CryptoKey) return found;
      await done(keys.add(fresh, userId));
      return fresh;
    })();
    request.catch(() => keyRequests.delete(userId));
    keyRequests.set(userId, request);
  }
  return request;
}

const snapshotKey = (userId: string, companyId: string) => `${userId}:${companyId}`;
const snapshotAad = (key: string) => `kora-offline:v1:snapshot:${key}`;
const itemAad = (userId: string, id: string) => `kora-offline:v1:queue:${userId}:${id}`;

export async function saveSnapshot(snapshot: Snapshot): Promise<void> {
  const key = snapshotKey(snapshot.userId, snapshot.companyId);
  const sealed = await seal(await userKey(snapshot.userId), snapshotAad(key), snapshot);
  const record: SnapshotRecord = {
    key,
    userId: snapshot.userId,
    companyId: snapshot.companyId,
    expiresAt: snapshot.expiresAt,
    ...sealed,
  };
  await done((await store("snapshots", "readwrite")).put(record));
  notifyChange();
}

async function openSnapshot(record: SnapshotRecord): Promise<Snapshot> {
  return unseal<Snapshot>(await userKey(record.userId), snapshotAad(record.key), record);
}

export async function getSnapshot(userId: string, companyId: string): Promise<Snapshot | null> {
  const record = (await done((await store("snapshots")).get(snapshotKey(userId, companyId)))) as SnapshotRecord | undefined;
  return record ? openSnapshot(record) : null;
}

export async function listSnapshots(userId: string): Promise<Snapshot[]> {
  const records = (await done((await store("snapshots")).index("userId").getAll(userId))) as SnapshotRecord[];
  return Promise.all(records.map(openSnapshot));
}

export async function deleteSnapshot(userId: string, companyId: string): Promise<void> {
  await done((await store("snapshots", "readwrite")).delete(snapshotKey(userId, companyId)));
  notifyChange();
}

export async function putItem(item: QueueItem): Promise<void> {
  const sealed = await seal(await userKey(item.userId), itemAad(item.userId, item.id), item);
  const record: QueueRecord = { id: item.id, userId: item.userId, companyId: item.companyId, status: item.status, ...sealed };
  await done((await store("queue", "readwrite")).put(record));
  notifyChange();
}

async function openItem(record: QueueRecord): Promise<QueueItem> {
  return unseal<QueueItem>(await userKey(record.userId), itemAad(record.userId, record.id), record);
}

export async function getItem(userId: string, id: string): Promise<QueueItem | null> {
  const record = (await done((await store("queue")).get(id))) as QueueRecord | undefined;
  return record && record.userId === userId ? openItem(record) : null;
}

export async function listItems(userId: string, companyId?: string): Promise<QueueItem[]> {
  const records = (await done((await store("queue")).index("userId").getAll(userId))) as QueueRecord[];
  const items = await Promise.all(records.filter((r) => !companyId || r.companyId === companyId).map(openItem));
  return items.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function deleteItem(id: string): Promise<void> {
  await done((await store("queue", "readwrite")).delete(id));
  notifyChange();
}

/** Nombre de saisies pas encore devenues des brouillons (en attente ou refusées). */
export async function unsyncedCount(userId: string): Promise<number> {
  const records = (await done((await store("queue")).index("userId").getAll(userId))) as QueueRecord[];
  return records.filter((r) => r.status !== "synced").length;
}

/** Efface tout ce que l'appareil conserve pour cet utilisateur (déconnexion). */
export async function purgeUser(userId: string): Promise<void> {
  const db = await database();
  keyRequests.delete(userId);
  const tx = db.transaction(["keys", "snapshots", "queue", "meta"], "readwrite");
  tx.objectStore("keys").delete(userId);
  for (const name of ["snapshots", "queue"] as const) {
    const index = tx.objectStore(name).index("userId");
    const keys = await done(index.getAllKeys(userId));
    for (const key of keys) tx.objectStore(name).delete(key);
  }
  const current: unknown = await done(tx.objectStore("meta").get("currentUser"));
  if (current === userId) tx.objectStore("meta").delete("currentUser");
  await new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("Effacement impossible"));
  });
  notifyChange();
}

/**
 * Chiffrement des données conservées sur l'appareil (AES-256-GCM, WebCrypto).
 *
 * La clé est générée sur l'appareil, NON EXPORTABLE, et conservée dans IndexedDB :
 * une copie des fichiers du navigateur ne donne pas les données en clair. Limite
 * assumée : quiconque utilise le navigateur ouvert de la personne peut, lui, les lire.
 * L'identifiant de l'enregistrement est lié au chiffré (donnée authentifiée) : un
 * enregistrement déplacé sous un autre identifiant est refusé au déchiffrement.
 */

export type Sealed = { iv: Uint8Array<ArrayBuffer>; data: ArrayBuffer };

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export function newKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export async function seal(key: CryptoKey, aad: string, value: unknown): Promise<Sealed> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: encoder.encode(aad) },
    key,
    encoder.encode(JSON.stringify(value)),
  );
  return { iv, data };
}

export async function unseal<T>(key: CryptoKey, aad: string, sealed: Sealed): Promise<T> {
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: sealed.iv, additionalData: encoder.encode(aad) },
    key,
    sealed.data,
  );
  return JSON.parse(decoder.decode(plain)) as T;
}

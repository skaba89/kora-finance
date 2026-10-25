import "server-only";

import { connection } from "next/server";

/**
 * L'installation envoie-t-elle des emails ? (KORA_EMAIL_BACKEND=disabled tant qu'aucun
 * fournisseur n'est configuré.) Lu à l'exécution, jamais figé au build.
 */
export async function emailsEnabled(): Promise<boolean> {
  await connection();
  return process.env.KORA_EMAIL_BACKEND !== "disabled";
}

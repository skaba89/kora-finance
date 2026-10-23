import "server-only";

import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * Client typé de l'API Kora, utilisable uniquement côté serveur.
 * Les types viennent du schéma OpenAPI exporté par apps/api (`npm run gen:api`).
 */
export function createApiClient(
  fetchImpl: typeof fetch = fetch,
  options: { accessToken?: string; clientIp?: string | null } = {},
) {
  const baseUrl = process.env.KORA_API_INTERNAL_URL;
  if (!baseUrl) {
    throw new Error("KORA_API_INTERNAL_URL n'est pas défini");
  }
  const headers: Record<string, string> = {};
  if (options.accessToken) headers.Authorization = `Bearer ${options.accessToken}`;
  // L'API ne fait confiance qu'à un proxy (ce serveur) pour l'IP du client : elle en a
  // besoin pour la limitation de débit et l'audit.
  if (options.clientIp) headers["X-Forwarded-For"] = options.clientIp;
  return createClient<paths>({ baseUrl, fetch: fetchImpl, headers });
}

export type ApiClient = ReturnType<typeof createApiClient>;

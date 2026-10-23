import "server-only";

import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * Client typé de l'API Kora, utilisable uniquement côté serveur.
 * Les types viennent du schéma OpenAPI exporté par apps/api (`npm run gen:api`).
 */
export function createApiClient(fetchImpl: typeof fetch = fetch) {
  const baseUrl = process.env.KORA_API_INTERNAL_URL;
  if (!baseUrl) {
    throw new Error("KORA_API_INTERNAL_URL n'est pas défini");
  }
  return createClient<paths>({ baseUrl, fetch: fetchImpl });
}

export type ApiClient = ReturnType<typeof createApiClient>;

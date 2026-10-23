import "server-only";

import { cookies, headers } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { ACCESS_COOKIE } from "@/lib/session";

import { createApiClient } from "./client";

/** Erreur renvoyée par l'API au format {detail, code, errors}. */
export type ApiError = { detail: string; code?: string; errors?: string[] };

/** IP du client telle que vue par ce serveur (dernière entrée ajoutée par un proxy). */
export async function clientIp(): Promise<string | null> {
  const h = await headers();
  const forwarded = h.get("x-forwarded-for");
  if (forwarded) {
    const parts = forwarded.split(",").map((p) => p.trim()).filter(Boolean);
    return parts.at(-1) ?? null;
  }
  return h.get("x-real-ip");
}

/** Client authentifié avec le jeton de la session courante. */
export async function api() {
  const accessToken = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!accessToken) redirect("/connexion");
  return createApiClient(fetch, { accessToken, clientIp: await clientIp() });
}

/** Client anonyme (connexion, inscription, rafraîchissement). */
export async function publicApi() {
  return createApiClient(fetch, { clientIp: await clientIp() });
}

/**
 * Normalise une erreur d'API en message affichable. Les erreurs de validation
 * FastAPI (422 avec une liste) sont ramenées au même format.
 */
export function toApiError(error: unknown, fallback: string): ApiError {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return error as ApiError;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : null))
        .filter((m): m is string => m !== null);
      return { detail: fallback, code: "validation", errors: messages };
    }
  }
  return { detail: fallback };
}

/**
 * Lecture côté Server Component : renvoie les données ou interrompt le rendu
 * proprement (session expirée → connexion ; dossier inaccessible → 404).
 */
export async function read<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.status === 401) redirect("/connexion");
  if (response.status === 404) notFound();
  if (error !== undefined || data === undefined) {
    throw new Error(`API ${response.status} : ${toApiError(error, "erreur inattendue").detail}`);
  }
  return data;
}

import "server-only";

import { cookies } from "next/headers";

import { type ApiError, toApiError } from "@/lib/api/server";
import { DEFAULT_LOCALE, isLocale } from "@/lib/i18n/config";
import { en } from "@/lib/i18n/en";
import { fr } from "@/lib/i18n/fr";
import { LOCALE_COOKIE } from "@/lib/session";

import type { ActionState } from "./state";

/** Dictionnaire dans une Server Action (`next/root-params` n'y est pas disponible). */
export async function actionDictionary() {
  const value = (await cookies()).get(LOCALE_COOKIE)?.value;
  return (isLocale(value) ? value : DEFAULT_LOCALE) === "en" ? en : fr;
}

export function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** Champ facultatif : chaîne vide → null. */
export function optionalField(formData: FormData, name: string): string | null {
  return field(formData, name) || null;
}

export async function failure(error: unknown): Promise<ActionState> {
  const t = await actionDictionary();
  const apiError: ApiError = toApiError(error, t.common.unexpectedError);
  return { status: "error", message: apiError.detail, errors: apiError.errors ?? [] };
}

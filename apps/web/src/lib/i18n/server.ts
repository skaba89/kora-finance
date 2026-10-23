import "server-only";

import { lang } from "next/root-params";

import { DEFAULT_LOCALE, isLocale, type Locale } from "./config";
import { en } from "./en";
import { fr } from "./fr";

export type Dictionary = typeof fr;

const DICTIONARIES: Record<Locale, Dictionary> = { fr, en };

/** Dictionnaire de la langue courante (segment racine [lang], posé par le proxy). */
export async function getDictionary(): Promise<{ t: Dictionary; locale: Locale }> {
  const value = await lang();
  const locale = isLocale(value) ? value : DEFAULT_LOCALE;
  return { t: DICTIONARIES[locale], locale };
}

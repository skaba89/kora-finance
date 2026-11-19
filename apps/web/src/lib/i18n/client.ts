import { DEFAULT_LOCALE, isLocale } from "./config";
import { en } from "./en";
import { fr } from "./fr";
import type { Dictionary } from "./server";

/**
 * Dictionnaire côté client — réservé aux composants non serveurs qui ne
 * peuvent pas recevoir de libellés en props (boundaries d'erreur montés par
 * le framework). Tout autre composant client reçoit ses libellés du serveur
 * (props sérialisées), comme le reste de l'application.
 */
export function getClientDictionary(locale: unknown): Dictionary {
  const key = isLocale(locale) ? locale : DEFAULT_LOCALE;
  return key === "en" ? en : fr;
}

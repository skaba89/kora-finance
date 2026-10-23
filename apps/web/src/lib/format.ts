/**
 * Formats d'affichage : français par défaut, montants en GNF sans décimales.
 * Les montants circulent en entiers (unités mineures) : jamais de flottant.
 */

import type { Locale } from "@/lib/i18n/config";

const INTL_LOCALE: Record<Locale, string> = { fr: "fr-FR", en: "en-GB" };

/** Nombre de décimales d'une devise (ISO 4217) ; GNF n'en a aucune. */
export function currencyDecimals(currency: string): number {
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency }).resolvedOptions()
    .maximumFractionDigits ?? 0;
}

/** Formate un montant exprimé en unités mineures (entier). */
export function formatMoney(minorUnits: number | bigint, currency: string, locale: Locale = "fr") {
  const decimals = currencyDecimals(currency);
  const value = typeof minorUnits === "bigint" ? minorUnits : BigInt(minorUnits);
  const sign = value < 0n ? "-" : "";
  const absolute = value < 0n ? -value : value;
  const divisor = 10n ** BigInt(decimals);
  const integerPart = new Intl.NumberFormat(INTL_LOCALE[locale]).format(absolute / divisor);
  const fraction = (absolute % divisor).toString().padStart(decimals, "0");
  const decimalPart = decimals > 0 ? `${locale === "fr" ? "," : "."}${fraction}` : "";
  return `${sign}${integerPart}${decimalPart} ${currency}`;
}

export function formatDate(isoDate: string, locale: Locale = "fr") {
  // Dates ISO (AAAA-MM-JJ) interprétées sans fuseau : pas de décalage d'un jour.
  const [year, month, day] = isoDate.slice(0, 10).split("-").map(Number);
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], { timeZone: "UTC" }).format(
    new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1)),
  );
}

export function formatDateTime(isoDateTime: string, locale: Locale = "fr") {
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Africa/Conakry",
  }).format(new Date(isoDateTime));
}

/** Taux en points de base (1800) → « 18 % » / « 18,5 % ». */
export function formatRate(basisPoints: number, locale: Locale = "fr") {
  return `${new Intl.NumberFormat(INTL_LOCALE[locale], { maximumFractionDigits: 2 }).format(
    basisPoints / 100,
  )} %`;
}

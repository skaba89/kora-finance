/**
 * Saisie et calcul de montants sans nombre flottant : les montants sont des chaînes de
 * chiffres en unités mineures (comme dans l'API) et les sommes se font en BigInt.
 */

/**
 * Convertit une saisie (« 1 500 000 », « 1500000 », « 12,50 » pour une devise à
 * décimales) en unités mineures. Renvoie null si la saisie est invalide, "0" si vide.
 */
export function parseAmount(input: string, decimals: number): string | null {
  const compact = input.replace(/[\s  ]/g, "");
  if (compact === "") return "0";
  const pattern = decimals > 0 ? new RegExp(`^(\\d+)(?:[.,](\\d{1,${decimals}}))?$`) : /^(\d+)$/;
  const match = pattern.exec(compact);
  if (!match) return null;
  const whole = (match[1] ?? "0").replace(/^0+(?=\d)/, "");
  const fraction = (match[2] ?? "").padEnd(decimals, "0");
  const minor = `${whole}${fraction}`.replace(/^0+(?=\d)/, "");
  return minor.length > 18 ? null : minor;
}

/** Valeur éditable (sans séparateurs de milliers) d'un montant en unités mineures. */
export function amountInputValue(minor: string, decimals: number): string {
  if (minor === "0") return "";
  if (decimals === 0) return minor;
  const padded = minor.padStart(decimals + 1, "0");
  return `${padded.slice(0, -decimals)},${padded.slice(-decimals)}`;
}

export function sumAmounts(values: readonly string[]): bigint {
  return values.reduce((total, value) => total + BigInt(value), 0n);
}

/**
 * Conversion d'un pourcentage saisi (« 18 », « 18,5 », « 0.25 ») en points de base
 * entiers, sans passer par un nombre flottant. Renvoie null si la saisie est invalide.
 */
export function percentToBasisPoints(input: string): number | null {
  const match = /^(\d{1,3})(?:[.,](\d{1,2}))?$/.exec(input.trim());
  if (!match) return null;
  const whole = Number.parseInt(match[1] ?? "0", 10);
  const fraction = Number.parseInt((match[2] ?? "").padEnd(2, "0"), 10);
  const basisPoints = whole * 100 + fraction;
  return basisPoints <= 10_000 ? basisPoints : null;
}

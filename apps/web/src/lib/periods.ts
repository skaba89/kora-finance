/** Choix de l'exercice affiché par défaut dans les états comptables. */

type FiscalYearLike = { id: string; start_date: string; end_date: string; status: string };

/**
 * Exercice demandé s'il existe ; sinon l'exercice qui contient aujourd'hui ; sinon le
 * plus récent. Dates ISO (AAAA-MM-JJ) : la comparaison de chaînes suffit.
 */
export function pickFiscalYear<T extends FiscalYearLike>(
  years: readonly T[],
  requestedId: string | undefined,
  today: string,
): T | undefined {
  const requested = years.find((y) => y.id === requestedId);
  if (requested) return requested;
  const current = years.find((y) => y.start_date <= today && today <= y.end_date);
  if (current) return current;
  return [...years].sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
}

/** Date ISO acceptée seulement si elle est dans l'exercice ; sinon undefined. */
export function dateWithin(value: string | undefined, year: FiscalYearLike): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  return value >= year.start_date && value <= year.end_date ? value : undefined;
}

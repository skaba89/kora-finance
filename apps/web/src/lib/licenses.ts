/**
 * Règles de présentation des licences, sans dépendance client ni serveur :
 * utilisables par les Server Components (page) et les Client Components
 * (formulaires). Un module "use client" ne peut pas exporter de fonctions
 * appelées côté serveur.
 */

type Period = { id: string; starts_on: string; ends_on: string; suspended: boolean };

export type RenewalAvailability = "available" | "suspended" | "expired" | "renewed";

/** Lendemain d'une date civile AAAA-MM-JJ, calculé en UTC (aucune heure locale). */
export function nextDay(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00.000Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

/**
 * Miroir des refus de l'API, pour ne proposer que les renouvellements possibles.
 * L'API reste l'autorité : elle revérifie tout sous verrou.
 */
export function renewalAvailability(period: Period, all: Period[], today: string): RenewalAvailability {
  if (all.some((other) => other.id !== period.id && other.starts_on === period.ends_on)) return "renewed";
  if (period.suspended) return "suspended";
  // Fin exclusive : renouveler le jour même de la fin reste admis (pas de rétroactivité).
  if (period.ends_on < today) return "expired";
  return "available";
}

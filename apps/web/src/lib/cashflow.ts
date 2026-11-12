/**
 * Aides de la prévision de trésorerie — agrégations et statuts (Phase 3E).
 *
 * Les montants restent des chaînes d'entiers (unités mineures) et les calculs se
 * font en BigInt : aucune conversion en flottant, conformément à la convention du
 * référentiel. Ce module ne dépend ni de React ni du réseau : testable par Vitest seul.
 */

export type ForecastStatus = "SAIN" | "SOUS_SURVEILLANCE" | "CRITIQUE";
export type ForecastScenario = "OPTIMISTE" | "NEUTRE" | "PRUDENT";
export type ForecastHorizon = 30 | 60 | 90;

export const HORIZONS: ForecastHorizon[] = [30, 60, 90];
export const SCENARIOS: ForecastScenario[] = ["OPTIMISTE", "NEUTRE", "PRUDENT"];

export type DailyProjection = {
  flow_date: string;
  inflow: string;
  outflow: string;
  balance: string;
  status: ForecastStatus;
  committed_inflow: string;
  committed_outflow: string;
  estimated_inflow: string;
  estimated_outflow: string;
};

export type AccountProjection = {
  account_id: string;
  number: string;
  label: string;
  opening: string;
  committed_net: string;
  projected: string;
  balances_at_marks: Record<string, string>;
};

export type Forecast = {
  as_of: string;
  horizon_days: number;
  scenario: ForecastScenario;
  opening_total: string;
  status: ForecastStatus;
  first_critical_date: string | null;
  lowest_balance: string;
  lowest_balance_date: string;
  beyond_horizon_inflow: string;
  beyond_horizon_outflow: string;
  insufficient_data: boolean;
  history_months_used: number;
  assumptions: Record<string, unknown>;
  days: DailyProjection[];
  accounts: AccountProjection[];
  excluded_drafts: { entry_date: string; label: string; net_treasury: string }[];
};

export type Snapshot = {
  id: string;
  generated_at: string;
  as_of: string;
  horizon_days: number;
  scenario: ForecastScenario;
  opening_total: string;
  status: ForecastStatus;
  first_critical_date: string | null;
  lowest_balance: string;
  lowest_balance_date: string;
  insufficient_data: boolean;
  history_months_used: number;
  assumptions: Record<string, unknown>;
};

/** Clé de semaine ISO (lundi) d'une date ISO « AAAA-MM-JJ ». */
export function weekKey(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  const day = (date.getUTCDay() + 6) % 7; // lundi = 0
  const monday = new Date(date);
  monday.setUTCDate(date.getUTCDate() - day);
  return monday.toISOString().slice(0, 10);
}

export type WeeklyPoint = {
  week_start: string;
  inflow: bigint;
  outflow: bigint;
  end_balance: bigint;
};

/**
 * Agrégation hebdomadaire pour la lisibilité mobile au-delà de 30 jours :
 * sommes des flux de la semaine, solde de fin de semaine (dernier jour connu).
 * Les jours arrivent dans l'ordre chronologique de l'API.
 */
export function aggregateWeekly(days: DailyProjection[]): WeeklyPoint[] {
  const buckets = new Map<string, WeeklyPoint>();
  for (const day of days) {
    const key = weekKey(day.flow_date);
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { week_start: key, inflow: 0n, outflow: 0n, end_balance: BigInt(day.balance) };
      buckets.set(key, bucket);
    }
    bucket.inflow += BigInt(day.inflow);
    bucket.outflow += BigInt(day.outflow);
    bucket.end_balance = BigInt(day.balance);
  }
  return [...buckets.values()];
}

/**
 * Variant de Badge (union du composant `ui/badge`) selon le statut projeté.
 * Convention du dépôt : ternaires inline ou fonction pure — jamais de couleur hors thème.
 */
export type ForecastBadgeVariant = "secondary" | "outline" | "destructive";

export function statusVariant(status: ForecastStatus): ForecastBadgeVariant {
  switch (status) {
    case "SAIN":
      return "secondary";
    case "SOUS_SURVEILLANCE":
      return "outline";
    case "CRITIQUE":
      return "destructive";
  }
}

/** Libellé de statut par locale (autonome : utilisable hors page). */
export function statusLabel(status: ForecastStatus, locale: "fr" | "en"): string {
  const labels: Record<ForecastStatus, Record<"fr" | "en", string>> = {
    SAIN: { fr: "Sain", en: "Healthy" },
    SOUS_SURVEILLANCE: { fr: "Sous surveillance", en: "Watch" },
    CRITIQUE: { fr: "Critique", en: "Critical" },
  };
  return labels[status][locale];
}

/**
 * Hauteur de barre proportionnelle en BigInt : ratio arrondi à l'unité près,
 * jamais en flottant (convention montants). Renvoie un entier 0..max_height.
 */
export function barHeight(amount: bigint, max: bigint, max_height: number): number {
  if (max <= 0n) return 0;
  return Number((amount * BigInt(max_height)) / max);
}

/**
 * Téléchargements : correspondance entre l'URL visible (/dossiers/{id}/exports/{type})
 * et la route de l'API, et liste blanche des paramètres transmis.
 */

export const EXPORT_KINDS = {
  balance: "/api/v1/companies/{company_id}/exports/trial-balance",
  "grand-livre": "/api/v1/companies/{company_id}/exports/ledger",
  ecritures: "/api/v1/companies/{company_id}/exports/entries",
  "etats-financiers": "/api/v1/companies/{company_id}/exports/financial-statements",
  tft: "/api/v1/companies/{company_id}/exports/cash-flow-statement",
  "previsions-tresorerie": "/api/v1/companies/{company_id}/cashflow/forecast/export",
} as const;

export type ExportKind = keyof typeof EXPORT_KINDS;
export type ExportFormat = "pdf" | "xlsx";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isExportKind(value: string): value is ExportKind {
  return Object.hasOwn(EXPORT_KINDS, value);
}

export type ExportQuery = {
  format: ExportFormat;
  fiscal_year_id: string;
  date_from?: string;
  date_to?: string;
  account_id?: string;
};

export type PrevisionsExportQuery = {
  format: ExportFormat;
  horizon: 30 | 60 | 90;
  scenario: "OPTIMISTE" | "NEUTRE" | "PRUDENT";
};

const HORIZONS = new Set(["30", "60", "90"]);
const SCENARIOS = new Set(["OPTIMISTE", "NEUTRE", "PRUDENT"]);

/** Paramètres validés ; null si la demande est incomplète ou invalide. */
export function exportQuery(
  kind: ExportKind,
  params: URLSearchParams,
): ExportQuery | PrevisionsExportQuery | null {
  const format = params.get("format");
  if (format !== "pdf" && format !== "xlsx") return null;
  if (kind === "previsions-tresorerie") {
    const horizon = params.get("horizon") ?? "";
    const scenario = params.get("scenario") ?? "";
    if (!HORIZONS.has(horizon) || !SCENARIOS.has(scenario)) return null;
    return { format, horizon: Number(horizon) as 30 | 60 | 90, scenario: scenario as PrevisionsExportQuery["scenario"] };
  }
  const fiscalYear = params.get("exercice") ?? "";
  if (!UUID.test(fiscalYear)) return null;
  const query: ExportQuery = { format, fiscal_year_id: fiscalYear };
  const from = params.get("du");
  const to = params.get("au");
  const account = params.get("compte_id");
  if (from && DATE.test(from)) query.date_from = from;
  if (to && DATE.test(to)) query.date_to = to;
  if (account && UUID.test(account)) query.account_id = account;
  return query;
}

/** Lien de téléchargement (paramètres en français, comme les pages). */
export function exportHref(
  companyId: string,
  kind: ExportKind,
  format: ExportFormat,
  params: { fiscalYearId: string; dateFrom?: string; dateTo?: string; accountId?: string },
): string {
  const search = new URLSearchParams({ format, exercice: params.fiscalYearId });
  if (params.dateFrom) search.set("du", params.dateFrom);
  if (params.dateTo) search.set("au", params.dateTo);
  if (params.accountId) search.set("compte_id", params.accountId);
  return `/dossiers/${companyId}/exports/${kind}?${search.toString()}`;
}

/** Lien de téléchargement de la prévision de trésorerie (Phase 3E). */
export function previsionsExportHref(
  companyId: string,
  format: ExportFormat,
  horizon: 30 | 60 | 90,
  scenario: "OPTIMISTE" | "NEUTRE" | "PRUDENT",
): string {
  const search = new URLSearchParams({ format, horizon: String(horizon), scenario });
  return `/dossiers/${companyId}/exports/previsions-tresorerie?${search.toString()}`;
}

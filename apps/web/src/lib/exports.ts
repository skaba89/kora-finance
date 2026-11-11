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

/** Paramètres validés ; null si la demande est incomplète ou invalide. */
export function exportQuery(params: URLSearchParams): ExportQuery | null {
  const format = params.get("format");
  const fiscalYear = params.get("exercice") ?? "";
  if ((format !== "pdf" && format !== "xlsx") || !UUID.test(fiscalYear)) return null;
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

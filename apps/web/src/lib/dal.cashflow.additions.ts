/**
 * Ajouts à appliquer à `apps/web/src/lib/dal.ts` dans le PR de la Phase 3E.
 * (Fragment fourni tel quel pour intégration — les fonctions suivent la convention
 * `read((await api()).GET(...))` du module existant. `schema.ts` est régénéré après
 * la génération du contrat OpenAPI : `npm run openapi && npm run generate:api`.)
 */

export type CashflowQuery = {
  horizon: number;
  scenario: "OPTIMISTE" | "NEUTRE" | "PRUDENT";
  as_of?: string;
};

export async function getCashflowForecast(companyId: string, query: CashflowQuery) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/cashflow/forecast", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getCashflowSettings(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/cashflow/settings", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getCashflowSnapshots(companyId: string, limit = 10) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/cashflow/snapshots", {
      params: { path: { company_id: companyId }, query: { limit } },
    }),
  );
}

export async function getCashflowVsActual(companyId: string, snapshotId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/cashflow/snapshots/{snapshot_id}/vs-actual", {
      params: { path: { company_id: companyId, snapshot_id: snapshotId } },
    }),
  );
}

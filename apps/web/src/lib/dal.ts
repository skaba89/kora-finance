import "server-only";

import { cache } from "react";

import { api, read } from "@/lib/api/server";

/**
 * Couche d'accès aux données (lecture). Chaque lecture passe par l'API, qui applique
 * l'authentification, les permissions et l'isolation des dossiers : le frontend ne
 * fait que masquer ce que l'utilisateur ne peut pas faire.
 * `cache` évite les appels en double dans un même rendu.
 */

export const getCurrentUser = cache(async () => read((await api()).GET("/api/v1/auth/me")));

export const getCompanies = cache(async () => read((await api()).GET("/api/v1/companies")));

export const getCompany = cache(async (companyId: string) =>
  read(
    (await api()).GET("/api/v1/companies/{company_id}", {
      params: { path: { company_id: companyId } },
    }),
  ),
);

export async function getFiscalYears(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/fiscal-years", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getAccounts(
  companyId: string,
  query: { q?: string; class?: number; active_only?: boolean; limit: number; offset: number },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/accounts", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getTaxRates(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/tax-rates", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getMembers(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/members", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getInvitations(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/invitations", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getJournals(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/journals", {
      params: { path: { company_id: companyId } },
    }),
  );
}

/** Tous les comptes actifs (sélecteur de saisie) : quelques centaines, en pages de 200. */
export async function getActiveAccounts(companyId: string) {
  const client = await api();
  const accounts = [];
  for (let offset = 0; ; offset += 200) {
    const page = await read(
      client.GET("/api/v1/companies/{company_id}/accounts", {
        params: { path: { company_id: companyId }, query: { active_only: true, limit: 200, offset } },
      }),
    );
    accounts.push(...page.items);
    if (accounts.length >= page.total || page.items.length === 0) return accounts;
  }
}

export type EntriesQuery = {
  journal_id?: string;
  status?: "DRAFT" | "POSTED";
  q?: string;
  limit: number;
  offset: number;
};

export async function getEntries(companyId: string, query: EntriesQuery) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/entries", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getEntry(companyId: string, entryId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/entries/{entry_id}", {
      params: { path: { company_id: companyId, entry_id: entryId } },
    }),
  );
}

export type PeriodQuery = { fiscal_year_id: string; date_from?: string; date_to?: string };

export async function getTrialBalance(
  companyId: string,
  query: PeriodQuery & { class?: number; prefix?: string; include_zero?: boolean },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/trial-balance", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getLedger(
  companyId: string,
  query: PeriodQuery & { account_id: string; limit: number; offset: number },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/ledger", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getLetterableLines(
  companyId: string,
  query: { account_id: string; status: "open" | "lettered" | "all"; limit: number; offset: number },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/lettering/lines", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getClosingCheck(companyId: string, fiscalYearId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/fiscal-years/{fiscal_year_id}/closing-check", {
      params: { path: { company_id: companyId, fiscal_year_id: fiscalYearId } },
    }),
  );
}

export async function getFinancialStatements(companyId: string, query: { fiscal_year_id: string; date_to?: string }) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/financial-statements", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getAuditEvents(companyId: string, limit: number, offset: number) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/audit-events", {
      params: { path: { company_id: companyId }, query: { limit, offset } },
    }),
  );
}

export type Company = Awaited<ReturnType<typeof getCompany>>;

export function can(company: Company, permission: string): boolean {
  return company.permissions.includes(permission);
}

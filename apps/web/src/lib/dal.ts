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

/** Référentiel des tiers (4A) : clients et fournisseurs, filtrable et paginé. */
export async function getPartners(
  companyId: string,
  query: {
    q?: string;
    kind?: "CLIENT" | "FOURNISSEUR";
    active?: boolean;
    limit: number;
    offset: number;
  },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/partners", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

export async function getPartner(companyId: string, partnerId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/partners/{partner_id}", {
      params: { path: { company_id: companyId, partner_id: partnerId } },
    }),
  );
}

/** Devis, factures et avoirs du dossier (Phase 4B), filtrables et paginés. */
export async function getSalesDocuments(
  companyId: string,
  query: {
    kind?: "quote" | "invoice" | "credit_note";
    status?: "DRAFT" | "SENT" | "ACCEPTED" | "REJECTED" | "ISSUED" | "CANCELLED";
    limit: number;
    offset: number;
  },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/sales", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

/** Comptes financiers du dossier (banques, caisses, Mobile Money) et leurs soldes. */
export async function getTreasuryAccounts(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/treasury/accounts", {
      params: { path: { company_id: companyId } },
    }),
  );
}

/** Mouvements d'un compte financier (paginés, du plus ancien au plus récent). */
export async function getTreasuryMovements(companyId: string, accountId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/treasury/accounts/{account_id}/movements", {
      params: { path: { company_id: companyId, account_id: accountId } },
      query: { limit: 100, offset: 0 },
    }),
  );
}

/** Relevés bancaires importés d'un compte (3B), du plus récent au plus ancien. */
export async function getTreasuryStatements(companyId: string, accountId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/treasury/accounts/{account_id}/statements", {
      params: { path: { company_id: companyId, account_id: accountId } },
      query: { limit: 50, offset: 0 },
    }),
  );
}

/** Lignes d'un relevé importé, dans l'ordre du fichier, doublons signalés. */
export async function getStatementLines(companyId: string, statementId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/treasury/statements/{statement_id}/lines", {
      params: { path: { company_id: companyId, statement_id: statementId } },
      query: { limit: 500, offset: 0 },
    }),
  );
}

/** Candidats de rapprochement d'une ligne de relevé (3C) : propositions classées,
 * jamais appliquées — la confirmation reste humaine. */
export async function getMatchCandidates(
  companyId: string,
  statementId: string,
  lineId: string,
) {
  return read(
    (await api()).GET(
      "/api/v1/companies/{company_id}/treasury/statements/{statement_id}/lines/{line_id}/candidates",
      { params: { path: { company_id: companyId, statement_id: statementId, line_id: lineId } } },
    ),
  );
}

/** Vue d'ensemble du rapprochement d'un compte financier (3C) : compteurs et écarts. */
export async function getReconciliationOverview(companyId: string, accountId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/treasury/accounts/{account_id}/reconciliation", {
      params: { path: { company_id: companyId, account_id: accountId } },
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

export async function getDashboard(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/dashboard", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getGuidedOptions(companyId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/guided-entries/options", {
      params: { path: { company_id: companyId } },
    }),
  );
}

export async function getAttachments(companyId: string, entryId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/entries/{entry_id}/attachments", {
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

export async function getCashFlowStatement(companyId: string, query: { fiscal_year_id: string; date_to?: string }) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/cash-flow-statement", {
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

// --- Prévision de trésorerie (Phase 3E) --------------------------------------

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

export async function getCashflowSnapshot(companyId: string, snapshotId: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/cashflow/snapshots/{snapshot_id}", {
      params: { path: { company_id: companyId, snapshot_id: snapshotId } },
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

export type Company = Awaited<ReturnType<typeof getCompany>>;

export function can(company: Company, permission: string): boolean {
  return company.permissions.includes(permission);
}

/** Règlements clients du dossier (Phase 4C), filtrables et paginés. */
export async function getSalesPayments(
  companyId: string,
  query: {
    partner_id?: string;
    document_id?: string;
    date_from?: string;
    date_to?: string;
    limit: number;
    offset: number;
  },
) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/payments", {
      params: { path: { company_id: companyId }, query },
    }),
  );
}

/** Balance âgée clients à une date donnée (Phase 4C) : créances par ancienneté. */
export async function getSalesAging(companyId: string, asOf?: string) {
  return read(
    (await api()).GET("/api/v1/companies/{company_id}/receivables/aging", {
      params: {
        path: { company_id: companyId },
        query: asOf ? { as_of: asOf } : undefined,
      },
    }),
  );
}

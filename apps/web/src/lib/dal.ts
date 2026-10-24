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

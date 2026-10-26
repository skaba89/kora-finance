"use server";

import { cookies } from "next/headers";

import { createApiClient } from "@/lib/api/client";
import { clientIp, toApiError } from "@/lib/api/server";
import { can, getActiveAccounts, getCompany, getCurrentUser, getFiscalYears, getGuidedOptions, getJournals } from "@/lib/dal";
import { type Snapshot, snapshotExpiry, type SyncOutcome } from "@/lib/offline/model";
import { parseEntry, parseGuided, UUID } from "@/lib/payloads";
import { ACCESS_COOKIE } from "@/lib/session";

import type { ActionState } from "./state";
import { actionDictionary } from "./support";

function nextDay(date: string): string {
  const day = new Date(`${date}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

/**
 * « Préparer la saisie hors connexion » : données du dossier nécessaires pour saisir
 * (comptes d'imputation, journaux, options de la saisie guidée, exercices ouverts),
 * conservées ensuite sur l'appareil, chiffrées. Réservé à qui peut saisir.
 */
export async function prepareOfflineAction(companyId: string): Promise<ActionState> {
  const t = await actionDictionary();
  const company = await getCompany(companyId);
  if (!can(company, "entries:write")) return { status: "error", message: t.offline.notAllowed };
  const [user, journals, accounts, guided, years] = await Promise.all([
    getCurrentUser(),
    getJournals(companyId),
    getActiveAccounts(companyId),
    getGuidedOptions(companyId),
    getFiscalYears(companyId),
  ]);
  const now = new Date();
  const snapshot: Snapshot = {
    version: 1,
    userId: user.id,
    companyId,
    companyName: company.company.legal_name,
    currency: company.company.currency,
    fetchedAt: now.toISOString(),
    expiresAt: snapshotExpiry(now),
    journals: journals.filter((j) => j.is_active).map(({ id, code, label }) => ({ id, code, label })),
    accounts: accounts.map(({ id, number, label }) => ({ id, number, label })),
    openFiscalYears: years
      .filter((y) => y.status === "OPEN")
      .map((y) => ({
        start_date: y.locked_until && y.locked_until >= y.start_date ? nextDay(y.locked_until) : y.start_date,
        end_date: y.end_date,
      }))
      .filter((y) => y.start_date <= y.end_date),
    guided,
  };
  return { status: "success", data: { snapshot } };
}

export type SyncInput = { companyId: string; id: string; kind: "free" | "guided"; payload: unknown };

/**
 * Synchronisation d'une saisie faite hors connexion : crée le brouillon (jamais de
 * validation). L'identifiant de la saisie rend l'appel idempotent : un renvoi après une
 * coupure renvoie le brouillon déjà créé. Ne redirige jamais (appelée en arrière-plan) :
 * une session absente est signalée par `auth`.
 */
export async function syncOfflineItemAction(input: SyncInput): Promise<SyncOutcome> {
  const t = await actionDictionary();
  const accessToken = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!accessToken) return { status: "auth" };
  if (!UUID.test(input.companyId) || !UUID.test(input.id)) {
    return { status: "rejected", message: t.offline.invalidItem, errors: [] };
  }
  const client = createApiClient(fetch, { accessToken, clientIp: await clientIp() });
  const path = { company_id: input.companyId };

  const call = async () => {
    if (input.kind === "guided") {
      const body = parseGuided(input.payload);
      if (!body) return null;
      return client.POST("/api/v1/companies/{company_id}/guided-entries", {
        params: { path },
        body: { ...body, id: input.id },
      });
    }
    const body = parseEntry(input.payload);
    if (!body) return null;
    return client.POST("/api/v1/companies/{company_id}/entries", { params: { path }, body: { ...body, id: input.id } });
  };

  try {
    let result = await call();
    if (!result) return { status: "rejected", message: t.offline.invalidItem, errors: [] };
    // 409 : envoi simultané du même identifiant (deux onglets) ; le second essai
    // renvoie le brouillon créé par le premier.
    if (result.response.status === 409) result = (await call()) ?? result;
    const { data, error, response } = result;
    if (data) return { status: "synced", entryId: data.id };
    if (response.status === 401) return { status: "auth" };
    if (response.status >= 500 || response.status === 429) return { status: "retry" };
    const apiError = toApiError(error, t.common.unexpectedError);
    return { status: "rejected", message: apiError.detail, errors: apiError.errors ?? [] };
  } catch (error) {
    console.error("Synchronisation hors connexion : API injoignable", error);
    return { status: "retry" };
  }
}

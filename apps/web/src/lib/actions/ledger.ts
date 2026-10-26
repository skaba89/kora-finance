"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { interpolate } from "@/lib/i18n/interpolate";
import { parseEntryJson, UUID } from "@/lib/payloads";

import type { ActionState } from "./state";
import { actionDictionary, failure, field } from "./support";

type JournalKind = components["schemas"]["JournalKind"];


/**
 * Enregistre un brouillon (création ou modification), puis le valide si demandé.
 * L'identifiant `client_id` généré par l'éditeur rend la création idempotente : un
 * double envoi (réseau lent) ne crée pas deux écritures.
 */
export async function saveEntryAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const body = parseEntryJson(field(formData, "payload"));
  if (!body) {
    const t = await actionDictionary();
    return { status: "error", message: t.common.unexpectedError };
  }
  const existingId = field(formData, "entry_id");
  const clientId = field(formData, "client_id");
  const client = await api();
  let entryId: string;
  if (UUID.test(existingId)) {
    const { error, response } = await client.PUT("/api/v1/companies/{company_id}/entries/{entry_id}", {
      params: { path: { company_id: companyId, entry_id: existingId } },
      body,
    });
    if (!response.ok) return failure(error);
    entryId = existingId;
  } else {
    const { data, error } = await client.POST("/api/v1/companies/{company_id}/entries", {
      params: { path: { company_id: companyId } },
      body: { ...body, id: UUID.test(clientId) ? clientId : null },
    });
    if (!data) return failure(error);
    entryId = data.id;
  }

  if (field(formData, "intent") === "post") {
    const { error, response } = await client.POST(
      "/api/v1/companies/{company_id}/entries/{entry_id}/post",
      { params: { path: { company_id: companyId, entry_id: entryId } } },
    );
    if (!response.ok) {
      // Brouillon enregistré, validation refusée : l'éditeur continue sur ce brouillon.
      const state = await failure(error);
      return { ...state, data: { entryId } };
    }
  }
  redirect(`/dossiers/${companyId}/ecritures/${entryId}`);
}

export async function postEntryAction(companyId: string, entryId: string, _: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/entries/{entry_id}/post",
    { params: { path: { company_id: companyId, entry_id: entryId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

export async function deleteEntryAction(companyId: string, entryId: string, _: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/entries/{entry_id}",
    { params: { path: { company_id: companyId, entry_id: entryId } } },
  );
  if (!response.ok) return failure(error);
  redirect(`/dossiers/${companyId}/ecritures`);
}

export async function reverseEntryAction(
  companyId: string,
  entryId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const { data, error } = await (await api()).POST(
    "/api/v1/companies/{company_id}/entries/{entry_id}/reversal",
    {
      params: { path: { company_id: companyId, entry_id: entryId } },
      body: { entry_date: field(formData, "entry_date") },
    },
  );
  if (!data) return failure(error);
  redirect(`/dossiers/${companyId}/ecritures/${data.id}`);
}

const JOURNAL_KINDS: readonly string[] = ["ACHATS", "VENTES", "TRESORERIE", "OPERATIONS_DIVERSES", "A_NOUVEAUX"];

export async function createJournalAction(companyId: string, _: ActionState, formData: FormData): Promise<ActionState> {
  const kind = field(formData, "kind");
  const { error, response } = await (await api()).POST("/api/v1/companies/{company_id}/journals", {
    params: { path: { company_id: companyId } },
    body: {
      code: field(formData, "code"),
      label: field(formData, "label"),
      kind: (JOURNAL_KINDS.includes(kind) ? kind : "OPERATIONS_DIVERSES") as JournalKind,
    },
  });
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

export async function toggleJournalAction(
  companyId: string,
  journalId: string,
  active: boolean,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).PATCH(
    "/api/v1/companies/{company_id}/journals/{journal_id}",
    { params: { path: { company_id: companyId, journal_id: journalId } }, body: { is_active: active } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

export async function letterAction(
  companyId: string,
  accountId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const lineIds = formData.getAll("line_id").filter((v): v is string => typeof v === "string" && UUID.test(v));
  const { error, response } = await (await api()).POST("/api/v1/companies/{company_id}/letterings", {
    params: { path: { company_id: companyId } },
    body: { account_id: accountId, line_ids: lineIds },
  });
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

export async function unletterAction(companyId: string, letteringId: string, _: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/letterings/{lettering_id}",
    { params: { path: { company_id: companyId, lettering_id: letteringId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

export async function autoLetterAction(companyId: string, accountId: string, _: ActionState): Promise<ActionState> {
  const { data, error } = await (await api()).POST("/api/v1/companies/{company_id}/letterings/auto", {
    params: { path: { company_id: companyId } },
    body: { account_id: accountId },
  });
  if (!data) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: interpolate(t.lettering.autoDone, { count: data.created }) };
}

export async function unlockPeriodAction(companyId: string, fiscalYearId: string, _: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/fiscal-years/{fiscal_year_id}/lock",
    { params: { path: { company_id: companyId, fiscal_year_id: fiscalYearId } }, body: { locked_until: null } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

export async function lockPeriodAction(
  companyId: string,
  fiscalYearId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const until = field(formData, "locked_until");
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/fiscal-years/{fiscal_year_id}/lock",
    {
      params: { path: { company_id: companyId, fiscal_year_id: fiscalYearId } },
      body: { locked_until: until || null },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

export async function closeFiscalYearAction(companyId: string, fiscalYearId: string, _: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/fiscal-years/{fiscal_year_id}/closing",
    { params: { path: { company_id: companyId, fiscal_year_id: fiscalYearId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

export async function reopenFiscalYearAction(companyId: string, fiscalYearId: string, _: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/fiscal-years/{fiscal_year_id}/reopening",
    { params: { path: { company_id: companyId, fiscal_year_id: fiscalYearId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

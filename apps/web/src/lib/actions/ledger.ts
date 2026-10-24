"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";

import type { ActionState } from "./state";
import { actionDictionary, failure, field } from "./support";

type EntryIn = components["schemas"]["EntryIn"];
type JournalKind = components["schemas"]["JournalKind"];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGITS = /^(0|[1-9][0-9]{0,17})$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Corps d'écriture préparé par l'éditeur : revérifié ici (l'API revérifie aussi). */
function parseEntry(raw: string): EntryIn | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (typeof v.journal_id !== "string" || !UUID.test(v.journal_id)) return null;
  if (typeof v.entry_date !== "string" || !DATE.test(v.entry_date)) return null;
  if (typeof v.label !== "string") return null;
  if (v.reference !== null && typeof v.reference !== "string") return null;
  if (!Array.isArray(v.lines)) return null;
  const lines = [];
  for (const line of v.lines as unknown[]) {
    const l = line as Record<string, unknown>;
    if (typeof l.account_id !== "string" || !UUID.test(l.account_id)) return null;
    if (typeof l.debit !== "string" || !DIGITS.test(l.debit)) return null;
    if (typeof l.credit !== "string" || !DIGITS.test(l.credit)) return null;
    if (l.label !== null && typeof l.label !== "string") return null;
    lines.push({ account_id: l.account_id, debit: l.debit, credit: l.credit, label: l.label });
  }
  return {
    journal_id: v.journal_id,
    entry_date: v.entry_date,
    label: v.label,
    reference: v.reference,
    lines,
  };
}

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
  const body = parseEntry(field(formData, "payload"));
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

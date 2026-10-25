"use server";

import { redirect } from "next/navigation";

import { parseAmount } from "@/lib/amounts";
import { api } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";

import type { ActionState } from "./state";
import { actionDictionary, failure, field, optionalField } from "./support";

type GuidedIn = components["schemas"]["GuidedIn"];
type Operation = components["schemas"]["Operation"];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function optionalUuid(formData: FormData, name: string): string | null {
  const value = field(formData, name);
  return UUID.test(value) ? value : null;
}

/**
 * Saisie guidée : « Voir l'écriture » (aperçu), « Enregistrer le brouillon » ou
 * « Enregistrer et valider ». L'API construit l'écriture ; ce formulaire ne fait que
 * transmettre les choix. L'identifiant `client_id` rend l'enregistrement idempotent.
 */
export async function guidedEntryAction(
  companyId: string,
  operation: Operation,
  decimals: number,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const t = await actionDictionary();
  const amount = parseAmount(field(formData, "amount"), decimals);
  if (amount === null || amount === "0") return { status: "error", message: t.guided.invalidAmount };
  const entryDate = field(formData, "entry_date");
  if (!DATE.test(entryDate)) return { status: "error", message: t.guided.invalidDate };

  const body: GuidedIn = {
    operation,
    entry_date: entryDate,
    amount,
    label: optionalField(formData, "label"),
    reference: optionalField(formData, "reference"),
    nature_account_id: optionalUuid(formData, "nature_account_id"),
    treasury_account_id: optionalUuid(formData, "treasury_account_id"),
    target_treasury_account_id: optionalUuid(formData, "target_treasury_account_id"),
    party_account_id: optionalUuid(formData, "party_account_id"),
    vat_included: formData.get("vat_included") === "on",
  };
  const client = await api();
  const intent = field(formData, "intent");

  if (intent === "preview") {
    const { data, error } = await client.POST("/api/v1/companies/{company_id}/guided-entries/preview", {
      params: { path: { company_id: companyId } },
      body,
    });
    if (!data) return failure(error);
    return { status: "success", data: { preview: data } };
  }

  const clientId = field(formData, "client_id");
  const { data, error } = await client.POST("/api/v1/companies/{company_id}/guided-entries", {
    params: { path: { company_id: companyId } },
    body: { ...body, id: UUID.test(clientId) ? clientId : null },
  });
  if (!data) return failure(error);

  if (intent === "post") {
    const { error: postError, response } = await client.POST(
      "/api/v1/companies/{company_id}/entries/{entry_id}/post",
      { params: { path: { company_id: companyId, entry_id: data.id } } },
    );
    if (!response.ok) {
      // Brouillon enregistré, validation refusée : on l'ouvre pour correction.
      const state = await failure(postError);
      return { ...state, data: { entryId: data.id } };
    }
  }
  redirect(`/dossiers/${companyId}/ecritures/${data.id}`);
}

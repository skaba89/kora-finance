"use server";

import { redirect } from "next/navigation";

import { api } from "@/lib/api/server";
import { guidedBody, type Operation, UUID } from "@/lib/payloads";

import type { ActionState } from "./state";
import { actionDictionary, failure, field } from "./support";

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
  const parsed = guidedBody(formData, operation, decimals);
  if ("error" in parsed) {
    const t = await actionDictionary();
    return { status: "error", message: parsed.error === "amount" ? t.guided.invalidAmount : t.guided.invalidDate };
  }
  const { body } = parsed;
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

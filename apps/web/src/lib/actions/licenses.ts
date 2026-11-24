"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api/server";
import type { ActionState } from "./state";
import { actionDictionary, failure, field } from "./support";

/**
 * Suspend (ou réactive) une période de licence. `currentlySuspended` est l'état
 * affiché à l'administrateur : il est transmis comme état attendu, et l'API
 * refuse (409) une demande fondée sur un état devenu obsolète. Le motif est
 * validé par l'API et conservé dans le journal d'audit.
 */
export async function changeLicenseSuspensionAction(
  clientId: string,
  licenseId: string,
  currentlySuspended: boolean,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const { response, error } = await (await api()).PUT(
    "/api/v1/platform/module-clients/{client_id}/licenses/{license_id}/suspension",
    {
      params: { path: { client_id: clientId, license_id: licenseId } },
      body: {
        suspended: !currentlySuspended,
        expected_suspended: currentlySuspended,
        reason: field(formData, "reason"),
      },
    },
  );
  if (!response.ok) return failure(error);
  refresh();
  const t = await actionDictionary();
  return { status: "success", message: t.common.saved };
}

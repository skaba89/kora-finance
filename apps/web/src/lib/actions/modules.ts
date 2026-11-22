"use server";

import { refresh } from "next/cache";
import { api } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import type { ActionState } from "./state";
import { actionDictionary, failure } from "./support";

export async function updateModuleAction(
  clientId: string,
  module: components["schemas"]["Module"],
  enabled: boolean,
  revision: number,
  _: ActionState,
): Promise<ActionState> {
  const { response, error } = await (await api()).PUT(
    "/api/v1/platform/module-clients/{client_id}/modules/{module}",
    {
      params: { path: { client_id: clientId, module } },
      body: { enabled, expected_revision: revision },
    },
  );
  if (!response.ok) return failure(error);
  refresh();
  const t = await actionDictionary();
  return { status: "success", message: t.common.saved };
}

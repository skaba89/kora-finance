"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api/server";

import type { ActionState } from "./state";
import { actionDictionary, failure } from "./support";

/**
 * Envoie une pièce justificative. Le fichier est transmis brut à l'API, qui vérifie
 * son type réel, sa taille, et ignore un second envoi du même fichier (réessai).
 */
export async function uploadAttachmentAction(
  companyId: string,
  entryId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const t = await actionDictionary();
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) return { status: "error", message: t.attachments.noFile };
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/entries/{entry_id}/attachments",
    {
      params: { path: { company_id: companyId, entry_id: entryId }, query: { filename: file.name || "piece" } },
      // Corps brut (pas de JSON) : le contenu du fichier.
      body: (await file.arrayBuffer()) as unknown as string,
      bodySerializer: (body: unknown) => body as ArrayBuffer,
      headers: { "Content-Type": file.type || "application/octet-stream" },
    },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success", message: response.status === 200 ? t.attachments.alreadyAttached : t.attachments.added };
}

export async function removeAttachmentAction(
  companyId: string,
  attachmentId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/attachments/{attachment_id}",
    { params: { path: { company_id: companyId, attachment_id: attachmentId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success" };
}

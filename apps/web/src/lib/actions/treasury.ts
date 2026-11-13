"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api/server";
import { actionDictionary, failure, field } from "@/lib/actions/support";
import { interpolate } from "@/lib/i18n/interpolate";
import type { ActionState } from "./state";

const KINDS = ["BANQUE", "CAISSE", "MOBILE_MONEY"] as const;
const MOVEMENTS = ["DEPOT", "RETRAIT", "FRAIS"] as const;

type AccountKind = (typeof KINDS)[number];
type MovementKind = (typeof MOVEMENTS)[number];

/** Crée un compte financier (banque, caisse, portefeuille Mobile Money). */
export async function createTreasuryAccountAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const kind = field(formData, "kind");
  if (!KINDS.includes(kind as AccountKind)) {
    const t = await actionDictionary();
    return { status: "error", message: t.common.unexpectedError };
  }
  const operator = field(formData, "operator");
  const masked = field(formData, "account_number_masked");
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/accounts",
    {
      params: { path: { company_id: companyId } },
      body: {
        name: field(formData, "name"),
        kind: kind as AccountKind,
        gl_account_id: field(formData, "gl_account_id"),
        operator: kind === "MOBILE_MONEY" && operator ? operator : undefined,
        account_number_masked: masked || undefined,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Enregistre un dépôt, un retrait ou des frais bancaires (écriture validée atomiquement). */
export async function recordTreasuryMovementAction(
  companyId: string,
  accountId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const kind = field(formData, "kind");
  if (!MOVEMENTS.includes(kind as MovementKind)) {
    const t = await actionDictionary();
    return { status: "error", message: t.common.unexpectedError };
  }
  const reference = field(formData, "reference");
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/accounts/{account_id}/movements",
    {
      params: { path: { company_id: companyId, account_id: accountId } },
      body: {
        kind: kind as MovementKind,
        amount: field(formData, "amount"),
        movement_date: field(formData, "movement_date"),
        label: field(formData, "label"),
        counterpart_account_id: field(formData, "counterpart_account_id"),
        reference: reference || undefined,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Virement interne : deux comptes financiers du dossier, une seule écriture. */
export async function recordTreasuryTransferAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const reference = field(formData, "reference");
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/transfers",
    {
      params: { path: { company_id: companyId } },
      body: {
        source_account_id: field(formData, "source_account_id"),
        target_account_id: field(formData, "target_account_id"),
        amount: field(formData, "amount"),
        movement_date: field(formData, "movement_date"),
        label: field(formData, "label"),
        reference: reference || undefined,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Import d'un relevé bancaire (OFX, CSV ou Excel .xlsx) : corps brut, pas de multipart. */
export async function importStatementAction(
  companyId: string,
  accountId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const t = await actionDictionary();
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { status: "error", message: t.treasury.releves.noFile };
  }
  const { data, error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/accounts/{account_id}/statements",
    {
      params: {
        path: { company_id: companyId, account_id: accountId },
        query: { filename: file.name || "releve" },
      },
      // Corps brut (pas de JSON) : le contenu du fichier.
      body: (await file.arrayBuffer()) as unknown as string,
      bodySerializer: (body: unknown) => body as ArrayBuffer,
      headers: { "Content-Type": "application/octet-stream" },
    },
  );
  if (!response.ok) return failure(error);
  refresh();
  return {
    status: "success",
    message: interpolate(t.treasury.releves.imported, { lines: data?.line_count ?? 0 }),
  };
}

/** Écarte une ligne de relevé du rapprochement (idempotent). */
export async function ignoreStatementLineAction(
  companyId: string,
  statementId: string,
  lineId: string,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/statements/{statement_id}/lines/{line_id}/ignore",
    { params: { path: { company_id: companyId, statement_id: statementId, line_id: lineId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success", message: (await actionDictionary()).common.saved };
}

/** Remet une ligne ignorée en attente de rapprochement (idempotent). */
export async function restoreStatementLineAction(
  companyId: string,
  statementId: string,
  lineId: string,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/statements/{statement_id}/lines/{line_id}/restore",
    { params: { path: { company_id: companyId, statement_id: statementId, line_id: lineId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success", message: (await actionDictionary()).common.saved };
}

/** Retire le rapprochement d'une ligne (repasse en attente, mouvement libéré). */
export async function unmatchStatementLineAction(
  companyId: string,
  statementId: string,
  lineId: string,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/statements/{statement_id}/lines/{line_id}/unmatch",
    { params: { path: { company_id: companyId, statement_id: statementId, line_id: lineId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success", message: (await actionDictionary()).common.saved };
}

/** Confirme le rapprochement d'une ligne avec le mouvement choisi (acte humain,
 * réversible) : le mouvement est passé lié au clic, jamais par le formulaire. */
export async function matchStatementLineAction(
  companyId: string,
  statementId: string,
  lineId: string,
  movementId: string,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/treasury/statements/{statement_id}/lines/{line_id}/match",
    {
      params: { path: { company_id: companyId, statement_id: statementId, line_id: lineId } },
      body: { movement_id: movementId },
    },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success", message: (await actionDictionary()).common.saved };
}

/** Supprime un relevé non rapproché (et son fichier original conservé). */
export async function deleteStatementAction(
  companyId: string,
  statementId: string,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/treasury/statements/{statement_id}",
    { params: { path: { company_id: companyId, statement_id: statementId } } },
  );
  if (!response.ok) return failure(error);
  refresh();
  return { status: "success", message: (await actionDictionary()).treasury.releves.deleted };
}

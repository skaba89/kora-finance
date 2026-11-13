"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api/server";
import { actionDictionary, failure, field } from "@/lib/actions/support";
import type { ActionState } from "./state";

/** Crée un tier du référentiel (client et/ou fournisseur, Phase 4A). */
export async function createPartnerAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const isClient = formData.get("is_client") === "on";
  const isSupplier = formData.get("is_supplier") === "on";
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/partners",
    {
      params: { path: { company_id: companyId } },
      body: {
        name: field(formData, "name"),
        is_client: isClient,
        is_supplier: isSupplier,
        is_active: true,
        tax_id: field(formData, "tax_id") || undefined,
        rccm: field(formData, "rccm") || undefined,
        address: field(formData, "address") || undefined,
        email: field(formData, "email") || undefined,
        phone: field(formData, "phone") || undefined,
        contact_name: field(formData, "contact_name") || undefined,
        default_client_account_id: field(formData, "default_client_account_id") || undefined,
        default_supplier_account_id: field(formData, "default_supplier_account_id") || undefined,
        notes: field(formData, "notes") || undefined,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Modifie une fiche tier (mise à jour partielle : seuls les champs remplis changent). */
export async function updatePartnerAction(
  companyId: string,
  partnerId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const isClient = formData.get("is_client") === "on";
  const isSupplier = formData.get("is_supplier") === "on";
  const clientAccount = field(formData, "default_client_account_id");
  const supplierAccount = field(formData, "default_supplier_account_id");
  const { error, response } = await (await api()).PATCH(
    "/api/v1/companies/{company_id}/partners/{partner_id}",
    {
      params: { path: { company_id: companyId, partner_id: partnerId } },
      body: {
        name: field(formData, "name"),
        is_client: isClient,
        is_supplier: isSupplier,
        tax_id: field(formData, "tax_id") || null,
        rccm: field(formData, "rccm") || null,
        address: field(formData, "address") || null,
        email: field(formData, "email") || null,
        phone: field(formData, "phone") || null,
        contact_name: field(formData, "contact_name") || null,
        default_client_account_id: clientAccount || null,
        default_supplier_account_id: supplierAccount || null,
        notes: field(formData, "notes") || null,
        is_active: formData.get("is_active") === "on",
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

/** Désactive ou réactive un tier (jamais de suppression). */
export async function setPartnerActiveAction(
  companyId: string,
  partnerId: string,
  isActive: boolean,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).PATCH(
    "/api/v1/companies/{company_id}/partners/{partner_id}",
    {
      params: { path: { company_id: companyId, partner_id: partnerId } },
      body: { is_active: isActive },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

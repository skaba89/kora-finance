"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { interpolate } from "@/lib/i18n/interpolate";
import { percentToBasisPoints } from "@/lib/rates";

import type { ActionState } from "./state";
import { actionDictionary, failure, field, optionalField } from "./support";

type LegalForm = components["schemas"]["LegalForm"];
type CompanyRole = "PME_DIRIGEANT" | "PME_COMPTABLE" | "PME_LECTEUR";
const COMPANY_ROLES: readonly string[] = ["PME_DIRIGEANT", "PME_COMPTABLE", "PME_LECTEUR"];

async function ok(): Promise<ActionState> {
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.common.saved };
}

export async function createCompanyAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const start = field(formData, "fiscal_year_start");
  const end = field(formData, "fiscal_year_end");
  const { data, error } = await (await api()).POST("/api/v1/companies", {
    body: {
      legal_name: field(formData, "legal_name"),
      legal_form: field(formData, "legal_form") as LegalForm,
      trade_name: optionalField(formData, "trade_name"),
      rccm: optionalField(formData, "rccm"),
      nif: optionalField(formData, "nif"),
      address: optionalField(formData, "address"),
      city: optionalField(formData, "city"),
      phone: optionalField(formData, "phone"),
      currency: "GNF",
      first_fiscal_year: start && end ? { start_date: start, end_date: end } : null,
    },
  });
  if (!data) return failure(error);
  redirect(`/dossiers/${data.id}`);
}

export async function updateCompanyAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const { error, response } = await (await api()).PATCH("/api/v1/companies/{company_id}", {
    params: { path: { company_id: companyId } },
    body: {
      legal_name: field(formData, "legal_name"),
      legal_form: field(formData, "legal_form") as LegalForm,
      trade_name: optionalField(formData, "trade_name"),
      rccm: optionalField(formData, "rccm"),
      nif: optionalField(formData, "nif"),
      address: optionalField(formData, "address"),
      city: optionalField(formData, "city"),
      phone: optionalField(formData, "phone"),
    },
  });
  return response.ok ? ok() : failure(error);
}

export async function createFiscalYearAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/fiscal-years",
    {
      params: { path: { company_id: companyId } },
      body: { start_date: field(formData, "start_date"), end_date: field(formData, "end_date") },
    },
  );
  return response.ok ? ok() : failure(error);
}

export async function createAccountAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST("/api/v1/companies/{company_id}/accounts", {
    params: { path: { company_id: companyId } },
    body: { number: field(formData, "number"), label: field(formData, "label") },
  });
  return response.ok ? ok() : failure(error);
}

export async function toggleAccountAction(
  companyId: string,
  accountId: string,
  isActive: boolean,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).PATCH(
    "/api/v1/companies/{company_id}/accounts/{account_id}",
    {
      params: { path: { company_id: companyId, account_id: accountId } },
      body: { is_active: isActive },
    },
  );
  return response.ok ? ok() : failure(error);
}

export async function addTaxRateAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const basisPoints = percentToBasisPoints(field(formData, "rate"));
  if (basisPoints === null) {
    const t = await actionDictionary();
    return { status: "error", message: t.taxes.rateHint };
  }
  const { error, response } = await (await api()).POST("/api/v1/companies/{company_id}/tax-rates", {
    params: { path: { company_id: companyId } },
    body: {
      code: field(formData, "code").toUpperCase(),
      label: field(formData, "label"),
      kind: field(formData, "kind") === "TVA" ? "TVA" : "AUTRE",
      rate_basis_points: basisPoints,
      valid_from: field(formData, "valid_from"),
      collected_account_number: optionalField(formData, "collected_account_number"),
      deductible_account_number: optionalField(formData, "deductible_account_number"),
      note: optionalField(formData, "note"),
    },
  });
  return response.ok ? ok() : failure(error);
}

export async function verifyTaxRateAction(
  companyId: string,
  taxRateId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/tax-rates/{tax_rate_id}/verification",
    { params: { path: { company_id: companyId, tax_rate_id: taxRateId } } },
  );
  return response.ok ? ok() : failure(error);
}

export async function addMemberAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const role = field(formData, "role");
  const { data, error } = await (await api()).POST("/api/v1/companies/{company_id}/members", {
    params: { path: { company_id: companyId } },
    body: {
      email: field(formData, "email"),
      role: (COMPANY_ROLES.includes(role) ? role : "PME_LECTEUR") as CompanyRole,
    },
  });
  if (!data) return failure(error);
  const t = await actionDictionary();
  refresh();
  if (data.status === "member") return { status: "success", message: t.members.added };
  const { email } = data.invitation;
  return data.email_queued
    ? { status: "success", message: interpolate(t.members.invited, { email }) }
    : { status: "error", message: interpolate(t.members.invitedNotQueued, { email }) };
}

export async function resendInvitationAction(
  companyId: string,
  invitationId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/invitations/{invitation_id}/resend",
    { params: { path: { company_id: companyId, invitation_id: invitationId } } },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.members.resent };
}

export async function revokeInvitationAction(
  companyId: string,
  invitationId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/invitations/{invitation_id}",
    { params: { path: { company_id: companyId, invitation_id: invitationId } } },
  );
  return response.ok ? ok() : failure(error);
}

export async function changeMemberRoleAction(
  companyId: string,
  membershipId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const role = field(formData, "role");
  const { error, response } = await (await api()).PATCH(
    "/api/v1/companies/{company_id}/members/{membership_id}",
    {
      params: { path: { company_id: companyId, membership_id: membershipId } },
      body: { role: (COMPANY_ROLES.includes(role) ? role : "PME_LECTEUR") as CompanyRole },
    },
  );
  return response.ok ? ok() : failure(error);
}

export async function removeMemberAction(
  companyId: string,
  membershipId: string,
  _: ActionState,
): Promise<ActionState> {
  const { error, response } = await (await api()).DELETE(
    "/api/v1/companies/{company_id}/members/{membership_id}",
    { params: { path: { company_id: companyId, membership_id: membershipId } } },
  );
  return response.ok ? ok() : failure(error);
}

export async function verifyAuditChainAction(companyId: string, _: ActionState): Promise<ActionState> {
  const { data, error } = await (await api()).GET(
    "/api/v1/companies/{company_id}/audit-events/verification",
    { params: { path: { company_id: companyId } } },
  );
  if (!data) return failure(error);
  return { status: data.ok ? "success" : "error", data };
}

"use server";

import { api, toApiError } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { actionDictionary, field } from "./support";

export type ImportState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | {
      status: "success";
      report: components["schemas"]["ImportReportOut"];
      expiresAt: string;
      batchId: string;
    };

export type ImportIssuesPage =
  | { status: "error"; message: string }
  | {
      status: "success";
      issues: components["schemas"]["ImportIssueOut"][];
      hasMore: boolean;
    };

export type ImportConfirmState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | {
      status: "success";
      confirmation: components["schemas"]["ImportConfirmationOut"];
    };

export async function confirmImportAction(
  companyId: string,
  batchId: string,
): Promise<ImportConfirmState> {
  const t = await actionDictionary();
  const client = await api();
  // Une seule confirmation possible côté API : un double appel est refusé
  // (409) et aucun brouillon ne peut être dupliqué.
  const confirmed = await client.POST(
    "/api/v1/companies/{company_id}/accounting-imports/{batch_id}/confirm",
    { params: { path: { company_id: companyId, batch_id: batchId } } },
  );
  if (!confirmed.response.ok || !confirmed.data) {
    return { status: "error", message: toApiError(confirmed.error, t.common.unexpectedError).detail };
  }
  return { status: "success", confirmation: confirmed.data };
}

export async function precheckImportAction(
  companyId: string,
  _: ImportState,
  formData: FormData,
): Promise<ImportState> {
  const t = await actionDictionary();
  const fail = (message: string): ImportState => ({ status: "error", message });
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) return fail(t.imports.noFile);
  if (file.size > 10 * 1024 * 1024) return fail(t.imports.tooLarge);
  const format = field(formData, "format");
  const delimiter = field(formData, "delimiter");
  if (format !== "csv" && format !== "fec" && format !== "xlsx") return fail(t.imports.invalidOptions);
  if (delimiter !== "pipe" && delimiter !== "tab") return fail(t.imports.invalidOptions);
  const client = await api();
  const upload = await client.POST("/api/v1/companies/{company_id}/accounting-imports", {
    params: { path: { company_id: companyId }, query: { file_format: format, source_currency: "GNF", fec_delimiter: format === "fec" && delimiter === "tab" ? "\t" : "|" } },
    body: (await file.arrayBuffer()) as unknown as string,
    bodySerializer: (body: unknown) => body as ArrayBuffer,
    headers: { "Content-Type": "application/octet-stream" },
  });
  if (!upload.response.ok || !upload.data) return fail(toApiError(upload.error, t.common.unexpectedError).detail);
  const check = await client.POST("/api/v1/companies/{company_id}/accounting-imports/{batch_id}/precheck", {
    params: { path: { company_id: companyId, batch_id: upload.data.id } },
  });
  if (!check.response.ok || !check.data) return fail(toApiError(check.error, t.common.unexpectedError).detail);
  return { status: "success", report: check.data, expiresAt: upload.data.expires_at, batchId: upload.data.id };
}

export async function loadMoreIssuesAction(
  companyId: string,
  batchId: string,
  offset: number,
): Promise<ImportIssuesPage> {
  const t = await actionDictionary();
  const client = await api();
  // Le rapport persisté est relu par pages : le fichier source n'est jamais
  // rechargé ni redéchiffré pour consulter des anomalies déjà contrôlées.
  const page = await client.GET(
    "/api/v1/companies/{company_id}/accounting-imports/{batch_id}/precheck",
    { params: { path: { company_id: companyId, batch_id: batchId }, query: { limit: 200, offset } } },
  );
  if (!page.response.ok || !page.data) {
    return { status: "error", message: toApiError(page.error, t.common.unexpectedError).detail };
  }
  return { status: "success", issues: page.data.issues, hasMore: page.data.has_more };
}

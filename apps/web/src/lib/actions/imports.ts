"use server";

import { api, toApiError } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { actionDictionary, field } from "./support";

export type ImportState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "success"; report: components["schemas"]["ImportReportOut"]; expiresAt: string };

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
  return { status: "success", report: check.data, expiresAt: upload.data.expires_at };
}

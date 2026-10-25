import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

import { createApiClient } from "@/lib/api/client";
import { clientIp } from "@/lib/api/server";
import { ACCESS_COOKIE } from "@/lib/session";

/**
 * Consultation d'une pièce justificative (BFF) : le navigateur n'appelle jamais l'API ni
 * le stockage. `?telecharger=1` force l'enregistrement du fichier ; sinon il s'ouvre
 * dans le navigateur (PDF, image).
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/[lang]/dossiers/[companyId]/pieces/[attachmentId]">,
) {
  const { companyId, attachmentId } = await params;
  const accessToken = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!accessToken) return NextResponse.redirect(new URL("/connexion", request.url));

  const api = createApiClient(fetch, { accessToken, clientIp: await clientIp() });
  const { response } = await api.GET("/api/v1/companies/{company_id}/attachments/{attachment_id}/content", {
    params: {
      path: { company_id: companyId, attachment_id: attachmentId },
      query: { disposition: request.nextUrl.searchParams.get("telecharger") === "1" ? "attachment" : "inline" },
    },
    parseAs: "stream",
  });
  if (!response.ok || !response.body) {
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) => (typeof body.detail === "string" ? body.detail : null))
      .catch(() => null);
    return new NextResponse(detail ?? "Pièce indisponible.", {
      status: [401, 404, 409, 503].includes(response.status) ? response.status : 502,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  return new NextResponse(response.body, {
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

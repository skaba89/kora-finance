import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

import { createApiClient } from "@/lib/api/client";
import { clientIp } from "@/lib/api/server";
import { EXPORT_KINDS, exportQuery, isExportKind } from "@/lib/exports";
import { ACCESS_COOKIE } from "@/lib/session";

/**
 * Téléchargement d'un export (BFF) : le navigateur n'appelle jamais l'API directement ;
 * le fichier est relayé en flux, sans être chargé en mémoire.
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/[lang]/dossiers/[companyId]/exports/[kind]">,
) {
  const { companyId, kind } = await params;
  if (!isExportKind(kind)) return new NextResponse("Demande d'export invalide.", { status: 400 });
  const query = exportQuery(kind, request.nextUrl.searchParams);
  if (!query) return new NextResponse("Demande d'export invalide.", { status: 400 });
  const accessToken = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!accessToken) return NextResponse.redirect(new URL("/connexion", request.url));

  const api = createApiClient(fetch, { accessToken, clientIp: await clientIp() });
  const { response } = await api.GET(EXPORT_KINDS[kind], {
    params: { path: { company_id: companyId }, query },
    parseAs: "stream",
  });
  if (!response.ok || !response.body) {
    // Message lisible (JSON {detail}) plutôt qu'un fichier corrompu.
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) => (typeof body.detail === "string" ? body.detail : null))
      .catch(() => null);
    return new NextResponse(detail ?? "Export impossible.", {
      status: response.status === 401 ? 401 : response.status === 404 ? 404 : 422,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  return new NextResponse(response.body, {
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment",
      "Cache-Control": "no-store",
    },
  });
}

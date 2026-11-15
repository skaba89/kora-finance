import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

import { createApiClient } from "@/lib/api/client";
import { clientIp } from "@/lib/api/server";
import { ACCESS_COOKIE } from "@/lib/session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PDF_PATH = "/api/v1/companies/{company_id}/sales/{document_id}/pdf";

/**
 * Téléchargement du PDF conforme d'un document de vente (BFF, Phase 4B-bis) :
 * le navigateur n'appelle jamais l'API directement ; le fichier est relayé en
 * flux. Un brouillon (jamais numéroté) renvoie 422 avec le message de l'API.
 */
export async function GET(
  request: NextRequest,
  { params }: RouteContext<"/[lang]/dossiers/[companyId]/ventes/[documentId]/pdf">,
) {
  const { companyId, documentId } = await params;
  if (!UUID.test(documentId)) return new NextResponse("Document invalide.", { status: 400 });
  const accessToken = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!accessToken) return NextResponse.redirect(new URL("/connexion", request.url));

  const api = createApiClient(fetch, { accessToken, clientIp: await clientIp() });
  const { response } = await api.GET(PDF_PATH, {
    params: { path: { company_id: companyId, document_id: documentId } },
    parseAs: "stream",
  });
  if (!response.ok || !response.body) {
    // Message lisible (JSON {detail}) plutôt qu'un fichier corrompu.
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) => (typeof body.detail === "string" ? body.detail : null))
      .catch(() => null);
    return new NextResponse(detail ?? "PDF impossible.", {
      status: response.status === 401 ? 401 : response.status === 404 ? 404 : 422,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  return new NextResponse(response.body, {
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "application/pdf",
      "Content-Disposition": response.headers.get("Content-Disposition") ?? "attachment",
      "Cache-Control": "no-store",
    },
  });
}

import { type NextRequest, NextResponse } from "next/server";

import { DEFAULT_LOCALE, isLocale, LOCALES, type Locale } from "@/lib/i18n/config";
import {
  ACCESS_COOKIE,
  cookieOptions,
  isFresh,
  LOCALE_COOKIE,
  MFA_COOKIE,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE_SECONDS,
} from "@/lib/session";

/**
 * Exécuté avant chaque page :
 * 1. politique de sécurité du contenu (CSP) et en-têtes de sécurité ;
 * 2. renouvellement du jeton d'accès à partir du refresh token (cookies httpOnly) ;
 * 3. protection des pages : sans session, retour à la connexion ;
 * 4. langue : `/dossiers` est réécrit en `/fr/dossiers` selon le cookie de langue,
 *    l'URL visible reste sans préfixe.
 */

/** Pages ouvertes depuis un lien reçu par email (jeton dans l'URL). */
const TOKEN_PAGES = ["/reinitialisation-mot-de-passe", "/verification-email", "/invitation"];

/** Pages réservées aux visiteurs non connectés (redirigent vers les dossiers sinon). */
const GUEST_ONLY = ["/connexion", "/inscription", "/mot-de-passe-oublie"];
/** Pages accessibles avec ou sans session. */
const PUBLIC = ["/hors-connexion", "/connexion/verification", ...TOKEN_PAGES];

type Tokens = { access_token: string; refresh_token: string; expires_in: number };

function matches(pathname: string, prefixes: string[]) {
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/**
 * CSP sans nonce : avec Cache Components, la coquille statique des pages est générée
 * au build et ses scripts ne peuvent pas porter un nonce par requête. Les scripts
 * restent limités à l'origine ('self') ; 'unsafe-inline' couvre les scripts d'amorçage
 * de Next.js. Le risque résiduel (XSS par script inline) est maîtrisé par l'échappement
 * systématique de React (aucun dangerouslySetInnerHTML). À durcir avec l'intégrité de
 * sous-ressource (SRI) quand elle ne sera plus expérimentale dans Next.js.
 */
function contentSecurityPolicy(): string {
  const isDev = process.env.NODE_ENV === "development";
  // KORA_PREVIEW_EMBED=1 : preview bac à sable uniquement (iframe de l'aperçu du
  // chat sur *.space-z.ai autorisée via `frame-ancestors *`). Ne jamais activer
  // en production, le comportement par défaut reste `frame-ancestors 'none'`.
  const previewEmbed = process.env.KORA_PREVIEW_EMBED === "1";
  const https = (process.env.KORA_PUBLIC_URL ?? "").startsWith("https://");
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    previewEmbed ? "frame-ancestors *" : "frame-ancestors 'none'",
    ...(https ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

function clientIp(request: NextRequest): string | null {
  const forwarded = request.headers.get("x-forwarded-for");
  return forwarded?.split(",").map((p) => p.trim()).filter(Boolean).at(-1) ?? null;
}

async function refreshTokens(request: NextRequest, refreshToken: string): Promise<Tokens | null> {
  const baseUrl = process.env.KORA_API_INTERNAL_URL;
  if (!baseUrl) throw new Error("KORA_API_INTERNAL_URL n'est pas défini");
  const ip = clientIp(request);
  const response = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(ip ? { "X-Forwarded-For": ip } : {}) },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`Rafraîchissement impossible (HTTP ${response.status})`);
  return (await response.json()) as Tokens;
}

function withSecurityHeaders(
  response: NextResponse,
  csp: string,
  referrer = "strict-origin-when-cross-origin",
): NextResponse {
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", referrer);
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
}

function redirectTo(request: NextRequest, pathname: string, csp: string, next?: string) {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  url.search = next ? `?suivant=${encodeURIComponent(next)}` : "";
  return withSecurityHeaders(NextResponse.redirect(url), csp);
}

function clearSession(response: NextResponse) {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE]) response.cookies.delete(name);
}

export async function proxy(request: NextRequest) {
  const csp = contentSecurityPolicy();
  const { pathname, search } = request.nextUrl;

  // Chemin déjà préfixé par une langue (accès direct) : on le traite sans le préfixe.
  const prefix = LOCALES.find((l) => pathname === `/${l}` || pathname.startsWith(`/${l}/`));
  const path = prefix ? pathname.slice(prefix.length + 1) || "/" : pathname;
  const cookieLocale = request.cookies.get(LOCALE_COOKIE)?.value;
  const locale: Locale = prefix ?? (isLocale(cookieLocale) ? cookieLocale : DEFAULT_LOCALE);

  let access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  let renewed: Tokens | null = null;
  let sessionEnded = false;

  if (!isFresh(access) && refresh) {
    try {
      renewed = await refreshTokens(request, refresh);
      if (renewed) {
        access = renewed.access_token;
      } else {
        // 401 : session révoquée ou expirée.
        sessionEnded = true;
        access = undefined;
      }
    } catch (error) {
      // API injoignable : on laisse la page s'afficher (elle signalera l'erreur)
      // sans détruire une session peut-être encore valide.
      console.error("Proxy : rafraîchissement de session impossible", error);
    }
  }
  const hasSession = Boolean(access);

  let response: NextResponse;
  if (matches(path, GUEST_ONLY) && !matches(path, PUBLIC) && hasSession) {
    response = redirectTo(request, "/dossiers", csp);
  } else if (!hasSession && !matches(path, GUEST_ONLY) && !matches(path, PUBLIC)) {
    response = redirectTo(request, "/connexion", csp, path === "/" ? undefined : path + search);
  } else if (path === "/connexion/verification" && !request.cookies.has(MFA_COOKIE)) {
    response = redirectTo(request, "/connexion", csp);
  } else {
    // Si la session vient d'être renouvelée, le rendu reçoit le nouveau jeton : sans
    // cela, la page lirait l'ancien cookie dans cette même requête.
    const requestHeaders = new Headers(request.headers);
    if (renewed) {
      request.cookies.set(ACCESS_COOKIE, renewed.access_token);
      request.cookies.set(REFRESH_COOKIE, renewed.refresh_token);
      requestHeaders.set("cookie", request.cookies.toString());
    }
    const url = request.nextUrl.clone();
    url.pathname = `/${locale}${path === "/" ? "" : path}`;
    response = withSecurityHeaders(
      NextResponse.rewrite(url, { request: { headers: requestHeaders } }),
      csp,
      // Le jeton à usage unique de l'URL ne doit fuiter dans aucun en-tête Referer.
      matches(path, TOKEN_PAGES) ? "no-referrer" : undefined,
    );
  }

  if (renewed) {
    response.cookies.set(ACCESS_COOKIE, renewed.access_token, cookieOptions(renewed.expires_in));
    response.cookies.set(
      REFRESH_COOKIE,
      renewed.refresh_token,
      cookieOptions(REFRESH_MAX_AGE_SECONDS),
    );
  } else if (sessionEnded) {
    clearSession(response);
  }
  return response;
}

export const config = {
  matcher: [
    // Tout sauf les fichiers statiques, le manifeste, le service worker et les icônes.
    "/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest|sw.js|icons/|robots.txt).*)",
  ],
};

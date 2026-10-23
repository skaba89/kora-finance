/**
 * Cookies de session du BFF (backend-for-frontend).
 *
 * Les jetons ne sont jamais exposés au JavaScript du navigateur : cookies httpOnly,
 * lus uniquement par le serveur Next (proxy, Server Components, Server Actions).
 * Ce module ne dépend que de constantes : il est utilisable dans `proxy.ts`.
 */

export const ACCESS_COOKIE = "kora_at";
export const REFRESH_COOKIE = "kora_rt";
export const MFA_COOKIE = "kora_mfa";
export const LOCALE_COOKIE = "kora_locale";

/** Marge avant expiration à partir de laquelle le proxy renouvelle le jeton d'accès. */
export const ACCESS_REFRESH_MARGIN_SECONDS = 60;
export const REFRESH_MAX_AGE_SECONDS = 30 * 24 * 3600;

export type CookieOptions = {
  httpOnly: boolean;
  secure: boolean;
  sameSite: "lax" | "strict";
  path: string;
  maxAge: number;
};

export function secureCookies(): boolean {
  // En local (HTTP), un cookie « Secure » ne serait jamais renvoyé par le navigateur.
  return (process.env.KORA_PUBLIC_URL ?? "").startsWith("https://");
}

export function cookieOptions(maxAge: number): CookieOptions {
  return { httpOnly: true, secure: secureCookies(), sameSite: "lax", path: "/", maxAge };
}

/** Lit l'expiration (`exp`) d'un JWT sans vérifier sa signature : l'API, elle, vérifie. */
export function jwtExpiresAt(token: string): number | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const json = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      exp?: unknown;
    };
    return typeof json.exp === "number" ? json.exp : null;
  } catch {
    return null;
  }
}

export function isFresh(token: string | undefined, nowSeconds = Date.now() / 1000): boolean {
  if (!token) return false;
  const exp = jwtExpiresAt(token);
  return exp !== null && exp - nowSeconds > ACCESS_REFRESH_MARGIN_SECONDS;
}

/** Destination de retour après connexion : chemin interne uniquement (pas d'open redirect). */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dossiers";
  }
  return value;
}

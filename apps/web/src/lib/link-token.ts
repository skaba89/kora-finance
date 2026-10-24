/** Jeton à usage unique lu dans l'URL d'un lien reçu par email (`?jeton=`). */
export function tokenFrom(params: Record<string, string | string[] | undefined>): string | null {
  const value = params.jeton;
  return typeof value === "string" && /^[A-Za-z0-9_-]{20,200}$/.test(value) ? value : null;
}

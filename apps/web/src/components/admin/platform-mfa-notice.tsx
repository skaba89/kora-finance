import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Double authentification et administration plateforme.
 * - `refused` : l'API a refusé l'accès (KORA_PLATFORM_ADMIN_REQUIRE_MFA actif).
 * - sinon : avertissement préventif, l'administration reste utilisable.
 */
export function PlatformMfaNotice({ refused, locale }: { refused: boolean; locale: string }) {
  const en = locale === "en";
  const label = (fr: string, english: string) => (en ? english : fr);
  const link = (
    <Link href="/compte/securite" className="font-medium underline underline-offset-4">
      {label("Activer la double authentification", "Enable two-factor authentication")}
    </Link>
  );
  if (refused) {
    return (
      <Alert variant="destructive" role="alert" className="mb-4">
        <AlertTitle>{label("Accès à l’administration refusé", "Administration access denied")}</AlertTitle>
        <AlertDescription>
          <p>
            {label(
              "L’administration de la plateforme exige la double authentification sur votre compte.",
              "Platform administration requires two-factor authentication on your account.",
            )}
          </p>
          <p>{link}</p>
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert role="status" className="mb-4">
      <AlertTitle>{label("Double authentification recommandée", "Two-factor authentication recommended")}</AlertTitle>
      <AlertDescription>
        <p>
          {label(
            "Votre compte administre la plateforme sans double authentification ; elle pourra être exigée.",
            "Your account administers the platform without two-factor authentication; it may become required.",
          )}
        </p>
        <p>{link}</p>
      </AlertDescription>
    </Alert>
  );
}

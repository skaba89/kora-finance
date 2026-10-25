import { Alert, AlertDescription } from "@/components/ui/alert";
import { emailsEnabled } from "@/lib/emails";

/** Avertissement affiché quand l'installation n'envoie pas d'emails (à placer sous Suspense). */
export async function EmailsDisabledNotice({ message }: { message: string }) {
  if (await emailsEnabled()) return null;
  return (
    <Alert role="note">
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

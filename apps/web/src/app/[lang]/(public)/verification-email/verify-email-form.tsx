"use client";

import Link from "next/link";
import { useActionState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { verifyEmailAction } from "@/lib/actions/auth";
import { IDLE } from "@/lib/actions/state";

/**
 * Confirmation par un clic (POST) et non à l'ouverture du lien : les antivirus de
 * messagerie qui visitent les liens ne doivent pas consommer le jeton.
 */
export function VerifyEmailForm({
  token,
  labels,
}: {
  token: string;
  labels: { submit: string; pending: string; continue: string };
}) {
  const [state, formAction, pending] = useActionState(verifyEmailAction, IDLE);
  if (state.status === "success") {
    return (
      <div className="flex flex-col gap-4">
        <p role="status" className="rounded-md bg-teal-50 px-3 py-2 text-sm text-teal-900">
          {state.message}
        </p>
        <div>
          <Button asChild>
            <Link href="/dossiers">{labels.continue}</Link>
          </Button>
        </div>
      </div>
    );
  }
  return (
    <form action={formAction} className="flex flex-col gap-4">
      <input type="hidden" name="token" value={token} />
      {state.status === "error" && state.message ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
      ) : null}
      <div>
        <Button type="submit" disabled={pending} aria-busy={pending}>
          {pending ? labels.pending : labels.submit}
        </Button>
      </div>
    </form>
  );
}

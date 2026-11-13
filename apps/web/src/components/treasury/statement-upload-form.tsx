"use client";

import { useActionState, useRef } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ActionState } from "@/lib/actions/state";

const IDLE: ActionState = { status: "idle" };

/**
 * Import d'un relevé bancaire (OFX, CSV ou Excel .xlsx). Pas de réduction ici :
 * le fichier est envoyé brut tel qu'exporté par la banque ou l'opérateur Mobile
 * Money (un fichier remanié perdrait sa valeur de traçabilité).
 */
export function StatementUploadForm({
  action,
  labels,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  labels: {
    file: string;
    hint: string;
    submit: string;
    pending: string;
  };
}) {
  const [state, formAction, pending] = useActionState(action, IDLE);
  const formRef = useRef<HTMLFormElement>(null);

  return (
    <form
      ref={formRef}
      action={async (formData) => {
        await formAction(formData);
        formRef.current?.reset();
      }}
      className="flex flex-col gap-3"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="statement-file">{labels.file}</Label>
        <Input
          id="statement-file"
          name="file"
          type="file"
          accept=".ofx,.csv,.txt,.xlsx,application/octet-stream,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          required
        />
        <p className="text-muted-foreground text-xs">{labels.hint}</p>
      </div>
      {state.status === "error" && state.message ? (
        <Alert variant="destructive">
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
      ) : null}
      {state.status === "success" && state.message ? (
        <Alert>
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
      ) : null}
      <Button type="submit" disabled={pending} className="w-fit">
        {pending ? labels.pending : labels.submit}
      </Button>
    </form>
  );
}

"use client";

import { startTransition, useActionState, useRef, useState, useTransition } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ActionState } from "@/lib/actions/state";
import { ACCEPT_ATTRIBUTE, MAX_BYTES, shrinkImage } from "@/lib/attachments";

const IDLE: ActionState = { status: "idle" };

export type UploadLabels = {
  file: string;
  hint: string;
  submit: string;
  pending: string;
  preparing: string;
  tooLarge: string;
};

/**
 * Envoi d'une pièce. Avec JavaScript, les photos lourdes sont d'abord réduites dans le
 * navigateur (envoi plus court en 3G) ; sans JavaScript, le formulaire part tel quel.
 */
export function UploadForm({
  action,
  labels,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  labels: UploadLabels;
}) {
  const [state, formAction, pending] = useActionState(action, IDLE);
  const [preparing, startPreparing] = useTransition();
  const [localError, setLocalError] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const busy = pending || preparing;

  return (
    <form
      ref={formRef}
      action={formAction}
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        const form = event.currentTarget;
        const input = form.elements.namedItem("file");
        const file = input instanceof HTMLInputElement ? input.files?.[0] : undefined;
        if (!file) return;
        event.preventDefault();
        setLocalError(null);
        startPreparing(async () => {
          const prepared = await shrinkImage(file);
          if (prepared.size > MAX_BYTES) {
            setLocalError(labels.tooLarge);
            return;
          }
          const data = new FormData();
          data.set("file", prepared);
          // Après un `await`, l'envoi doit être replacé dans une transition.
          startTransition(() => formAction(data));
          form.reset();
        });
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="attachment-file">{labels.file}</Label>
        <Input id="attachment-file" name="file" type="file" accept={ACCEPT_ATTRIBUTE} required />
        <p className="text-muted-foreground text-xs">{labels.hint}</p>
      </div>
      {localError || (state.status === "error" && state.message) ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{localError ?? state.message}</AlertDescription>
        </Alert>
      ) : null}
      {state.status === "success" && state.message && !localError ? (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {state.message}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="outline" disabled={busy} aria-busy={busy}>
          {preparing ? labels.preparing : pending ? labels.pending : labels.submit}
        </Button>
      </div>
    </form>
  );
}

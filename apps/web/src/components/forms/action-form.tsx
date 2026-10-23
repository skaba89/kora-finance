"use client";

import { type ReactNode, useActionState, useEffect, useRef } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ActionState } from "@/lib/actions/state";
import { cn } from "@/lib/utils";

const IDLE: ActionState = { status: "idle" };

type Props = {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  submitLabel: string;
  pendingLabel: string;
  children?: ReactNode;
  className?: string;
  /** Vide le formulaire après succès (ajout d'éléments en série). */
  resetOnSuccess?: boolean;
  variant?: "default" | "outline" | "destructive" | "secondary";
  /** Message de confirmation natif avant envoi (actions destructrices). */
  confirm?: string;
  /** Rendu des données renvoyées par l'action (ex. codes de secours). */
  renderResult?: (state: ActionState) => ReactNode;
};

/**
 * Formulaire branché sur une Server Action : fonctionne sans JavaScript (envoi
 * classique), affiche l'état d'envoi et les erreurs renvoyées par l'API.
 */
export function ActionForm({
  action,
  submitLabel,
  pendingLabel,
  children,
  className,
  resetOnSuccess,
  variant = "default",
  confirm,
  renderResult,
}: Props) {
  const [state, formAction, pending] = useActionState(action, IDLE);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (resetOnSuccess && state.status === "success") formRef.current?.reset();
  }, [state, resetOnSuccess]);

  return (
    <form
      ref={formRef}
      action={formAction}
      className={cn("flex flex-col gap-4", className)}
      onSubmit={(event) => {
        if (confirm && !window.confirm(confirm)) event.preventDefault();
      }}
    >
      {children}
      {state.status === "error" && state.message ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>
            <p>{state.message}</p>
            {state.errors && state.errors.length > 0 ? (
              <ul className="mt-1 list-disc pl-5">
                {state.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
      {state.status === "success" && state.message ? (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {state.message}
        </p>
      ) : null}
      {renderResult ? renderResult(state) : null}
      <div>
        <Button type="submit" variant={variant} disabled={pending} aria-busy={pending}>
          {pending ? pendingLabel : submitLabel}
        </Button>
      </div>
    </form>
  );
}

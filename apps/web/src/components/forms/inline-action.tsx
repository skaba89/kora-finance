"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import type { ActionState } from "@/lib/actions/state";

const IDLE: ActionState = { status: "idle" };

/** Bouton d'action unitaire (dans une ligne de tableau) avec message d'erreur en place. */
export function InlineAction({
  action,
  label,
  pendingLabel,
  confirm,
  variant = "outline",
  showSuccess = false,
}: {
  action: (state: ActionState) => Promise<ActionState>;
  label: string;
  pendingLabel: string;
  confirm?: string;
  variant?: "outline" | "destructive" | "secondary" | "ghost";
  /** Affiche le message de succès renvoyé par l'action (ex. « email envoyé »). */
  showSuccess?: boolean;
}) {
  const [state, formAction, pending] = useActionState(action, IDLE);
  return (
    <form
      action={formAction}
      className="flex flex-col items-start gap-1"
      onSubmit={(event) => {
        if (confirm && !window.confirm(confirm)) event.preventDefault();
      }}
    >
      <Button type="submit" size="sm" variant={variant} disabled={pending}>
        {pending ? pendingLabel : label}
      </Button>
      {state.status === "error" && state.message ? (
        <p role="alert" className="text-destructive max-w-xs text-xs">
          {state.message}
        </p>
      ) : null}
      {showSuccess && state.status === "success" && state.message ? (
        <p role="status" className="max-w-xs text-xs text-emerald-700 dark:text-emerald-400">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}

"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import type { ActionState } from "@/lib/actions/state";
import { interpolate } from "@/lib/i18n/interpolate";

type Verification = { ok: boolean; events_checked: number; broken_at_seq: number | null; reason: string | null };

export function AuditVerifier({
  action,
  labels,
}: {
  action: (state: ActionState) => Promise<ActionState>;
  labels: { verify: string; pending: string; ok: string; broken: string };
}) {
  const [state, formAction, pending] = useActionState(action, { status: "idle" } as ActionState);
  const result = state.data as Verification | undefined;
  return (
    <form action={formAction} className="flex flex-col items-start gap-2 sm:items-end">
      <Button type="submit" variant="outline" disabled={pending}>
        {pending ? labels.pending : labels.verify}
      </Button>
      {result ? (
        <p
          role="status"
          className={result.ok ? "text-sm text-emerald-700" : "text-destructive text-sm font-medium"}
        >
          {result.ok
            ? interpolate(labels.ok, { count: result.events_checked })
            : interpolate(labels.broken, { seq: result.broken_at_seq ?? "?", reason: result.reason ?? "" })}
        </p>
      ) : state.status === "error" && state.message ? (
        <p role="alert" className="text-destructive text-sm">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}

"use client";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import type { ActionState } from "@/lib/actions/state";

/** Bornes identiques à l'API (`LicenseSuspensionIn.reason`). */
export const REASON_MIN_LENGTH = 3;
export const REASON_MAX_LENGTH = 500;

export type LicenseSuspensionLabels = {
  suspend: string;
  reactivate: string;
  reason: string;
  reasonHint: string;
  confirmSuspend: string;
  confirmReactivate: string;
  pending: string;
};

/**
 * Suspension ou réactivation d'une période commerciale : motif obligatoire
 * (journalisé) et confirmation explicite. L'état affiché sert d'état attendu
 * côté serveur : une période modifiée entre-temps est refusée (409).
 */
export function LicenseSuspensionForm({
  action,
  suspended,
  labels,
  fieldId,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  suspended: boolean;
  labels: LicenseSuspensionLabels;
  fieldId: string;
}) {
  return (
    <ActionForm
      action={action}
      submitLabel={suspended ? labels.reactivate : labels.suspend}
      pendingLabel={labels.pending}
      variant={suspended ? "outline" : "destructive"}
      confirm={suspended ? labels.confirmReactivate : labels.confirmSuspend}
      resetOnSuccess
      className="gap-2"
    >
      <Field
        id={`motif-${fieldId}`}
        name="reason"
        label={labels.reason}
        hint={labels.reasonHint}
        required
        minLength={REASON_MIN_LENGTH}
        maxLength={REASON_MAX_LENGTH}
        autoComplete="off"
      />
    </ActionForm>
  );
}

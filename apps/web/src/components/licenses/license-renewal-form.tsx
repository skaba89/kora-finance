"use client";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { REASON_MAX_LENGTH, REASON_MIN_LENGTH } from "@/components/licenses/license-suspension-form";
import type { ActionState } from "@/lib/actions/state";
import { nextDay } from "@/lib/licenses";

export type LicenseRenewalLabels = {
  submit: string;
  endsOn: string;
  endsOnHint: string;
  kind: string;
  kinds: { paid: string; trial: string };
  reason: string;
  reasonHint: string;
  confirm: string;
  pending: string;
};

/** Ajout d'une période adjacente : fin, type et motif obligatoires, confirmation explicite. */
export function LicenseRenewalForm({
  action,
  previousEndsOn,
  labels,
  fieldId,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  previousEndsOn: string;
  labels: LicenseRenewalLabels;
  fieldId: string;
}) {
  return (
    <ActionForm
      action={action}
      submitLabel={labels.submit}
      pendingLabel={labels.pending}
      variant="outline"
      confirm={labels.confirm}
      resetOnSuccess
      className="gap-2"
    >
      <Field
        id={`fin-${fieldId}`}
        name="ends_on"
        type="date"
        label={labels.endsOn}
        hint={labels.endsOnHint}
        required
        min={nextDay(previousEndsOn)}
      />
      <SelectField
        id={`type-${fieldId}`}
        name="kind"
        label={labels.kind}
        defaultValue="paid"
        options={[
          { value: "paid", label: labels.kinds.paid },
          { value: "trial", label: labels.kinds.trial },
        ]}
      />
      <Field
        id={`motif-renouvellement-${fieldId}`}
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

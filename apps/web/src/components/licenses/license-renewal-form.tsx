"use client";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { REASON_MAX_LENGTH, REASON_MIN_LENGTH } from "@/components/licenses/license-suspension-form";
import type { ActionState } from "@/lib/actions/state";

type Period = { id: string; starts_on: string; ends_on: string; suspended: boolean };

export type RenewalAvailability = "available" | "suspended" | "expired" | "renewed";

/** Lendemain d'une date civile AAAA-MM-JJ, calculé en UTC (aucune heure locale). */
export function nextDay(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00.000Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

/**
 * Miroir des refus de l'API, pour ne proposer que les renouvellements possibles.
 * L'API reste l'autorité : elle revérifie tout sous verrou.
 */
export function renewalAvailability(period: Period, all: Period[], today: string): RenewalAvailability {
  if (all.some((other) => other.id !== period.id && other.starts_on === period.ends_on)) return "renewed";
  if (period.suspended) return "suspended";
  // Fin exclusive : renouveler le jour même de la fin reste admis (pas de rétroactivité).
  if (period.ends_on < today) return "expired";
  return "available";
}

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

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { updateScheduleAction } from "@/lib/actions/sales";
import { formatMoney } from "@/lib/format";
import type { Dictionary, SalesDocumentsPage, SalesSchedules } from "./types";

const STATUS_VARIANTS = {
  settled: "secondary",
  late: "destructive",
  upcoming: "outline",
} as const;

/** Échéanciers clients (lot B-4) : les plans posés, puis le formulaire de
 * planification d'une facture émise non soldée (tranches remplacées en bloc).
 * Un échéancier n'écrit jamais en comptabilité : c'est un outil de suivi du
 * recouvrement, le solde reste calculé depuis les règlements (4C). */
export function SalesScheduleCard({
  companyId,
  documents,
  schedules,
  t,
  manage,
}: {
  companyId: string;
  documents: SalesDocumentsPage;
  schedules: SalesSchedules;
  t: Dictionary;
  manage: boolean;
}) {
  const solvables = documents.items.filter(
    (d) => d.doc_kind === "invoice" && d.status === "ISSUED" && (d.outstanding_ttc ?? 0) > 0,
  );
  const labels: Record<string, string> = {
    settled: t.sales.scheduleSettled,
    late: t.sales.scheduleLate,
    upcoming: t.sales.scheduleUpcoming,
  };
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.scheduleTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">{t.sales.scheduleSubtitle}</p>
      </CardHeader>
      <CardContent>
        {schedules.items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t.sales.scheduleEmpty}</p>
        ) : (
          <div className="space-y-4">
            {schedules.items.map((plan) => (
              <div key={plan.document_id} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-mono text-xs">FAC-{plan.document_number}</span>
                    <span className="ml-2 text-sm">{plan.partner_name}</span>
                  </div>
                  <div className="text-sm">
                    <span className="text-muted-foreground">
                      {t.sales.schedulePlanned}{" "}
                    </span>
                    {formatMoney(plan.planned_total, plan.currency)}
                    {" — "}
                    <span className="text-muted-foreground">{t.sales.scheduleRestant} </span>
                    {formatMoney(plan.outstanding_ttc, plan.currency)}
                  </div>
                </div>
                <ul className="mt-3 space-y-1.5">
                  {plan.lines.map((line) => (
                    <li key={line.line_no} className="flex items-center gap-2 text-sm">
                      <Badge variant={STATUS_VARIANTS[line.status]}>{labels[line.status]}</Badge>
                      <span>{line.expected_on}</span>
                      <span className="font-mono text-xs">
                        {formatMoney(line.expected_amount, plan.currency)}
                      </span>
                      {line.note && <span className="text-muted-foreground">— {line.note}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {manage && solvables.length > 0 && (
          <ActionForm
            action={updateScheduleAction.bind(null, companyId)}
            className="mt-6 space-y-4 border-t pt-6"
            submitLabel={t.sales.scheduleSave}
            pendingLabel={t.common.pending}
          >
            <SelectField
              label={t.sales.schedulePick}
              name="document_id"
              required
              options={[
                { value: "", label: t.sales.schedulePick },
                ...solvables.map((d) => ({
                  value: d.id,
                  label: `FAC-${d.number} — ${formatMoney(d.outstanding_ttc ?? 0, d.currency)}`,
                })),
              ]}
            />
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label={t.sales.scheduleDate1} name="expected_on_1" type="date" required />
              <Field
                label={t.sales.scheduleAmount1}
                name="expected_amount_1"
                type="number"
                min="1"
                step="1"
                required
              />
              <Field label={t.sales.scheduleNote1} name="note_1" maxLength={500} />
              <Field label={t.sales.scheduleDate2} name="expected_on_2" type="date" />
              <Field
                label={t.sales.scheduleAmount2}
                name="expected_amount_2"
                type="number"
                min="1"
                step="1"
              />
              <Field label={t.sales.scheduleNote2} name="note_2" maxLength={500} />
              <Field label={t.sales.scheduleDate3} name="expected_on_3" type="date" />
              <Field
                label={t.sales.scheduleAmount3}
                name="expected_amount_3"
                type="number"
                min="1"
                step="1"
              />
              <Field label={t.sales.scheduleNote3} name="note_3" maxLength={500} />
            </div>
            <p className="text-muted-foreground text-xs">{t.sales.scheduleHint}</p>
          </ActionForm>
        )}
      </CardContent>
    </Card>
  );
}

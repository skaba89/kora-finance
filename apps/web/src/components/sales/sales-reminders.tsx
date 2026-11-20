import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createReminderAction,
  resendReminderAction,
  updateReminderPolicyAction,
} from "@/lib/actions/sales";
import { formatMoney } from "@/lib/format";
import type { Dictionary, SalesDocumentsPage, SalesOverdue, SalesReminderPolicy, SalesRemindersPage } from "./types";

/** Factures échues : qui, combien, de combien de jours — base des relances. */
export function SalesOverdueCard({
  companyId,
  overdue,
  t,
  manage,
}: {
  companyId: string;
  overdue: SalesOverdue;
  t: Dictionary;
  manage: boolean;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.reminderTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">
          {t.sales.reminderAsOf} {overdue.as_of} — {overdue.items.length} {t.sales.reminderOverdueCount}
        </p>
      </CardHeader>
      <CardContent>
        {overdue.items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t.sales.reminderEmpty}</p>
        ) : (
          <Table className="max-md:block">
            <TableHeader className="max-md:sr-only">
              <TableRow>
                <TableHead>{t.sales.reminderOverdueDoc}</TableHead>
                <TableHead>{t.sales.reminderPartner}</TableHead>
                <TableHead>{t.sales.reminderDue}</TableHead>
                <TableHead className="text-right">{t.sales.reminderBalance}</TableHead>
                <TableHead className="text-right">{t.sales.reminderLate}</TableHead>
                <TableHead className="text-right">{t.sales.reminderCount}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="max-md:block">
              {overdue.items.map((item) => (
                <TableRow key={item.document_id} className="max-md:grid max-md:grid-cols-2 max-md:gap-x-2 max-md:py-3">
                  <TableCell className="font-mono text-xs">FAC-{item.number}</TableCell>
                  <TableCell className="whitespace-normal wrap-anywhere max-md:order-first max-md:col-span-2 max-md:font-medium">
                    {item.partner_name}
                    {item.partner_email == null && (
                      <span className="text-muted-foreground"> — {t.sales.reminderNoEmail}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right md:text-left"><span className="text-muted-foreground block text-xs md:hidden">{t.sales.reminderDue}</span>{item.due_on}</TableCell>
                  <TableCell className="text-right whitespace-normal max-md:text-left">
                    <span className="text-muted-foreground block text-xs md:hidden">{t.sales.reminderBalance}</span>
                    {formatMoney(item.outstanding_ttc, item.currency)}
                  </TableCell>
                  <TableCell className="text-right"><span className="text-muted-foreground block text-xs md:hidden">{t.sales.reminderLate}</span>{item.days_late} j</TableCell>
                  <TableCell className="text-right max-md:text-left"><span className="text-muted-foreground block text-xs md:hidden">{t.sales.reminderCount}</span>{item.reminders_count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {manage && overdue.items.length > 0 && (
          <ActionForm
            action={createReminderAction.bind(null, companyId)}
            className="mt-6 space-y-4"
            submitLabel={t.sales.reminderRecord}
            pendingLabel={t.common.pending}
          >
            <h3 className="text-sm font-medium">{t.sales.reminderFormTitle}</h3>
            <div className="grid gap-4 sm:grid-cols-3">
              <SelectField
                label={t.sales.reminderDoc}
                name="document_id"
                required
                options={[
                  { value: "", label: t.sales.reminderDocPlaceholder },
                  ...overdue.items
                    .filter((item) => item.partner_email != null)
                    .map((item) => ({
                      value: item.document_id,
                      label: `FAC-${item.number} — ${item.partner_name} · ${formatMoney(item.outstanding_ttc, item.currency)} · ${item.days_late} j · ${t.sales.reminderNext} ${item.next_level}`,
                    })),
                ]}
              />
              <Field label={t.sales.reminderNote} name="note" />
            </div>
            <p className="text-muted-foreground text-xs">{t.sales.reminderHint}</p>
          </ActionForm>
        )}
      </CardContent>
    </Card>
  );
}

/** Historique des relances envoyées, avec renvoi possible. */
export function SalesRemindersHistoryCard({
  companyId,
  reminders,
  documents,
  t,
  manage,
}: {
  companyId: string;
  reminders: SalesRemindersPage;
  documents: SalesDocumentsPage;
  t: Dictionary;
  manage: boolean;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.remindersHistoryTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        {reminders.items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t.sales.remindersHistoryEmpty}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.sales.reminderOn}</TableHead>
                <TableHead>{t.sales.reminderOverdueDoc}</TableHead>
                <TableHead>{t.sales.reminderLevel}</TableHead>
                <TableHead>{t.sales.reminderTo}</TableHead>
                <TableHead>{t.sales.reminderNote}</TableHead>
                <TableHead className="text-right">{t.common.actions}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {reminders.items.map((reminder) => (
                <TableRow key={reminder.id}>
                  <TableCell>{reminder.reminded_on}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {(() => {
                      const target = documents.items.find(
                        (document) => document.id === reminder.document_id,
                      );
                      return target?.number != null ? `FAC-${target.number}` : "…";
                    })()}
                  </TableCell>
                  <TableCell>
                    {(t.sales.reminderLevels as Record<string, string>)[
                      reminder.level
                    ] ?? `#${reminder.level}`}
                  </TableCell>
                  <TableCell className="text-xs">{reminder.email_to}</TableCell>
                  <TableCell>{reminder.note ?? "—"}</TableCell>
                  <TableCell className="text-right">
                    {manage && (
                      <InlineAction
                        action={resendReminderAction.bind(null, companyId, reminder.id)}
                        confirm={t.sales.reminderConfirmResend}
                        label={t.sales.reminderResend}
                        pendingLabel={t.common.pending}
                      />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

/** Relances automatiques (Phase B, lot 2) : politique par dossier, exécution
 * périodique côté worker — une relance par facture et par jour, aucune
 * écriture comptable. La carte est visible des lecteurs ; le réglage exige
 * sales:manage (PUT audité). */
export function SalesReminderPolicyCard({
  companyId,
  policy,
  t,
  manage,
}: {
  companyId: string;
  policy: SalesReminderPolicy;
  t: Dictionary;
  manage: boolean;
}) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>{t.sales.autoTitle}</CardTitle>
        <p className="text-muted-foreground text-sm">
          {policy.updated_at
            ? `${t.sales.autoUpdated} : ${policy.updated_at.slice(0, 10)}`
            : t.sales.autoUnconfigured}
        </p>
      </CardHeader>
      <CardContent>
        {manage ? (
          <ActionForm
            action={updateReminderPolicyAction.bind(null, companyId)}
            className="space-y-4"
            submitLabel={t.sales.autoSave}
            pendingLabel={t.common.pending}
          >
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="enabled"
                defaultChecked={policy.enabled}
                className="h-4 w-4"
              />
              {t.sales.autoEnabled}
            </label>
            <div className="max-w-sm">
              <Field
                label={t.sales.autoOffsets}
                name="offsets_days"
                defaultValue={policy.offsets_days.join(", ")}
                placeholder={t.sales.autoOffsetsPlaceholder}
                inputMode="numeric"
                required
              />
            </div>
            <p className="text-muted-foreground text-xs">{t.sales.autoOffsetsHint}</p>
          </ActionForm>
        ) : (
          <p className="text-muted-foreground text-sm">
            {t.sales.autoState} :{" "}
            {policy.enabled
              ? `${policy.offsets_days.join(" / ")} j`
              : "—"}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

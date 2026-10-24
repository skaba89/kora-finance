import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { EntryEditor } from "@/components/ledger/entry-editor";
import { editorLabels } from "@/components/ledger/labels";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { deleteEntryAction, postEntryAction, reverseEntryAction, saveEntryAction } from "@/lib/actions/ledger";
import { can, getActiveAccounts, getCompany, getEntry, getJournals } from "@/lib/dal";
import { currencyDecimals, formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.entries.title };
}

type Entry = Awaited<ReturnType<typeof getEntry>>;

function entryRef(entry: Entry) {
  return entry.number === null ? entry.journal_code : `${entry.journal_code} n° ${entry.number}`;
}

export default async function EntryPage({ params }: PageProps<"/[lang]/dossiers/[companyId]/ecritures/[entryId]">) {
  const { companyId, entryId } = await params;
  const [{ t, locale }, company, entry] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getEntry(companyId, entryId),
  ]);
  const base = `/dossiers/${companyId}/ecritures`;
  const currency = company.company.currency;
  const money = (value: string) => formatMoney(BigInt(value), currency, locale);
  const title = `${entryRef(entry)} — ${entry.label}`;

  if (entry.status === "DRAFT" && can(company, "entries:write")) {
    const [journals, accounts] = await Promise.all([getJournals(companyId), getActiveAccounts(companyId)]);
    return (
      <>
        <PageHeader title={t.entries.editTitle} subtitle={t.entries.draftNotice} />
        <EntryEditor
          action={saveEntryAction.bind(null, companyId)}
          journals={journals.filter((j) => j.is_active).map(({ id, code, label }) => ({ id, code, label }))}
          accounts={accounts.map(({ id, number, label }) => ({ id, number, label }))}
          initial={{
            id: entry.id,
            journal_id: entry.journal_id,
            entry_date: entry.entry_date,
            reference: entry.reference,
            label: entry.label,
            lines: entry.lines.map(({ account_id, label, debit, credit }) => ({ account_id, label, debit, credit })),
          }}
          defaultDate={entry.entry_date}
          currency={currency}
          decimals={currencyDecimals(currency)}
          locale={locale}
          canPost={can(company, "entries:post")}
          labels={editorLabels(t)}
        />
        <div className="mt-8 flex flex-wrap gap-3 border-t pt-6">
          {can(company, "entries:post") ? (
            <InlineAction
              action={postEntryAction.bind(null, companyId, entry.id)}
              label={t.entries.post}
              pendingLabel={t.common.pending}
              variant="secondary"
              confirm={t.entries.postConfirm}
            />
          ) : null}
          <InlineAction
            action={deleteEntryAction.bind(null, companyId, entry.id)}
            label={t.entries.deleteDraft}
            pendingLabel={t.common.pending}
            variant="destructive"
            confirm={t.entries.deleteConfirm}
          />
        </div>
      </>
    );
  }

  const [original, reversal] = await Promise.all([
    entry.reversal_of_id ? getEntry(companyId, entry.reversal_of_id) : Promise.resolve(null),
    entry.reversed_by_id ? getEntry(companyId, entry.reversed_by_id) : Promise.resolve(null),
  ]);
  const canReverse =
    entry.status === "POSTED" && !entry.reversal_of_id && !entry.reversed_by_id && can(company, "entries:post");

  return (
    <>
      <PageHeader
        title={title}
        subtitle={entry.status === "POSTED" ? t.entries.postedNotice : t.entries.draftNotice}
      />
      <dl className="mb-6 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">{t.entries.date}</dt>
          <dd>{formatDate(entry.entry_date, locale)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t.entries.reference}</dt>
          <dd>{entry.reference ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t.common.status}</dt>
          <dd>
            <Badge variant={entry.status === "POSTED" ? "secondary" : "outline"}>{t.entries.statuses[entry.status]}</Badge>
          </dd>
        </div>
        {entry.posted_at ? (
          <div>
            <dt className="text-muted-foreground">{t.entries.postedOn}</dt>
            <dd>{formatDateTime(entry.posted_at, locale)}</dd>
          </div>
        ) : null}
      </dl>

      {original ? (
        <Alert className="mb-4">
          <AlertDescription>
            <Link href={`${base}/${original.id}`} className="underline underline-offset-4">
              {interpolate(t.entries.reversalOf, { ref: entryRef(original) })}
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}
      {reversal ? (
        <Alert className="mb-4">
          <AlertDescription>
            <Link href={`${base}/${reversal.id}`} className="underline underline-offset-4">
              {interpolate(t.entries.reversedBy, { ref: entryRef(reversal) })}
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t.entries.account}</TableHead>
            <TableHead className="hidden sm:table-cell">{t.entries.lineLabel}</TableHead>
            <TableHead className="text-right">{t.entries.debit}</TableHead>
            <TableHead className="text-right">{t.entries.credit}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entry.lines.map((line) => (
            <TableRow key={line.line_no}>
              <TableCell className="whitespace-normal">
                <span className="font-mono">{line.account_number}</span> {line.account_label}
              </TableCell>
              <TableCell className="hidden whitespace-normal sm:table-cell">{line.label}</TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {line.debit !== "0" ? money(line.debit) : ""}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {line.credit !== "0" ? money(line.credit) : ""}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell className="font-medium">{t.entries.totals}</TableCell>
            <TableCell className="hidden sm:table-cell" />
            <TableCell className="text-right whitespace-nowrap tabular-nums">{money(entry.total_debit)}</TableCell>
            <TableCell className="text-right whitespace-nowrap tabular-nums">{money(entry.total_credit)}</TableCell>
          </TableRow>
        </TableFooter>
      </Table>

      {canReverse ? (
        <Card className="mt-8 max-w-md">
          <CardHeader>
            <CardTitle className="text-base">{t.entries.reverse}</CardTitle>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={reverseEntryAction.bind(null, companyId, entry.id)}
              submitLabel={t.entries.reverse}
              pendingLabel={t.common.pending}
              variant="outline"
              confirm={t.entries.reverseConfirm}
            >
              <Field
                label={t.entries.reversalDate}
                name="entry_date"
                type="date"
                defaultValue={entry.entry_date}
                required
              />
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}

      <p className="mt-8">
        <Link href={base} className="text-sm underline underline-offset-4">
          {t.entries.backToList}
        </Link>
      </p>
    </>
  );
}

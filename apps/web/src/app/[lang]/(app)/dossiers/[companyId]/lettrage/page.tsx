import type { Metadata } from "next";
import Link from "next/link";

import { InlineAction } from "@/components/forms/inline-action";
import { LetteringForm } from "@/components/ledger/lettering-form";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { autoLetterAction, letterAction, unletterAction } from "@/lib/actions/ledger";
import { can, getAccounts, getCompany, getLetterableLines } from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.lettering.title };
}

const STATUSES = ["open", "lettered", "all"] as const;
const PAGE_SIZE = 200;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function LetteringPage({ params, searchParams }: PageProps<"/[lang]/dossiers/[companyId]/lettrage">) {
  const { companyId } = await params;
  const query = await searchParams;
  const [{ t, locale }, company] = await Promise.all([getDictionary(), getCompany(companyId)]);
  const l = t.lettering;
  const number = /^4[0-9]{1,11}$/.test(one(query.compte) ?? "") ? one(query.compte) : undefined;
  const rawNumber = one(query.compte);
  const status = STATUSES.find((s) => s === one(query.statut)) ?? "open";
  const page = Math.max(1, Number.parseInt(one(query.page) ?? "1", 10) || 1);
  const account = number
    ? (await getAccounts(companyId, { q: number, limit: 50, offset: 0 })).items.find((a) => a.number === number)
    : undefined;
  const data = account
    ? await getLetterableLines(companyId, {
        account_id: account.id,
        status,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      })
    : null;
  const manage = can(company, "lettering:manage");
  const currency = company.company.currency;
  const signed = (value: string) => {
    const amount = BigInt(value);
    if (amount === 0n) return formatMoney(0n, currency, locale);
    return `${formatMoney(amount < 0n ? -amount : amount, currency, locale)} ${amount < 0n ? t.reports.creditSide : t.reports.debitSide}`;
  };
  const openLines = data?.items.filter((line) => line.lettering_id === null) ?? [];
  const letteredGroups = new Map<string, { code: string; lines: NonNullable<typeof data>["items"] }>();
  for (const line of data?.items ?? []) {
    if (line.lettering_id && line.lettering_code) {
      const group = letteredGroups.get(line.lettering_id) ?? { code: line.lettering_code, lines: [] };
      group.lines.push(line);
      letteredGroups.set(line.lettering_id, group);
    }
  }

  return (
    <>
      <PageHeader title={l.title} subtitle={l.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.common.expertNotice}</p>

      <form method="get" className="mb-6 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="lettrage-compte">{l.account}</Label>
          <Input
            id="lettrage-compte"
            name="compte"
            defaultValue={rawNumber}
            inputMode="numeric"
            placeholder="411"
            className="w-32"
            aria-describedby="lettrage-compte-aide"
            required
          />
          <p id="lettrage-compte-aide" className="text-muted-foreground text-xs">
            {l.accountHint}
          </p>
        </div>
        <select
          name="statut"
          defaultValue={status}
          aria-label={t.common.status}
          className="border-input bg-background mb-5 h-9 rounded-md border px-3 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {l.statuses[s]}
            </option>
          ))}
        </select>
        <Button type="submit" variant="secondary" className="mb-5">
          {t.reports.show}
        </Button>
      </form>

      {!rawNumber ? <p className="text-muted-foreground text-sm">{l.chooseAccount}</p> : null}
      {rawNumber && !number ? (
        <p role="alert" className="text-destructive text-sm">
          {l.notLetterable}
        </p>
      ) : null}
      {number && !account ? (
        <p role="alert" className="text-destructive text-sm">
          {interpolate(t.reports.unknownAccount, { number })}
        </p>
      ) : null}

      {data ? (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">
                <span className="font-mono">{data.account_number}</span> {data.account_label}
              </h2>
              <p className="text-sm">
                {l.openBalance} : <span className="font-medium tabular-nums">{signed(data.open_balance)}</span>
              </p>
            </div>
            {manage ? (
              <div className="flex max-w-sm flex-col items-end gap-1">
                <InlineAction
                  action={autoLetterAction.bind(null, companyId, data.account_id)}
                  label={l.auto}
                  pendingLabel={t.common.pending}
                  variant="secondary"
                  showSuccess
                />
                <p className="text-muted-foreground text-right text-xs">{l.autoHint}</p>
              </div>
            ) : null}
          </div>

          {data.items.length === 0 ? <p className="text-muted-foreground text-sm">{l.empty}</p> : null}

          {openLines.length > 0 ? (
            <LetteringForm
              action={letterAction.bind(null, companyId, data.account_id)}
              lines={openLines}
              currency={currency}
              locale={locale}
              canManage={manage}
              labels={{
                selection: l.selection,
                selected: l.selected,
                letter: l.letter,
                selectionHint: l.selectionHint,
                difference: t.entries.difference,
                balanced: t.entries.balanced,
                select: l.select,
                debitSide: t.reports.debitSide,
                creditSide: t.reports.creditSide,
                pending: t.common.pending,
              }}
            />
          ) : null}

          {data.total > PAGE_SIZE ? (
            <nav className="flex items-center justify-between text-sm" aria-label="pagination">
              <span className="text-muted-foreground">
                {interpolate(t.common.pageRange, {
                  from: data.offset + 1,
                  to: data.offset + data.items.length,
                  total: data.total,
                })}
              </span>
              <div className="flex gap-2">
                {page > 1 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={`?compte=${number}&statut=${status}&page=${page - 1}`}>{t.common.previous}</Link>
                  </Button>
                ) : null}
                {data.offset + data.items.length < data.total ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={`?compte=${number}&statut=${status}&page=${page + 1}`}>{t.common.next}</Link>
                  </Button>
                ) : null}
              </div>
            </nav>
          ) : null}

          {[...letteredGroups.entries()].map(([letteringId, group]) => (
            <section key={letteringId} className="rounded-md border" aria-label={`${l.code} ${group.code}`}>
              <div className="bg-muted/40 flex items-center justify-between gap-3 p-3">
                <Badge variant="secondary">
                  {l.code} {group.code}
                </Badge>
                {manage ? (
                  <InlineAction
                    action={unletterAction.bind(null, companyId, letteringId)}
                    label={l.unletter}
                    pendingLabel={t.common.pending}
                    confirm={interpolate(l.unletterConfirm, { code: group.code })}
                  />
                ) : null}
              </div>
              <ul className="divide-y">
                {group.lines.map((line) => {
                  const debit = BigInt(line.debit);
                  return (
                    <li key={line.line_id} className="flex items-start justify-between gap-3 p-3 text-sm">
                      <span className="flex min-w-0 flex-col">
                        <span className="text-muted-foreground tabular-nums">
                          {formatDate(line.entry_date, locale)} · {line.journal_code} {line.number}
                          {line.reference ? ` · ${line.reference}` : ""}
                        </span>
                        <span className="break-words">{line.label}</span>
                      </span>
                      <span className="whitespace-nowrap tabular-nums">
                        {formatMoney(debit > 0n ? debit : BigInt(line.credit), currency, locale)}{" "}
                        {debit > 0n ? t.reports.debitSide : t.reports.creditSide}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      ) : null}
    </>
  );
}

import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { createAccountAction, toggleAccountAction } from "@/lib/actions/companies";
import { can, getAccounts, getCompany } from "@/lib/dal";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.chart.title };
}

const PAGE_SIZE = 50;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ChartPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/parametres/plan-comptable">) {
  const { companyId } = await params;
  const query = await searchParams;
  const q = one(query.q)?.slice(0, 100) || undefined;
  const classNumber = Number(one(query.classe));
  const accountClass = Number.isInteger(classNumber) && classNumber >= 1 && classNumber <= 8 ? classNumber : undefined;
  const activeOnly = one(query.actifs) === "1";
  const page = Math.max(1, Number.parseInt(one(query.page) ?? "1", 10) || 1);

  const [{ t }, company, accounts] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getAccounts(companyId, {
      q,
      class: accountClass,
      active_only: activeOnly,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
  ]);
  const manage = can(company, "accounts:manage");
  const pageHref = (target: number) => {
    const search = new URLSearchParams();
    if (q) search.set("q", q);
    if (accountClass) search.set("classe", String(accountClass));
    if (activeOnly) search.set("actifs", "1");
    search.set("page", String(target));
    return `?${search.toString()}`;
  };
  const from = accounts.total === 0 ? 0 : accounts.offset + 1;
  const to = accounts.offset + accounts.items.length;

  return (
    <>
      <PageHeader title={t.chart.title} subtitle={t.chart.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.common.expertNotice}</p>

      <form method="get" className="mb-4 flex flex-wrap items-end gap-3" role="search">
        <div className="flex min-w-56 flex-1 flex-col gap-1.5">
          <label htmlFor="recherche-compte" className="text-sm font-medium">
            {t.common.search}
          </label>
          <Input id="recherche-compte" name="q" defaultValue={q} placeholder={t.chart.searchPlaceholder} />
        </div>
        <select
          name="classe"
          defaultValue={accountClass ?? ""}
          aria-label={t.common.filter}
          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
        >
          <option value="">{t.chart.allClasses}</option>
          {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
            <option key={n} value={n}>
              {interpolate(t.chart.classLabel, { n })}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="actifs" value="1" defaultChecked={activeOnly} />
          {t.chart.activeOnly}
        </label>
        <Button type="submit" variant="secondary">
          {t.common.search}
        </Button>
      </form>

      {accounts.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t.chart.empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">{t.chart.number}</TableHead>
              <TableHead>{t.chart.label}</TableHead>
              <TableHead className="hidden sm:table-cell">{t.chart.origin}</TableHead>
              {manage ? <TableHead className="w-32">{t.common.actions}</TableHead> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {accounts.items.map((account) => (
              <TableRow key={account.id} className={account.is_active ? undefined : "opacity-60"}>
                <TableCell className="font-mono tabular-nums">{account.number}</TableCell>
                <TableCell className="whitespace-normal">
                  {account.label}
                  {!account.is_active ? (
                    <Badge variant="outline" className="ml-2">
                      {t.chart.inactive}
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  <Badge variant={account.reference ? "secondary" : "outline"}>
                    {account.reference ? t.chart.reference : t.chart.custom}
                  </Badge>
                </TableCell>
                {manage ? (
                  <TableCell>
                    <InlineAction
                      action={toggleAccountAction.bind(null, companyId, account.id, !account.is_active)}
                      label={account.is_active ? t.chart.deactivate : t.chart.activate}
                      pendingLabel={t.common.pending}
                      variant="ghost"
                    />
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <nav className="mt-4 flex items-center justify-between text-sm" aria-label="Pagination">
        <span className="text-muted-foreground">
          {interpolate(t.common.pageRange, { from, to, total: accounts.total })}
        </span>
        <div className="flex gap-2">
          {page > 1 ? (
            <Button asChild variant="outline" size="sm">
              <Link href={pageHref(page - 1)}>{t.common.previous}</Link>
            </Button>
          ) : null}
          {to < accounts.total ? (
            <Button asChild variant="outline" size="sm">
              <Link href={pageHref(page + 1)}>{t.common.next}</Link>
            </Button>
          ) : null}
        </div>
      </nav>

      {manage ? (
        <Card className="mt-8 max-w-xl">
          <CardHeader>
            <CardTitle className="text-base">{t.chart.addTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={createAccountAction.bind(null, companyId)}
              submitLabel={t.common.create}
              pendingLabel={t.common.pending}
              resetOnSuccess
            >
              <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
                <Field
                  label={t.chart.number}
                  name="number"
                  inputMode="numeric"
                  pattern="[1-8][0-9]{1,11}"
                  required
                  hint={t.chart.addHint}
                />
                <Field label={t.chart.label} name="label" required maxLength={200} />
              </div>
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

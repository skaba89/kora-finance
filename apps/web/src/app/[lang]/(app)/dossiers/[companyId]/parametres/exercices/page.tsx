import type { Metadata } from "next";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createFiscalYearAction } from "@/lib/actions/companies";
import {
  closeFiscalYearAction,
  lockPeriodAction,
  reopenFiscalYearAction,
  unlockPeriodAction,
} from "@/lib/actions/ledger";
import { can, getClosingCheck, getCompany, getFiscalYears } from "@/lib/dal";
import { formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.fiscalYears.title };
}

export default async function FiscalYearsPage({
  params,
}: PageProps<"/[lang]/dossiers/[companyId]/parametres/exercices">) {
  const { companyId } = await params;
  const [{ t, locale }, company, years] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getFiscalYears(companyId),
  ]);
  const f = t.fiscalYears;
  const manage = can(company, "fiscal_years:manage");
  const closeRight = can(company, "fiscal_years:close");
  const checks = new Map(
    await Promise.all(
      years
        .filter((y) => y.status === "OPEN")
        .map(async (y) => [y.id, await getClosingCheck(companyId, y.id)] as const),
    ),
  );
  const currency = company.company.currency;

  return (
    <>
      <PageHeader title={f.title} subtitle={f.subtitle} />
      {years.length === 0 ? <p className="text-muted-foreground text-sm">{f.empty}</p> : null}
      <div className="flex flex-col gap-4">
        {years.map((year) => {
          const check = checks.get(year.id);
          const result = check ? BigInt(check.result) : 0n;
          const period = `${formatDate(year.start_date, locale)} – ${formatDate(year.end_date, locale)}`;
          return (
            <Card key={year.id} role="region" aria-label={period}>
              <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base">{period}</CardTitle>
                <Badge variant={year.status === "OPEN" ? "secondary" : "outline"}>
                  {year.status === "OPEN" ? f.OPEN : f.CLOSED}
                </Badge>
              </CardHeader>
              <CardContent className="flex flex-col gap-4 text-sm">
                {year.status === "CLOSED" ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p>{year.closed_at ? interpolate(f.closed, { date: formatDateTime(year.closed_at, locale) }) : f.CLOSED}</p>
                    {closeRight ? (
                      <InlineAction
                        action={reopenFiscalYearAction.bind(null, companyId, year.id)}
                        label={f.reopen}
                        pendingLabel={t.common.pending}
                        confirm={f.reopenConfirm}
                      />
                    ) : null}
                  </div>
                ) : (
                  <>
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <p>
                        {year.locked_until
                          ? interpolate(f.lockedUntil, { date: formatDate(year.locked_until, locale) })
                          : f.notLocked}
                      </p>
                      {year.locked_until && closeRight ? (
                        <InlineAction
                          action={unlockPeriodAction.bind(null, companyId, year.id)}
                          label={f.unlock}
                          pendingLabel={t.common.pending}
                          confirm={f.unlockConfirm}
                        />
                      ) : null}
                    </div>
                    {manage ? (
                      <ActionForm
                        action={lockPeriodAction.bind(null, companyId, year.id)}
                        submitLabel={f.lock}
                        pendingLabel={t.common.pending}
                        variant="outline"
                        className="flex-row flex-wrap items-end gap-3"
                      >
                        <Field
                          label={f.lockDate}
                          name="locked_until"
                          id={`verrou-${year.id}`}
                          type="date"
                          min={year.start_date}
                          max={year.end_date}
                          defaultValue={year.locked_until ?? ""}
                          hint={f.lockHint}
                          required
                        />
                      </ActionForm>
                    ) : null}
                    {check ? (
                      <section className="border-t pt-4" aria-label={f.closingTitle}>
                        <h3 className="mb-2 font-medium">{f.closingTitle}</h3>
                        <p>
                          {f.result} :{" "}
                          <span className="font-medium tabular-nums">
                            {formatMoney(result < 0n ? -result : result, currency, locale)}
                          </span>{" "}
                          {result !== 0n ? `(${result > 0n ? f.profit : f.loss})` : null}
                        </p>
                        <p className="text-muted-foreground">
                          {interpolate(f.carried, { count: check.carried_accounts })}
                        </p>
                        {check.issues.length > 0 ? (
                          <div className="mt-2">
                            <p>{f.blocking}</p>
                            <ul className="list-disc pl-5">
                              {check.issues.map((issue) => (
                                <li key={issue}>{issue}</li>
                              ))}
                            </ul>
                          </div>
                        ) : closeRight ? (
                          <div className="mt-3">
                            <InlineAction
                              action={closeFiscalYearAction.bind(null, companyId, year.id)}
                              label={f.close}
                              pendingLabel={t.common.pending}
                              variant="secondary"
                              confirm={f.closeConfirm}
                            />
                          </div>
                        ) : null}
                      </section>
                    ) : null}
                  </>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="text-muted-foreground mt-3 text-xs">{f.closingNotice}</p>
      {manage ? (
        <Card className="mt-6 max-w-xl">
          <CardHeader>
            <CardTitle className="text-base">{f.add}</CardTitle>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={createFiscalYearAction.bind(null, companyId)}
              submitLabel={t.common.add}
              pendingLabel={t.common.pending}
              resetOnSuccess
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={f.start} name="start_date" type="date" required />
                <Field label={f.end} name="end_date" type="date" required />
              </div>
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

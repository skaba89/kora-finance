import type { Metadata } from "next";
import Link from "next/link";

import { MonthlyChart } from "@/components/dashboard/monthly-chart";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";
import {
  can,
  getCompany,
  getCurrentUser,
  getDashboard,
  getEntries,
  getFiscalYears,
  getMembers,
  getTaxRates,
} from "@/lib/dal";
import { formatDate, formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { cn } from "@/lib/utils";

type Operation = components["schemas"]["Operation"];

const QUICK: Operation[] = ["VENTE_COMPTANT", "ACHAT_COMPTANT", "FACTURE_CLIENT", "ENCAISSEMENT_CLIENT", "FACTURE_FOURNISSEUR", "PAIEMENT_FOURNISSEUR"];

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.dashboard.title };
}

function Tile({
  label,
  value,
  hint,
  href,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  href?: string;
  tone?: "default" | "negative";
}) {
  const body = (
    <Card className={cn("h-full", href && "hover:bg-muted/50 transition-colors")}>
      <CardHeader className="gap-1">
        <p className="text-muted-foreground text-sm">{label}</p>
        <p className={cn("text-2xl font-semibold tabular-nums", tone === "negative" && "text-destructive")}>{value}</p>
        {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
      </CardHeader>
    </Card>
  );
  return href ? (
    <Link href={href} className="block h-full">
      {body}
    </Link>
  ) : (
    body
  );
}

export default async function DashboardPage({ params }: PageProps<"/[lang]/dossiers/[companyId]">) {
  const { companyId } = await params;
  const [{ t, locale }, company, user] = await Promise.all([getDictionary(), getCompany(companyId), getCurrentUser()]);
  const canRead = can(company, "entries:read");
  const canWrite = can(company, "entries:write");
  const [fiscalYears, taxRates, members, dashboard, recent] = await Promise.all([
    can(company, "fiscal_years:read") ? getFiscalYears(companyId) : Promise.resolve(null),
    can(company, "taxes:read") ? getTaxRates(companyId) : Promise.resolve(null),
    can(company, "members:read") ? getMembers(companyId) : Promise.resolve(null),
    canRead ? getDashboard(companyId) : Promise.resolve(null),
    canRead ? getEntries(companyId, { limit: 5, offset: 0 }) : Promise.resolve(null),
  ]);
  const d = t.dashboard;
  const base = `/dossiers/${companyId}`;
  const currency = company.company.currency;
  const money = (value: string) => formatMoney(BigInt(value), currency, locale);
  const ratesToVerify = taxRates?.filter((r) => r.verified_at === null && r.valid_to === null).length ?? 0;

  const steps = [
    fiscalYears && { label: d.stepFiscalYear, done: fiscalYears.length > 0, href: `${base}/parametres/exercices` },
    taxRates && {
      label: ratesToVerify ? `${d.stepTaxes} — ${interpolate(d.stepTaxesPending, { count: ratesToVerify })}` : d.stepTaxes,
      done: ratesToVerify === 0,
      href: `${base}/parametres/taxes`,
    },
    members && {
      label: d.stepMembers,
      done: members.length > 1 || company.company.firm_id !== null,
      href: `${base}/parametres/utilisateurs`,
    },
    { label: d.stepMfa, done: user.mfa_enabled, href: "/compte/securite" },
  ].filter((step): step is { label: string; done: boolean; href: string } => Boolean(step));
  const setupPending = steps.some((s) => !s.done);
  const fy = dashboard?.fiscal_year ?? null;

  return (
    <>
      <PageHeader
        title={company.company.legal_name}
        subtitle={
          fy && dashboard
            ? interpolate(d.asOf, {
                date: formatDate(dashboard.as_of, locale),
                start: formatDate(fy.start_date, locale),
                end: formatDate(fy.end_date, locale),
              })
            : d.title
        }
      />

      <div className="flex flex-col gap-6">
        {canRead && !fy ? (
          <Alert role="status">
            <AlertDescription>
              {d.noFiscalYear}{" "}
              <Link href={`${base}/parametres/exercices`} className="underline underline-offset-4">
                {d.createFiscalYear}
              </Link>
            </AlertDescription>
          </Alert>
        ) : null}

        {canWrite ? (
          <section aria-labelledby="actions-rapides" className="flex flex-col gap-2">
            <h2 id="actions-rapides" className="font-medium">
              {d.quickTitle}
            </h2>
            <div className="flex flex-wrap gap-2">
              {QUICK.map((op) => (
                <Link
                  key={op}
                  href={`${base}/saisie-guidee?operation=${op}`}
                  className="border-input hover:bg-muted rounded-md border px-3 py-2 text-sm"
                >
                  {t.guided.operations[op].title}
                </Link>
              ))}
              <Link href={`${base}/ecritures/nouvelle`} className="text-muted-foreground hover:bg-muted rounded-md px-3 py-2 text-sm">
                {d.newEntry}
              </Link>
              <Link href={`${base}/hors-connexion`} className="text-muted-foreground hover:bg-muted rounded-md px-3 py-2 text-sm">
                {d.offline}
              </Link>
            </div>
          </section>
        ) : null}

        {dashboard && dashboard.drafts > 0 ? (
          <Alert role="status">
            <AlertDescription>
              {interpolate(d.drafts, { n: dashboard.drafts })}{" "}
              <Link href={`${base}/ecritures?statut=DRAFT`} className="underline underline-offset-4">
                {d.draftsLink}
              </Link>
            </AlertDescription>
          </Alert>
        ) : null}

        {dashboard && fy ? (
          <>
            <section aria-label={d.title} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Tile
                label={d.treasury}
                value={money(dashboard.treasury_total)}
                hint={d.treasuryHint}
                tone={BigInt(dashboard.treasury_total) < 0n ? "negative" : "default"}
              />
              <Tile
                label={`${d.revenue} — ${d.thisMonth}`}
                value={money(dashboard.month.revenue)}
                hint={interpolate(d.yearToDate, { amount: money(dashboard.year_to_date.revenue) })}
              />
              <Tile
                label={`${d.expenses} — ${d.thisMonth}`}
                value={money(dashboard.month.expenses)}
                hint={interpolate(d.yearToDate, { amount: money(dashboard.year_to_date.expenses) })}
              />
              <Tile
                label={d.result}
                value={money(dashboard.year_to_date.result)}
                hint={d.resultHint}
                tone={BigInt(dashboard.year_to_date.result) < 0n ? "negative" : "default"}
                href={`${base}/etats-financiers`}
              />
              <Tile label={d.receivables} value={money(dashboard.receivables)} href={`${base}/lettrage`} />
              <Tile label={d.payables} value={money(dashboard.payables)} href={`${base}/lettrage`} />
            </section>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{d.chartTitle}</CardTitle>
                </CardHeader>
                <CardContent>
                  <MonthlyChart
                    points={dashboard.monthly}
                    currency={currency}
                    locale={locale}
                    labels={{ revenue: d.revenue, expenses: d.expenses, month: d.month, table: d.chartTable, title: d.chartTitle }}
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{d.treasuryAccounts}</CardTitle>
                </CardHeader>
                <CardContent>
                  {dashboard.treasury.length === 0 ? (
                    <p className="text-muted-foreground text-sm">{d.noTreasury}</p>
                  ) : (
                    <ul className="flex flex-col gap-2 text-sm">
                      {dashboard.treasury.map((a) => (
                        <li key={a.account_id} className="flex items-baseline justify-between gap-3">
                          <span>
                            <span className="font-mono">{a.number}</span> {a.label}
                          </span>
                          <span className={cn("tabular-nums whitespace-nowrap", BigInt(a.balance) < 0n && "text-destructive")}>
                            {money(a.balance)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-2">
          {recent ? (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle className="text-base">{d.recentTitle}</CardTitle>
                <Link href={`${base}/ecritures`} className="text-sm underline underline-offset-4">
                  {d.allEntries}
                </Link>
              </CardHeader>
              <CardContent>
                {recent.items.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{d.recentEmpty}</p>
                ) : (
                  <ul className="flex flex-col gap-2 text-sm">
                    {recent.items.map((e) => (
                      <li key={e.id} className="flex items-baseline justify-between gap-3">
                        <Link href={`${base}/ecritures/${e.id}`} className="min-w-0 truncate underline-offset-4 hover:underline">
                          {formatDate(e.entry_date, locale)} · {e.journal_code}
                          {e.number ? ` n° ${e.number}` : ""} — {e.label}
                        </Link>
                        <span className="flex shrink-0 items-center gap-2">
                          {e.status === "DRAFT" ? <Badge variant="outline">{d.draft}</Badge> : null}
                          <span className="tabular-nums">{money(e.total_debit)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          ) : null}

          {setupPending ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{d.setupTitle}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col gap-3">
                  {steps.map((step) => (
                    <li key={step.href} className="flex items-start justify-between gap-3">
                      <Link href={step.href} className="text-sm underline-offset-4 hover:underline">
                        {step.label}
                      </Link>
                      <Badge variant={step.done ? "secondary" : "outline"}>{step.done ? d.done : d.todo}</Badge>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </div>

        {dashboard ? (
          <p className="text-muted-foreground text-xs">
            {d.postedOnly} {d.expertNotice}
          </p>
        ) : null}
      </div>
    </>
  );
}

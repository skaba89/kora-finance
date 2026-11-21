import type { Metadata } from "next";
import Link from "next/link";
import { ArrowDownLeft, ArrowUpRight, Banknote, ClipboardPlus, FilePlus2, ReceiptText, Wallet, WifiOff, ChartNoAxesCombined, CircleCheck, CircleDashed, type LucideIcon } from "lucide-react";

import { MonthlyChart } from "@/components/dashboard/monthly-chart";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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

const QUICK: { operation: Operation; icon: LucideIcon }[] = [
  { operation: "VENTE_COMPTANT", icon: ArrowDownLeft },
  { operation: "ACHAT_COMPTANT", icon: ArrowUpRight },
  { operation: "FACTURE_CLIENT", icon: FilePlus2 },
  { operation: "ENCAISSEMENT_CLIENT", icon: Banknote },
  { operation: "FACTURE_FOURNISSEUR", icon: ReceiptText },
  { operation: "PAIEMENT_FOURNISSEUR", icon: Wallet },
];

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.dashboard.title };
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
        actions={can(company, "sales:manage") ? (
          <Button asChild className="min-h-11 self-start">
            <Link href={`${base}/ventes?vue=nouveau`}>{t.sales.createInvoice}</Link>
          </Button>
        ) : undefined}
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
          <section aria-label={d.title} className="grid min-w-0 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <KpiCard
              primary
              icon={Wallet}
              href={can(company, "treasury:read") ? `${base}/tresorerie` : undefined}
              label={d.treasury}
              value={money(dashboard.treasury_total)}
              hint={d.treasuryHint}
              negative={BigInt(dashboard.treasury_total) < 0n}
            />
            <KpiCard
              icon={ArrowDownLeft}
              label={`${d.revenue} — ${d.thisMonth}`}
              value={money(dashboard.month.revenue)}
              hint={interpolate(d.yearToDate, { amount: money(dashboard.year_to_date.revenue) })}
            />
            <KpiCard
              icon={ArrowUpRight}
              label={`${d.expenses} — ${d.thisMonth}`}
              value={money(dashboard.month.expenses)}
              hint={interpolate(d.yearToDate, { amount: money(dashboard.year_to_date.expenses) })}
            />
            <KpiCard
              icon={ChartNoAxesCombined}
              label={d.result}
              value={money(dashboard.year_to_date.result)}
              hint={d.resultHint}
              negative={BigInt(dashboard.year_to_date.result) < 0n}
              href={`${base}/etats-financiers`}
            />
            <KpiCard icon={Banknote} label={d.receivables} value={money(dashboard.receivables)} href={`${base}/lettrage`} />
            <KpiCard icon={ReceiptText} label={d.payables} value={money(dashboard.payables)} href={`${base}/lettrage`} />
          </section>
        ) : null}

        {canWrite ? (
          <section aria-labelledby="actions-rapides" className="flex flex-col gap-3">
            <h2 id="actions-rapides" className="text-base font-semibold tracking-tight">
              {d.quickTitle}
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {QUICK.map(({ operation: op, icon: Icon }) => (
                  <Link
                    key={op}
                    href={`${base}/saisie-guidee?operation=${op}`}
                    className="border-border bg-card hover:bg-accent flex min-h-12 min-w-0 items-center gap-3 rounded-lg border px-3 py-2 text-sm font-medium"
                  >
                    <Icon aria-hidden className="text-primary size-4 shrink-0" />
                    {t.guided.operations[op].title}
                  </Link>
              ))}
              <Link href={`${base}/ecritures/nouvelle`} className="text-muted-foreground hover:bg-accent flex min-h-12 items-center gap-3 rounded-lg px-3 py-2 text-sm">
                <ClipboardPlus aria-hidden className="size-4 shrink-0" />
                {d.newEntry}
              </Link>
              <Link href={`${base}/hors-connexion`} className="text-muted-foreground hover:bg-accent flex min-h-12 items-center gap-3 rounded-lg px-3 py-2 text-sm">
                <WifiOff aria-hidden className="size-4 shrink-0" />
                {d.offline}
              </Link>
            </div>
          </section>
        ) : null}

        {dashboard && fy ? (
          <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
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
                      <li key={a.account_id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b pb-2 last:border-b-0 last:pb-0">
                        <span className="min-w-0 wrap-anywhere">
                          <span className="font-mono">{a.number}</span> {a.label}
                        </span>
                        <span className={cn("ml-auto min-w-0 wrap-anywhere text-right font-medium tabular-nums", BigInt(a.balance) < 0n && "text-destructive")}>
                          {money(a.balance)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}

        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
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
                      <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b pb-2 last:border-b-0 last:pb-0">
                        <Link href={`${base}/ecritures/${e.id}`} className="min-w-0 wrap-anywhere underline-offset-4 hover:underline">
                          {formatDate(e.entry_date, locale)} · {e.journal_code}
                          {e.number ? ` n° ${e.number}` : ""} — {e.label}
                        </Link>
                        <span className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2">
                          {e.status === "DRAFT" ? <Badge variant="outline">{d.draft}</Badge> : null}
                          <span className="wrap-anywhere text-right font-medium tabular-nums">{money(e.total_debit)}</span>
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
                    <li key={step.href} className="flex items-start justify-between gap-3 border-b pb-3 last:border-b-0 last:pb-0">
                      <Link href={step.href} className="flex min-w-0 items-start gap-2 text-sm underline-offset-4 hover:underline">
                        {step.done ? <CircleCheck aria-hidden className="text-success mt-0.5 size-4 shrink-0" /> : <CircleDashed aria-hidden className="text-muted-foreground mt-0.5 size-4 shrink-0" />}
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

import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { can, getCompany, getCurrentUser, getFiscalYears, getMembers, getTaxRates } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";
import { interpolate } from "@/lib/i18n/interpolate";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.dashboard.title };
}

export default async function DashboardPage({ params }: PageProps<"/[lang]/dossiers/[companyId]">) {
  const { companyId } = await params;
  const [{ t, locale }, company, user] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getCurrentUser(),
  ]);
  const [fiscalYears, taxRates, members] = await Promise.all([
    can(company, "fiscal_years:read") ? getFiscalYears(companyId) : Promise.resolve(null),
    can(company, "taxes:read") ? getTaxRates(companyId) : Promise.resolve(null),
    can(company, "members:read") ? getMembers(companyId) : Promise.resolve(null),
  ]);
  const openYear = fiscalYears?.find((fy) => fy.status === "OPEN");
  const ratesToVerify = taxRates?.filter((r) => r.verified_at === null && r.valid_to === null).length ?? 0;
  const base = `/dossiers/${companyId}`;

  const steps = [
    fiscalYears && {
      label: t.dashboard.stepFiscalYear,
      done: fiscalYears.length > 0,
      href: `${base}/parametres/exercices`,
    },
    taxRates && {
      label: ratesToVerify
        ? `${t.dashboard.stepTaxes} — ${interpolate(t.dashboard.stepTaxesPending, { count: ratesToVerify })}`
        : t.dashboard.stepTaxes,
      done: ratesToVerify === 0,
      href: `${base}/parametres/taxes`,
    },
    members && {
      label: t.dashboard.stepMembers,
      done: members.length > 1 || company.company.firm_id !== null,
      href: `${base}/parametres/utilisateurs`,
    },
    { label: t.dashboard.stepMfa, done: user.mfa_enabled, href: "/compte/securite" },
  ].filter((step): step is { label: string; done: boolean; href: string } => Boolean(step));

  return (
    <>
      <PageHeader title={company.company.legal_name} subtitle={t.dashboard.title} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t.dashboard.setupTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-3">
              {steps.map((step) => (
                <li key={step.href} className="flex items-start justify-between gap-3">
                  <Link href={step.href} className="text-sm underline-offset-4 hover:underline">
                    {step.label}
                  </Link>
                  <Badge variant={step.done ? "secondary" : "outline"}>
                    {step.done ? t.dashboard.done : t.dashboard.todo}
                  </Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t.dashboard.currentFiscalYear}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            {openYear
              ? `${formatDate(openYear.start_date, locale)} – ${formatDate(openYear.end_date, locale)}`
              : t.dashboard.none}
          </CardContent>
        </Card>
      </div>
      <p className="text-muted-foreground mt-6 text-sm">{t.dashboard.accountingComing}</p>
    </>
  );
}

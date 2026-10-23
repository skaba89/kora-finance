import type { Metadata } from "next";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { createFiscalYearAction } from "@/lib/actions/companies";
import { can, getCompany, getFiscalYears } from "@/lib/dal";
import { formatDate } from "@/lib/format";
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

  return (
    <>
      <PageHeader title={t.fiscalYears.title} subtitle={t.fiscalYears.subtitle} />
      {years.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t.fiscalYears.empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t.fiscalYears.start}</TableHead>
              <TableHead>{t.fiscalYears.end}</TableHead>
              <TableHead>{t.fiscalYears.status}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {years.map((year) => (
              <TableRow key={year.id}>
                <TableCell>{formatDate(year.start_date, locale)}</TableCell>
                <TableCell>{formatDate(year.end_date, locale)}</TableCell>
                <TableCell>
                  <Badge variant={year.status === "OPEN" ? "secondary" : "outline"}>
                    {year.status === "OPEN" ? t.fiscalYears.OPEN : t.fiscalYears.CLOSED}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <p className="text-muted-foreground mt-3 text-xs">{t.fiscalYears.closingNotice}</p>
      {can(company, "fiscal_years:manage") ? (
        <Card className="mt-6 max-w-xl">
          <CardHeader>
            <CardTitle className="text-base">{t.fiscalYears.add}</CardTitle>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={createFiscalYearAction.bind(null, companyId)}
              submitLabel={t.common.add}
              pendingLabel={t.common.pending}
              resetOnSuccess
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t.fiscalYears.start} name="start_date" type="date" required />
                <Field label={t.fiscalYears.end} name="end_date" type="date" required />
              </div>
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

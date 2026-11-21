import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { addTaxRateAction, verifyTaxRateAction } from "@/lib/actions/companies";
import { can, getCompany, getTaxRates } from "@/lib/dal";
import { formatDate, formatRate } from "@/lib/format";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.taxes.title };
}

export default async function TaxesPage({
  params,
}: PageProps<"/[lang]/dossiers/[companyId]/parametres/taxes">) {
  const { companyId } = await params;
  const [{ t, locale }, company, rates] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getTaxRates(companyId),
  ]);
  const manage = can(company, "taxes:manage");
  const unverified = rates.some((r) => r.verified_at === null);

  return (
    <>
      <PageHeader title={t.taxes.title} subtitle={t.taxes.subtitle} />
      {unverified ? (
        <Alert className="mb-4 border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
          <AlertDescription className="text-amber-950 dark:text-amber-100">{t.taxes.dgiNotice}</AlertDescription>
        </Alert>
      ) : null}
      <DataTable label={t.taxes.title}>
        <TableHeader>
          <TableRow>
            <TableHead>{t.taxes.code}</TableHead>
            <TableHead>{t.taxes.label}</TableHead>
            <TableHead className="text-right">{t.taxes.rate}</TableHead>
            <TableHead>{t.taxes.validFrom}</TableHead>
            <TableHead className="hidden md:table-cell">{t.taxes.collectedAccount}</TableHead>
            <TableHead className="hidden md:table-cell">{t.taxes.deductibleAccount}</TableHead>
            <TableHead>{t.common.status}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rates.map((rate) => (
            <TableRow key={rate.id}>
              <TableCell className="font-mono text-xs">{rate.code}</TableCell>
              <TableCell className="whitespace-normal">
                {rate.label}
                {rate.note ? <p className="text-muted-foreground text-xs">{rate.note}</p> : null}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatRate(rate.rate_basis_points, locale)}</TableCell>
              <TableCell className="whitespace-normal">
                {formatDate(rate.valid_from, locale)} {t.taxes.validTo}{" "}
                {rate.valid_to ? formatDate(rate.valid_to, locale) : t.taxes.ongoing}
              </TableCell>
              <TableCell className="hidden font-mono md:table-cell">{rate.collected_account_number ?? "—"}</TableCell>
              <TableCell className="hidden font-mono md:table-cell">{rate.deductible_account_number ?? "—"}</TableCell>
              <TableCell>
                {rate.verified_at ? (
                  <Badge variant="secondary">{t.taxes.verified}</Badge>
                ) : manage ? (
                  <InlineAction
                    action={verifyTaxRateAction.bind(null, companyId, rate.id)}
                    label={t.taxes.verify}
                    pendingLabel={t.common.pending}
                  />
                ) : (
                  <Badge variant="outline">{t.taxes.toVerify}</Badge>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>

      {manage ? (
        <Card className="mt-8 max-w-2xl">
          <CardHeader>
            <CardTitle className="text-base">{t.taxes.addTitle}</CardTitle>
            <p className="text-muted-foreground text-sm">{t.taxes.addHint}</p>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={addTaxRateAction.bind(null, companyId)}
              submitLabel={t.common.add}
              pendingLabel={t.common.pending}
              resetOnSuccess
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t.taxes.code} name="code" required pattern="[A-Za-z0-9_]{2,40}" placeholder="TVA_NORMAL" />
                <SelectField
                  label={t.taxes.kind}
                  name="kind"
                  options={[
                    { value: "TVA", label: "TVA" },
                    { value: "AUTRE", label: t.legalForms.AUTRE },
                  ]}
                />
              </div>
              <Field label={t.taxes.label} name="label" required maxLength={200} />
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={`${t.taxes.rate} (%)`} name="rate" inputMode="decimal" required hint={t.taxes.rateHint} />
                <Field label={t.taxes.validFrom} name="valid_from" type="date" required />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={`${t.taxes.collectedAccount} (${t.common.optional})`} name="collected_account_number" inputMode="numeric" />
                <Field label={`${t.taxes.deductibleAccount} (${t.common.optional})`} name="deductible_account_number" inputMode="numeric" />
              </div>
              <Field label={`${t.taxes.note} (${t.common.optional})`} name="note" maxLength={2000} />
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

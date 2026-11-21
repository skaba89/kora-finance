import type { Metadata } from "next";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { updateCompanyAction } from "@/lib/actions/companies";
import { can, getCompany } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.nav.company };
}

export default async function CompanySettingsPage({
  params,
}: PageProps<"/[lang]/dossiers/[companyId]/parametres/entreprise">) {
  const { companyId } = await params;
  const [{ t }, { company, ...access }] = await Promise.all([getDictionary(), getCompany(companyId)]);
  const editable = can({ company, ...access }, "company:update");

  const rows: [string, string | null][] = [
    [t.companies.legalName, company.legal_name],
    [t.companies.tradeName, company.trade_name],
    [t.companies.legalForm, t.legalForms[company.legal_form as keyof typeof t.legalForms] ?? company.legal_form],
    [t.companies.rccm, company.rccm],
    [t.companies.nif, company.nif],
    [t.companies.currency, company.currency],
    [t.companies.address, company.address],
    [t.companies.city, company.city],
    [t.companies.phone, company.phone],
  ];

  return (
    <>
      <PageHeader title={t.companies.identity} />
      <Card className="max-w-3xl">
        <CardHeader><CardTitle>{company.legal_name}</CardTitle></CardHeader>
        <CardContent>
      {editable ? (
        <ActionForm
          action={updateCompanyAction.bind(null, companyId)}
          submitLabel={t.common.save}
          pendingLabel={t.common.pending}
          className="min-w-0"
        >
          <Field label={t.companies.legalName} name="legal_name" defaultValue={company.legal_name} required maxLength={200} />
          <SelectField
            label={t.companies.legalForm}
            name="legal_form"
            defaultValue={company.legal_form}
            options={Object.entries(t.legalForms).map(([value, label]) => ({ value, label }))}
          />
          <Field label={t.companies.tradeName} name="trade_name" defaultValue={company.trade_name ?? ""} maxLength={200} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.companies.rccm} name="rccm" defaultValue={company.rccm ?? ""} maxLength={64} />
            <Field label={t.companies.nif} name="nif" defaultValue={company.nif ?? ""} maxLength={64} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.companies.city} name="city" defaultValue={company.city ?? ""} maxLength={120} />
            <Field label={t.companies.phone} name="phone" type="tel" defaultValue={company.phone ?? ""} maxLength={32} />
          </div>
          <Field label={t.companies.address} name="address" defaultValue={company.address ?? ""} maxLength={500} />
          <p className="text-muted-foreground text-xs">
            {t.companies.currency} : {company.currency}. {t.companies.currencyFixed}
          </p>
        </ActionForm>
      ) : (
        <dl className="divide-y text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="grid gap-1 py-3 sm:grid-cols-2 sm:gap-4">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="min-w-0 wrap-anywhere font-medium">{value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      )}
        </CardContent>
      </Card>
    </>
  );
}

import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { PageHeader, PageSkeleton } from "@/components/page-header";
import { createCompanyAction } from "@/lib/actions/companies";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.companies.createTitle };
}

async function CreateCompanyForm() {
  // Exercice proposé par défaut : l'année civile en cours (calculée à la requête).
  await connection();
  const { t } = await getDictionary();
  const year = new Date().getFullYear();
  return (
    <ActionForm
      action={createCompanyAction}
      submitLabel={t.common.create}
      pendingLabel={t.common.pending}
      className="max-w-xl"
    >
      <Field label={t.companies.legalName} name="legal_name" required maxLength={200} />
      <SelectField
        label={t.companies.legalForm}
        name="legal_form"
        defaultValue="SARL"
        options={Object.entries(t.legalForms).map(([value, label]) => ({ value, label }))}
      />
      <Field label={`${t.companies.tradeName} (${t.common.optional})`} name="trade_name" maxLength={200} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={`${t.companies.rccm} (${t.common.optional})`} name="rccm" maxLength={64} />
        <Field label={`${t.companies.nif} (${t.common.optional})`} name="nif" maxLength={64} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={`${t.companies.city} (${t.common.optional})`} name="city" maxLength={120} />
        <Field label={`${t.companies.phone} (${t.common.optional})`} name="phone" type="tel" maxLength={32} />
      </div>
      <Field label={`${t.companies.address} (${t.common.optional})`} name="address" maxLength={500} />
      <fieldset className="flex flex-col gap-3 rounded-md border p-4">
        <legend className="px-1 text-sm font-medium">{t.companies.firstFiscalYear}</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t.companies.fiscalYearStart} name="fiscal_year_start" type="date" defaultValue={`${year}-01-01`} />
          <Field label={t.companies.fiscalYearEnd} name="fiscal_year_end" type="date" defaultValue={`${year}-12-31`} />
        </div>
      </fieldset>
      <p className="text-muted-foreground text-xs">
        {t.companies.currency} : GNF. {t.companies.currencyFixed}
      </p>
    </ActionForm>
  );
}

export default async function NewCompanyPage() {
  const { t } = await getDictionary();
  return (
    <>
      <PageHeader title={t.companies.createTitle} subtitle={t.companies.createSubtitle} />
      <Suspense fallback={<PageSkeleton />}>
        <CreateCompanyForm />
      </Suspense>
    </>
  );
}

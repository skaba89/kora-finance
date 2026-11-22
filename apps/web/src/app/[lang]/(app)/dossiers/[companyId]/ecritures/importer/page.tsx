import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { ImportPrecheck } from "@/components/ledger/import-precheck";
import { precheckImportAction } from "@/lib/actions/imports";
import { can, getCompany } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export default async function ImportPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  const [{ t, locale }, company] = await Promise.all([getDictionary(), getCompany(companyId)]);
  if (!can(company, "entries:write") || company.company.currency !== "GNF") notFound();
  return <>
    <PageHeader title={t.imports.title} subtitle={t.imports.subtitle} actions={<Button asChild variant="outline"><Link href={`/dossiers/${companyId}/ecritures`}>{t.entries.title}</Link></Button>} />
    <ImportPrecheck action={precheckImportAction.bind(null, companyId)} labels={t.imports} locale={locale} />
  </>;
}

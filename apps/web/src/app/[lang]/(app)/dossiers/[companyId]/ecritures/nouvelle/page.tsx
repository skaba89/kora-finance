import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EntryEditor } from "@/components/ledger/entry-editor";
import { editorLabels } from "@/components/ledger/labels";
import { PageHeader } from "@/components/page-header";
import { saveEntryAction } from "@/lib/actions/ledger";
import { can, getActiveAccounts, getCompany, getJournals } from "@/lib/dal";
import { currencyDecimals } from "@/lib/format";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.entries.newTitle };
}

export default async function NewEntryPage({ params }: PageProps<"/[lang]/dossiers/[companyId]/ecritures/nouvelle">) {
  const { companyId } = await params;
  const [{ t, locale }, company, journals, accounts] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getJournals(companyId),
    getActiveAccounts(companyId),
  ]);
  if (!can(company, "entries:write")) notFound();
  const currency = company.company.currency;
  return (
    <>
      <PageHeader title={t.entries.newTitle} subtitle={t.entries.draftNotice} />
      <EntryEditor
        action={saveEntryAction.bind(null, companyId)}
        journals={journals.filter((j) => j.is_active).map(({ id, code, label }) => ({ id, code, label }))}
        accounts={accounts.map(({ id, number, label }) => ({ id, number, label }))}
        defaultDate={new Date().toISOString().slice(0, 10)}
        currency={currency}
        decimals={currencyDecimals(currency)}
        locale={locale}
        canPost={can(company, "entries:post")}
        labels={editorLabels(t)}
      />
    </>
  );
}

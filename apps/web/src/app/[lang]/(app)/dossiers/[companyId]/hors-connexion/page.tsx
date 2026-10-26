import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DevicePanel } from "@/components/offline/device-panel";
import { PageHeader } from "@/components/page-header";
import { can, getCompany, getCurrentUser } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.offline.pageTitle };
}

export default async function OfflineDevicePage({ params }: PageProps<"/[lang]/dossiers/[companyId]/hors-connexion">) {
  const { companyId } = await params;
  const [{ t, locale }, company, user] = await Promise.all([getDictionary(), getCompany(companyId), getCurrentUser()]);
  if (!can(company, "entries:write")) notFound();
  return (
    <>
      <PageHeader title={t.offline.pageTitle} subtitle={t.offline.pageSubtitle} />
      <DevicePanel
        companyId={companyId}
        userId={user.id}
        currency={company.company.currency}
        locale={locale}
        labels={t.offline}
      />
    </>
  );
}

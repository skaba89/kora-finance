import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { PageHeader, PageSkeleton } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getCompanies } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.companies.listTitle };
}

async function CompanyList() {
  const [{ t }, companies] = await Promise.all([getDictionary(), getCompanies()]);
  if (companies.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <p className="font-medium">{t.companies.empty}</p>
        <p className="text-muted-foreground mt-1 text-sm">{t.companies.emptyHint}</p>
        <Button asChild className="mt-4">
          <Link href="/dossiers/nouveau">{t.companies.newCompany}</Link>
        </Button>
      </div>
    );
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {companies.map(({ company, role }) => (
        <li key={company.id}>
          <Link href={`/dossiers/${company.id}`} className="block focus-visible:outline-none">
            <Card className="hover:border-teal-600 transition-colors">
              <CardHeader>
                <CardTitle className="text-base">{company.legal_name}</CardTitle>
                <CardDescription className="flex flex-wrap items-center gap-2">
                  <span>{t.legalForms[company.legal_form as keyof typeof t.legalForms] ?? company.legal_form}</span>
                  <Badge variant="secondary">{t.roles[role]}</Badge>
                </CardDescription>
              </CardHeader>
            </Card>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default async function CompaniesPage() {
  const { t } = await getDictionary();
  return (
    <>
      <PageHeader
        title={t.companies.listTitle}
        actions={
          <Button asChild>
            <Link href="/dossiers/nouveau">{t.companies.newCompany}</Link>
          </Button>
        }
      />
      <Suspense fallback={<PageSkeleton />}>
        <CompanyList />
      </Suspense>
    </>
  );
}

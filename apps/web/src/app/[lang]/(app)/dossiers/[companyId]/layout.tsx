import { Suspense } from "react";

import { CompanyNavigation } from "@/components/company-navigation";
import { CompanySwitcher } from "@/components/company-switcher";
import { companyNavigation } from "@/lib/company-navigation";
import { PageSkeleton } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { can, getCompany, getCompanies } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

type Params = LayoutProps<"/[lang]/dossiers/[companyId]">["params"];

async function CompanyNav({ params }: { params: Params }) {
  const { companyId } = await params;
  const [{ t }, company] = await Promise.all([getDictionary(), getCompany(companyId)]);
  const base = `/dossiers/${companyId}`;
  const groups = companyNavigation(base, t.nav, permission => can(company, permission));
  return (
    <nav aria-label={t.nav.mainMenu}>
      <div className="mb-2 flex items-center gap-2 px-1 md:mb-3 md:block md:px-3">
        <p className="truncate font-semibold leading-tight">{company.company.legal_name}</p>
        <Badge variant="secondary" className="md:mt-1">
          {t.roles[company.role]}
        </Badge>
      </div>
      <CompanyNavigation groups={groups} searchLabel={t.nav.searchModules} emptyLabel={t.nav.noModules} />
    </nav>
  );
}

async function CompanySwitcherSlot({ params }: { params: Params }) {
  const { companyId } = await params;
  const [{ t }, companies] = await Promise.all([getDictionary(), getCompanies()]);
  if (!companies.some(({ company }) => company.id === companyId)) return null;
  return <CompanySwitcher key={companyId} currentId={companyId} label={t.nav.switchCompany}
    openLabel={t.nav.openSelectedCompany} pendingLabel={t.common.pending}
    companies={companies.map(({ company, role }) => ({ id: company.id, name: company.legal_name, role: t.roles[role] }))} />;
}

export default function CompanyLayout({ children, params }: LayoutProps<"/[lang]/dossiers/[companyId]">) {
  return (
    <div className="flex flex-1 flex-col gap-6 md:flex-row">
      <aside className="min-w-0 md:w-60 md:shrink-0 md:self-start md:rounded-xl md:border md:bg-sidebar md:p-3">
        <Suspense fallback={<div className="bg-muted h-64 animate-pulse rounded" />}>
          <CompanyNav params={params} />
        </Suspense>
      </aside>
      <section className="min-w-0 flex-1">
        <div className="mb-4 min-w-0">
          <Suspense fallback={<div className="bg-muted h-11 w-full max-w-96 animate-pulse rounded-lg" />}>
            <CompanySwitcherSlot params={params} />
          </Suspense>
        </div>
        <Suspense fallback={<PageSkeleton />}>{children}</Suspense>
      </section>
    </div>
  );
}

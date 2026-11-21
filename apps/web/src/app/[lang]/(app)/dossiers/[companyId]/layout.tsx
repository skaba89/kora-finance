import { Suspense } from "react";

import { CompanyNavigation } from "@/components/company-navigation";
import { companyNavigation } from "@/lib/company-navigation";
import { PageSkeleton } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { can, getCompany } from "@/lib/dal";
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

export default function CompanyLayout({ children, params }: LayoutProps<"/[lang]/dossiers/[companyId]">) {
  return (
    <div className="flex flex-1 flex-col gap-6 md:flex-row">
      <aside className="min-w-0 md:w-60 md:shrink-0 md:self-start md:rounded-xl md:border md:bg-sidebar md:p-3">
        <Suspense fallback={<div className="bg-muted h-64 animate-pulse rounded" />}>
          <CompanyNav params={params} />
        </Suspense>
      </aside>
      <section className="min-w-0 flex-1">
        <Suspense fallback={<PageSkeleton />}>{children}</Suspense>
      </section>
    </div>
  );
}

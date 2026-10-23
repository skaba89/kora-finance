import { Suspense } from "react";

import { NavLink } from "@/components/nav-link";
import { PageSkeleton } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { can, getCompany } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

type Params = LayoutProps<"/[lang]/dossiers/[companyId]">["params"];

async function CompanyNav({ params }: { params: Params }) {
  const { companyId } = await params;
  const [{ t }, company] = await Promise.all([getDictionary(), getCompany(companyId)]);
  const base = `/dossiers/${companyId}`;
  const settings = [
    { href: `${base}/parametres/entreprise`, label: t.nav.company, permission: "company:read" },
    { href: `${base}/parametres/exercices`, label: t.nav.fiscalYears, permission: "fiscal_years:read" },
    { href: `${base}/parametres/plan-comptable`, label: t.nav.chart, permission: "accounts:read" },
    { href: `${base}/parametres/taxes`, label: t.nav.taxes, permission: "taxes:read" },
    { href: `${base}/parametres/utilisateurs`, label: t.nav.members, permission: "members:read" },
  ].filter((item) => can(company, item.permission));
  return (
    <nav aria-label={t.nav.mainMenu} className="flex flex-col gap-1">
      <div className="mb-3 px-3">
        <p className="font-semibold leading-tight">{company.company.legal_name}</p>
        <Badge variant="secondary" className="mt-1">
          {t.roles[company.role]}
        </Badge>
      </div>
      <NavLink href={base} exact>
        {t.nav.dashboard}
      </NavLink>
      <p className="text-muted-foreground mt-3 px-3 text-xs font-medium uppercase">{t.nav.settings}</p>
      {settings.map((item) => (
        <NavLink key={item.href} href={item.href}>
          {item.label}
        </NavLink>
      ))}
      {can(company, "audit:read") ? (
        <NavLink href={`${base}/journal-audit`}>{t.nav.audit}</NavLink>
      ) : null}
      <NavLink href="/dossiers" exact>
        {t.nav.switchCompany}
      </NavLink>
    </nav>
  );
}

export default function CompanyLayout({ children, params }: LayoutProps<"/[lang]/dossiers/[companyId]">) {
  return (
    <div className="flex flex-1 flex-col gap-6 md:flex-row">
      <aside className="md:w-56 md:shrink-0">
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

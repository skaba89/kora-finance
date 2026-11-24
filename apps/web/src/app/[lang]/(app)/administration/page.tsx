import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { PageHeader, PageSkeleton } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, read } from "@/lib/api/server";
import { getCurrentUser } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

async function PlatformDashboard() {
  const [user, { locale }] = await Promise.all([getCurrentUser(), getDictionary()]);
  if (!user.is_platform_admin) notFound();
  const label = (fr: string, en: string) => locale === "en" ? en : fr;
  const client = await api();
  const page = await read(client.GET("/api/v1/platform/module-clients", {
    params: { query: { limit: 1, offset: 0 } },
  }));
  return (
    <main id="main-content" tabIndex={-1}>
      <PageHeader title={label("Administration Kora Finance", "Kora Finance administration")}
        subtitle={label("Pilotez les dossiers et leurs fonctionnalités.", "Manage companies and their features.")} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>{label("Dossiers clients", "Client companies")}</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <p className="text-3xl font-semibold tabular-nums">{page.total.toLocaleString(locale)}</p>
            <p className="text-muted-foreground text-sm">{label("Total des dossiers enregistrés sur la plateforme.", "Total companies registered on the platform.")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>{label("Modules", "Modules")}</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-muted-foreground text-sm">{label("Consultez et configurez les capacités disponibles par dossier.", "View and configure available capabilities for each company.")}</p>
            <Link href="/administration/modules" className="text-primary font-medium underline underline-offset-4">
              {label("Gérer les modules", "Manage modules")}
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>{label("Licences commerciales", "Commercial licenses")}</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-muted-foreground text-sm">{label("Consultez les licences et leur état sans modifier les abonnements.", "View licenses and their status without changing subscriptions.")}</p>
            <Link href="/administration/licences" className="text-primary font-medium underline underline-offset-4">
              {label("Consulter les licences", "View licenses")}
            </Link>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}

export default function AdministrationPage() {
  return <Suspense fallback={<PageSkeleton />}><PlatformDashboard /></Suspense>;
}

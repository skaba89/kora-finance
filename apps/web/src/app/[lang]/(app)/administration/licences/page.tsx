import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { PageHeader, PageSkeleton } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, read } from "@/lib/api/server";
import { getCurrentUser } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

type Query = PageProps<"/[lang]/administration/licences">["searchParams"];

const statuses: Record<string, [string, string]> = {
  scheduled: ["Programmée", "Scheduled"],
  trial: ["Essai", "Trial"],
  active: ["Active", "Active"],
  suspended: ["Suspendue", "Suspended"],
  expired: ["Expirée", "Expired"],
};

async function LicenseList({ searchParams }: { searchParams: Query }) {
  const [user, { locale }, query] = await Promise.all([
    getCurrentUser(), getDictionary(), searchParams,
  ]);
  if (!user.is_platform_admin) notFound();

  const en = locale === "en";
  const label = (fr: string, english: string) => en ? english : fr;
  const offset = typeof query.offset === "string" && /^\d{1,8}$/.test(query.offset)
    ? Number(query.offset) : 0;
  const client = await api();
  const companies = await read(client.GET("/api/v1/platform/module-clients", {
    params: { query: { limit: 50, offset } },
  }));
  // Only accept a company present in the authorized server-side page.
  const selected = typeof query.client === "string"
    ? companies.items.find((item) => item.id === query.client)
    : undefined;
  const today = new Date().toISOString().slice(0, 10);
  const requestedDate = typeof query.as_of === "string" ? query.as_of : undefined;
  // Reject invalid calendar dates rather than silently requesting another period.
  const validDate = requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate)
    && !Number.isNaN(Date.parse(`${requestedDate}T00:00:00.000Z`))
    && new Date(`${requestedDate}T00:00:00.000Z`).toISOString().slice(0, 10) === requestedDate;
  const asOf = validDate ? requestedDate : today;
  const licenses = selected
    ? await read(client.GET("/api/v1/platform/module-clients/{client_id}/licenses", {
        params: { path: { client_id: selected.id }, query: { as_of: asOf } },
      }))
    : [];

  return (
    <main id="main-content" tabIndex={-1}>
      <PageHeader
        title={label("Licences commerciales", "Commercial licenses")}
        subtitle={label(
          "Consultation sécurisée et en lecture seule des périodes de licence.",
          "Secure, read-only view of license periods.",
        )}
      />
      <Link href="/administration" className="text-primary mb-4 inline-block text-sm font-medium underline underline-offset-4">
        {label("Retour à l’administration", "Back to administration")}
      </Link>
      <div className="grid gap-4 lg:grid-cols-[minmax(220px,1fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader>
            <CardTitle>{label("Dossiers clients", "Client companies")} ({companies.total})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {companies.items.length === 0
              ? <p>{label("Aucun dossier sur cette page.", "No companies on this page.")}</p>
              : null}
            {companies.items.map((item) => (
              <Link
                key={item.id}
                href={`/administration/licences?offset=${offset}&client=${item.id}&as_of=${asOf}`}
                aria-current={selected?.id === item.id ? "page" : undefined}
                className={`block break-words rounded-lg border px-3 py-2 text-sm hover:bg-accent ${selected?.id === item.id ? "border-primary font-semibold" : ""}`}
              >
                {item.legal_name}
              </Link>
            ))}
            <nav aria-label={label("Pagination des dossiers", "Company pagination")} className="flex flex-wrap gap-3 text-sm">
              {offset > 0
                ? <Link href={`/administration/licences?offset=${Math.max(0, offset - 50)}&as_of=${asOf}`}>{label("Précédent", "Previous")}</Link>
                : null}
              {offset + 50 < companies.total
                ? <Link href={`/administration/licences?offset=${offset + 50}&as_of=${asOf}`}>{label("Suivant", "Next")}</Link>
                : null}
            </nav>
          </CardContent>
        </Card>
        <section className="min-w-0 space-y-3">
          {!selected ? (
            <p className="text-muted-foreground">
              {label("Sélectionnez un dossier pour consulter ses licences.", "Select a company to view its licenses.")}
            </p>
          ) : (
            <>
              <h2 className="text-lg font-semibold">{selected.legal_name}</h2>
              <form method="get" action="/administration/licences" className="flex flex-wrap items-end gap-3">
                <input type="hidden" name="client" value={selected.id} />
                <input type="hidden" name="offset" value={offset} />
                <label htmlFor="licenses-as-of" className="flex flex-col gap-1 text-sm font-medium">
                  {label("Date de consultation (UTC)", "As-of date (UTC)")}
                  <input id="licenses-as-of" type="date" name="as_of" required
                    defaultValue={asOf} className="border-input bg-background rounded-md border px-3 py-2" />
                </label>
                <button type="submit" className="bg-primary text-primary-foreground rounded-md px-4 py-2 text-sm font-medium">
                  {label("Consulter", "View")}
                </button>
              </form>
              {requestedDate && !validDate
                ? <p role="alert" className="text-destructive text-sm">
                    {label("Date invalide : affichage à la date UTC du jour.", "Invalid date: displaying today’s UTC status.")}
                  </p> : null}
              <p className="text-muted-foreground text-sm">
                {label("États calculés au", "Statuses calculated as of")} <time dateTime={asOf}>{asOf}</time> (UTC)
              </p>
              {licenses.length === 0
                ? <p>{label("Aucune période de licence enregistrée.", "No license periods recorded.")}</p>
                : null}
              <div className="grid gap-3 xl:grid-cols-2">
                {licenses.map((license) => (
                  <Card key={license.id}>
                    <CardHeader className="space-y-2">
                      <CardTitle className="break-words text-base">
                        {license.offer_code} — v{license.offer_version}
                      </CardTitle>
                      <div>
                        <Badge variant={license.status === "active" ? "default" : "secondary"}>
                          {statuses[license.status]?.[en ? 1 : 0] ?? license.status}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <p>{label("Type", "Kind")} : {license.kind}</p>
                      <p>{label("Début", "Start")} : <time dateTime={license.starts_on}>{license.starts_on}</time></p>
                      <p>{label("Fin", "End")} : <time dateTime={license.ends_on}>{license.ends_on}</time></p>
                      {license.suspended
                        ? <p>{label("Suspension enregistrée", "Suspension recorded")}</p>
                        : null}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

export default function LicensesPage({ searchParams }: PageProps<"/[lang]/administration/licences">) {
  return <Suspense fallback={<PageSkeleton />}><LicenseList searchParams={searchParams} /></Suspense>;
}

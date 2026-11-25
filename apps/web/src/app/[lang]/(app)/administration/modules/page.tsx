import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { InlineAction } from "@/components/forms/inline-action";
import { PlatformMfaNotice } from "@/components/admin/platform-mfa-notice";
import { PageHeader, PageSkeleton } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, read, readOrForbidden } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { updateModuleAction } from "@/lib/actions/modules";
import { getCurrentUser } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

type Module = components["schemas"]["Module"];
const names: Record<Module, [string, string]> = {
  sales: ["Ventes et facturation", "Sales and invoicing"],
  purchases: ["Achats", "Purchases"],
  accounting: ["Comptabilité", "Accounting"],
  treasury: ["Trésorerie", "Treasury"],
  imports: ["Imports comptables", "Accounting imports"],
  forecast: ["Prévisions de trésorerie", "Cash forecasts"],
  offline: ["Mode hors connexion", "Offline mode"],
  expenses: ["Notes de frais", "Expenses"],
  documents: ["Documents", "Documents"],
  ocr: ["Reconnaissance de documents", "Document recognition"],
  assets: ["Immobilisations", "Fixed assets"],
  analytics: ["Comptabilité analytique", "Analytics"],
  budgets: ["Budgets", "Budgets"],
  tax_reporting: ["Déclarations fiscales", "Tax reporting"],
  firm: ["Cabinet comptable", "Accounting firm"],
  funding: ["Financement", "Funding"],
  ai: ["Intelligence artificielle", "Artificial intelligence"],
  makitiplus: ["MakitiPlus", "MakitiPlus"],
  payments: ["Paiements", "Payments"],
};

async function ModuleSettings({ searchParams }: { searchParams: PageProps<"/[lang]/administration/modules">["searchParams"] }) {
  const [user, { t, locale }, query] = await Promise.all([getCurrentUser(), getDictionary(), searchParams]);
  if (!user.is_platform_admin) notFound();
  const en = locale === "en";
  const label = (fr: string, english: string) => en ? english : fr;
  const name = (module: Module) => names[module][en ? 1 : 0];
  const offset = typeof query.offset === "string" && /^\d{1,8}$/.test(query.offset) ? Number(query.offset) : 0;
  const client = await api();
  const page = await readOrForbidden(client.GET("/api/v1/platform/module-clients", { params: { query: { limit: 50, offset } } }));
  if (page === null) {
    return (
      <main id="main-content" tabIndex={-1}>
        <PageHeader title={label("Administration des modules", "Module administration")} />
        <PlatformMfaNotice refused locale={locale} />
      </main>
    );
  }
  const selected = typeof query.client === "string" ? page.items.find((item) => item.id === query.client) : undefined;
  const modules = selected ? await read(client.GET("/api/v1/platform/module-clients/{client_id}/modules", {
    params: { path: { client_id: selected.id } },
  })) : [];
  const statusLabels = {
    enabled: label("Actif", "Enabled"),
    disabled: label("Inactif", "Disabled"),
    unreleased: label("À venir", "Coming soon"),
    dependency_disabled: label("Prérequis inactif", "Dependency disabled"),
  };
  return (
    <main id="main-content" tabIndex={-1}>
      <PageHeader title={label("Administration des modules", "Module administration")}
        subtitle={label("Configurez les fonctionnalités disponibles pour chaque dossier client.", "Configure available features for each client company.")} />
      <Link href="/administration" className="text-primary mb-4 inline-block text-sm font-medium underline underline-offset-4">{label("Retour à l’administration", "Back to administration")}</Link>
      <div className="grid gap-4 lg:grid-cols-[minmax(220px,1fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader><CardTitle>{label("Clients", "Clients")} ({page.total})</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {page.items.length === 0 ? <p>{label("Aucun dossier sur cette page.", "No companies on this page.")}</p> : null}
            {page.items.map((item) => (
              <Link key={item.id} href={`/administration/modules?offset=${offset}&client=${item.id}`}
                aria-current={selected?.id === item.id ? "page" : undefined}
                className={`block break-words rounded-lg border px-3 py-2 text-sm hover:bg-accent ${selected?.id === item.id ? "border-primary font-semibold" : ""}`}>
                {item.legal_name}
              </Link>
            ))}
            <div className="flex flex-wrap gap-3 text-sm">
              {offset > 0 ? <Link href={`/administration/modules?offset=${Math.max(0, offset - 50)}`}>{label("Précédent", "Previous")}</Link> : null}
              {offset + 50 < page.total ? <Link href={`/administration/modules?offset=${offset + 50}`}>{label("Suivant", "Next")}</Link> : null}
            </div>
          </CardContent>
        </Card>
        <section className="min-w-0 space-y-3">
          {!selected ? <p className="text-muted-foreground">{label("Sélectionnez un client pour gérer ses modules.", "Select a client to manage modules.")}</p> : (
            <>
              <h2 className="text-lg font-semibold">{selected.legal_name}</h2>
              <div className="grid gap-3 xl:grid-cols-2">
                {modules.map((row) => {
                  const enabled = row.configured_enabled ?? row.default_enabled;
                  return (
                    <Card key={row.module}>
                      <CardHeader className="space-y-2">
                        <CardTitle className="text-base">{name(row.module)}</CardTitle>
                        <div><Badge variant={row.configured_status === "enabled" ? "default" : "secondary"}>{statusLabels[row.configured_status]}</Badge></div>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {row.dependencies.length > 0 ? <p className="text-muted-foreground text-sm">{label("Prérequis :", "Requires:")} {row.dependencies.map(name).join(", ")}</p> : null}
                        {row.released ? (
                          <InlineAction key={row.revision}
                            action={updateModuleAction.bind(null, selected.id, row.module, !enabled, row.revision)}
                            label={enabled ? label("Désactiver", "Disable") : label("Activer", "Enable")}
                            pendingLabel={t.common.pending}
                            variant={enabled ? "destructive" : "outline"}
                            confirm={enabled ? label("Désactiver ce module pour ce client ?", "Disable this module for this client?") : undefined}
                            showSuccess />
                        ) : <p className="text-muted-foreground text-sm">{label("Non disponible actuellement.", "Not currently available.")}</p>}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

export default function ModulesPage({ searchParams }: PageProps<"/[lang]/administration/modules">) {
  return <Suspense fallback={<PageSkeleton />}><ModuleSettings searchParams={searchParams} /></Suspense>;
}

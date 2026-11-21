import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { tablePreferences, tableRange } from "@/lib/table-preferences";
import { interpolate } from "@/lib/i18n/interpolate";

import { PageHeader } from "@/components/page-header";
import {
  PurchasesAgingCard,
  PurchasesCreateDocumentCard,
} from "@/components/purchases/purchases-cards";
import { PurchasesDocumentsTable } from "@/components/purchases/purchases-documents-table";
import { PurchasesFilters } from "@/components/purchases/purchases-filters";
import {
  PurchasesAdvanceFormCard,
  PurchasesPaymentFormCard,
} from "@/components/purchases/purchases-payment-forms";
import { PurchasesPaymentsTable } from "@/components/purchases/purchases-payments-table";
import { activeRateOptions, PURCHASE_STATUSES } from "@/components/purchases/labels";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  can,
  getCompany,
  getPartners,
  getPayablesAging,
  getPurchaseDocuments,
  getPurchasePayments,
  getTaxRates,
} from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.purchases.title };
}

/** Page achats (4F) : factures et avoirs fournisseurs à numérotation interne
 * sans trou (FACH/AVF), décaissements lettrés et échéancier fournisseurs.
 * Enregistrer un document n'écrit rien en comptabilité ; la comptabilisation
 * est un acte explicite du comptable : elle crée l'écriture validée du journal
 * des achats et la lie au document ou au décaissement.
 *
 * La composition est déléguée aux composants de `@/components/purchases/` :
 * cette page charge les données, résout les permissions et assemble. */
export default async function PurchasesPage({
  params,
  searchParams,
}: {
  params: Promise<{ lang: string; companyId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ companyId }, query] = await Promise.all([params, searchParams]);
  const { kind, statut } = query;
  const { size, page, offset, density } = tablePreferences(query);
  const kindParam =
    kind === "supplier_invoice" || kind === "supplier_credit_note" ? kind : undefined;
  const statusParam = PURCHASE_STATUSES.find((value) => value === statut);
  const [{ t }, company, documents, partners, taxRates, payments, aging] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getPurchaseDocuments(companyId, {
      kind: kindParam,
      status: statusParam,
      limit: size,
      offset,
    }),
    getPartners(companyId, { limit: 200, offset: 0 }),
    getTaxRates(companyId),
    getPurchasePayments(companyId, { limit: 50, offset: 0 }),
    getPayablesAging(companyId),
  ]);

  const manage = can(company, "purchases:manage");
  // La comptabilisation est un acte comptable : permission entries:post.
  const canPost = can(company, "entries:post");
  const rateOptions = activeRateOptions(taxRates);
  const base = `/dossiers/${companyId}/achats`;
  const range = tableRange(documents.total, offset, documents.items.length, size);
  const pageHref = (target: number) => `${base}?${new URLSearchParams({ ...(kindParam ? { kind: kindParam } : {}), ...(statusParam ? { statut: statusParam } : {}), taille: String(size), densite: density, page: String(target) })}#documents-achats`;

  return (
    <>
      <PageHeader title={t.purchases.title} subtitle={t.purchases.subtitle} actions={manage ? <Button asChild className="min-h-11"><a href="#nouvel-achat">{t.purchases.createTitle}</a></Button> : undefined} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.purchases.noPostingNotice}</p>
      <nav aria-label={t.purchases.title} className="mb-5 flex flex-wrap gap-2 rounded-xl border bg-card p-2">
        {[{ id: "documents-achats", label: t.purchases.listTitle }, { id: "decaissements", label: t.purchases.paymentsTitle }, { id: "echeancier", label: t.purchases.agingTitle }].map(({ id, label }) => <a key={id} href={`#${id}`} className="hover:bg-accent text-primary inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium">{label}</a>)}
      </nav>

      <PurchasesFilters t={t} kindParam={kindParam} statusParam={statusParam} size={size} density={density} resetHref={base} />

      <Card id="documents-achats" className="scroll-mt-4">
        <CardHeader>
          <CardTitle>{t.purchases.listTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {documents.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{kindParam || statusParam || page > 1 || !manage ? t.purchases.noMatchingDocuments : t.purchases.empty}</p>
          ) : (
            <PurchasesDocumentsTable
              companyId={companyId}
              documents={documents}
              t={t}
              manage={manage}
              canPost={canPost}
              density={density}
              partnerNames={new Map(partners.items.map(p => [p.id, p.name]))}
            />
          )}
          <nav aria-label={t.table.pagination} className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-muted-foreground">{interpolate(t.common.pageRange, { from: range.from, to: range.to, total: documents.total })}</span>
            <div className="flex gap-2">
              {page > 1 && <Button asChild variant="outline"><Link href={pageHref(Math.min(page - 1, range.lastPage))}>{t.common.previous}</Link></Button>}
              {page < range.lastPage && <Button asChild variant="outline"><Link href={pageHref(page + 1)}>{t.common.next}</Link></Button>}
            </div>
          </nav>
        </CardContent>
      </Card>

      {manage && (
        <>
          <PurchasesPaymentFormCard companyId={companyId} documents={documents} t={t} />
          <PurchasesAdvanceFormCard companyId={companyId} partners={partners} t={t} />
        </>
      )}

      <Card id="decaissements" className="mt-6 scroll-mt-4">
        <CardHeader>
          <CardTitle>{t.purchases.paymentsTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {payments.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.purchases.paymentsEmpty}</p>
          ) : (
            <PurchasesPaymentsTable
              companyId={companyId}
              payments={payments}
              documents={documents}
              t={t}
              manage={manage}
              canPost={canPost}
            />
          )}
        </CardContent>
      </Card>

      <PurchasesAgingCard aging={aging} currency={company.company.currency} t={t} />

      {manage && (
        <PurchasesCreateDocumentCard
          companyId={companyId}
          partners={partners}
          rateOptions={rateOptions}
          t={t}
        />
      )}
    </>
  );
}

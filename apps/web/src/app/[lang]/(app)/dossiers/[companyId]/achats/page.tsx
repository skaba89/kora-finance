import type { Metadata } from "next";

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
  searchParams: Promise<{ kind?: string; statut?: string }>;
}) {
  const [{ companyId }, { kind, statut }] = await Promise.all([params, searchParams]);
  const kindParam =
    kind === "supplier_invoice" || kind === "supplier_credit_note" ? kind : undefined;
  const statusParam = PURCHASE_STATUSES.find((value) => value === statut);
  const [{ t }, company, documents, partners, taxRates, payments, aging] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getPurchaseDocuments(companyId, {
      kind: kindParam,
      status: statusParam,
      limit: 50,
      offset: 0,
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

  return (
    <>
      <PageHeader title={t.purchases.title} subtitle={t.purchases.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.purchases.noPostingNotice}</p>

      <PurchasesFilters t={t} kindParam={kindParam} statusParam={statusParam} />

      <Card>
        <CardHeader>
          <CardTitle>{t.purchases.listTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {documents.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.purchases.empty}</p>
          ) : (
            <PurchasesDocumentsTable
              companyId={companyId}
              documents={documents}
              t={t}
              manage={manage}
              canPost={canPost}
            />
          )}
        </CardContent>
      </Card>

      {manage && (
        <>
          <PurchasesPaymentFormCard companyId={companyId} documents={documents} t={t} />
          <PurchasesAdvanceFormCard companyId={companyId} partners={partners} t={t} />
        </>
      )}

      <Card className="mt-6">
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

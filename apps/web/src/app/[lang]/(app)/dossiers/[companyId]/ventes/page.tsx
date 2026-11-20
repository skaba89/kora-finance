import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { activeRateOptions, SALES_KINDS, SALES_STATUSES } from "@/components/sales/labels";
import { SalesAgingCard } from "@/components/sales/sales-aging-card";
import { SalesKpisCard } from "@/components/sales/sales-kpis-card";
import { SalesScheduleCard } from "@/components/sales/sales-schedule-card";
import {
  SalesCreateDocumentCard,
  SalesEmailFormCard,
} from "@/components/sales/sales-document-forms";
import { SalesDocumentsTable } from "@/components/sales/sales-documents-table";
import { SalesFilters } from "@/components/sales/sales-filters";
import {
  SalesDepositFormCard,
  SalesPaymentFormCard,
} from "@/components/sales/sales-payment-forms";
import { SalesPaymentsTable } from "@/components/sales/sales-payments-table";
import {
  SalesOverdueCard,
  SalesReminderPolicyCard,
  SalesRemindersHistoryCard,
} from "@/components/sales/sales-reminders";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  can,
  getCompany,
  getPartners,
  getSalesAging,
  getSalesDocuments,
  getSalesKpis,
  getSalesOverdue,
  getSalesPayments,
  getSalesReminderPolicy,
  getSalesReminders,
  getSalesSchedules,
  getTaxRates,
} from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.sales.title };
}

/** Page ventes (4B) : devis, factures et avoirs à numérotation sans trou. Créer un
 * brouillon n'écrit rien en comptabilité ; le numéro est attribué à l'émission
 * (facture/avoir) ou à l'envoi (devis) et n'est jamais réutilisé. La
 * comptabilisation (4E) est un acte explicite du comptable : elle crée l'écriture
 * validée et la lie au document ou au règlement.
 *
 * Le recouvrement (lot B-4) complète la page : échéanciers clients (tranches
 * prévues), indicateurs de recouvrement et DSO, export de la balance âgée.
 *
 * La composition est déléguée aux composants de `@/components/sales/` : cette
 * page charge les données, résout les permissions et assemble. */
export default async function SalesPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/ventes">) {
  const { companyId } = await params;
  const { kind, statut } = await searchParams;
  const kindParam =
    typeof kind === "string" && SALES_KINDS.includes(kind as (typeof SALES_KINDS)[number])
      ? (kind as (typeof SALES_KINDS)[number])
      : undefined;
  const statusParam =
    typeof statut === "string" && SALES_STATUSES.includes(statut as (typeof SALES_STATUSES)[number])
      ? (statut as (typeof SALES_STATUSES)[number])
      : undefined;
  const [
    { t },
    company,
    documents,
    partners,
    taxRates,
    payments,
    aging,
    kpis,
    schedules,
    overdue,
    reminders,
    policy,
  ] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getSalesDocuments(companyId, { kind: kindParam, status: statusParam, limit: 100, offset: 0 }),
    getPartners(companyId, { active: true, limit: 200, offset: 0 }),
    getTaxRates(companyId),
    getSalesPayments(companyId, { limit: 50, offset: 0 }),
    getSalesAging(companyId),
    getSalesKpis(companyId),
    getSalesSchedules(companyId),
    getSalesOverdue(companyId),
    getSalesReminders(companyId, { limit: 50, offset: 0 }),
    getSalesReminderPolicy(companyId),
  ]);
  const manage = can(company, "sales:manage");
  // La comptabilisation (4E) est un acte comptable : permission entries:post.
  const canPost = can(company, "entries:post");
  const rateOptions = activeRateOptions(taxRates);

  return (
    <>
      <PageHeader title={t.sales.title} subtitle={t.sales.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.sales.noPostingNotice}</p>

      <SalesFilters t={t} kindParam={kindParam} statusParam={statusParam} />

      <Card>
        <CardHeader>
          <CardTitle>{t.sales.listTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {documents.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.sales.empty}</p>
          ) : (
            <SalesDocumentsTable
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
          <SalesPaymentFormCard companyId={companyId} documents={documents} t={t} />
          <SalesDepositFormCard companyId={companyId} partners={partners} t={t} />
        </>
      )}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t.sales.paymentsTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {payments.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t.sales.paymentsEmpty}</p>
          ) : (
            <SalesPaymentsTable
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

      <SalesAgingCard
        companyId={companyId}
        aging={aging}
        currency={company.company.currency}
        t={t}
      />

      <SalesKpisCard kpis={kpis} currency={company.company.currency} t={t} />

      <SalesScheduleCard
        companyId={companyId}
        documents={documents}
        schedules={schedules}
        t={t}
        manage={manage}
      />

      <SalesOverdueCard companyId={companyId} overdue={overdue} t={t} manage={manage} />

      <SalesRemindersHistoryCard
        companyId={companyId}
        reminders={reminders}
        documents={documents}
        t={t}
        manage={manage}
      />

      <SalesReminderPolicyCard companyId={companyId} policy={policy} t={t} manage={manage} />

      {manage && <SalesEmailFormCard companyId={companyId} documents={documents} t={t} />}

      {manage && (
        <SalesCreateDocumentCard
          companyId={companyId}
          partners={partners}
          rateOptions={rateOptions}
          t={t}
        />
      )}
    </>
  );
}

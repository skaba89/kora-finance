import type { Metadata } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { Dictionary } from "@/components/sales/types";

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

type ViewProps = { companyId: string; t: Dictionary; manage: boolean };
type DocumentParams = Awaited<PageProps<"/[lang]/dossiers/[companyId]/ventes">["searchParams"]>;

async function DocumentsView({ companyId, t, manage, canPost, query }: ViewProps & {
  canPost: boolean; query: DocumentParams;
}) {
  const { kind, statut } = query;
  const kindParam = SALES_KINDS.find((value) => value === kind);
  const statusParam = SALES_STATUSES.find((value) => value === statut);
  const [documents, partners] = await Promise.all([
    getSalesDocuments(companyId, { kind: kindParam, status: statusParam, limit: 100, offset: 0 }),
    getPartners(companyId, { limit: 200, offset: 0 }),
  ]);
  const partnerNames = new Map(partners.items.map((p) => [p.id, p.name]));

  return (
    <>
      <SalesFilters t={t} kindParam={kindParam} statusParam={statusParam} />
      <Card>
        <CardHeader><CardTitle>{t.sales.listTitle}</CardTitle></CardHeader>
        <CardContent>
          {documents.items.length ? (
            <SalesDocumentsTable companyId={companyId} documents={documents} partnerNames={partnerNames}
              manage={manage} canPost={canPost} t={t} />
          ) : (
            <p className="text-muted-foreground text-sm">
              {kindParam || statusParam || !manage ? t.sales.noMatchingDocuments : t.sales.empty}
            </p>
          )}
        </CardContent>
      </Card>
      {manage && <SalesEmailFormCard companyId={companyId} documents={documents} t={t} />}
    </>
  );
}

async function PaymentsView({ companyId, t, manage, canPost }: ViewProps & { canPost: boolean }) {
  const [payments, documents, partners] = await Promise.all([
    getSalesPayments(companyId, { limit: 50, offset: 0 }),
    getSalesDocuments(companyId, { limit: 100, offset: 0 }),
    manage ? getPartners(companyId, { active: true, limit: 200, offset: 0 }) : null,
  ]);
  return (
    <>
      {manage && <SalesPaymentFormCard companyId={companyId} documents={documents} t={t} />}
      {partners && <SalesDepositFormCard companyId={companyId} partners={partners} t={t} />}
      <Card className="mt-6">
        <CardHeader><CardTitle>{t.sales.paymentsTitle}</CardTitle></CardHeader>
        <CardContent>
          {payments.items.length ? (
            <SalesPaymentsTable companyId={companyId} payments={payments} documents={documents}
              t={t} manage={manage} canPost={canPost} />
          ) : <p className="text-muted-foreground text-sm">{t.sales.paymentsEmpty}</p>}
        </CardContent>
      </Card>
    </>
  );
}

async function CollectionView({ companyId, t, manage, currency }: ViewProps & { currency: string }) {
  const [documents, overdue, kpis, schedules, aging, reminders, policy] = await Promise.all([
    getSalesDocuments(companyId, { limit: 100, offset: 0 }),
    getSalesOverdue(companyId), getSalesKpis(companyId), getSalesSchedules(companyId),
    getSalesAging(companyId), getSalesReminders(companyId, { limit: 50, offset: 0 }),
    getSalesReminderPolicy(companyId),
  ]);
  return (
    <>
      <SalesOverdueCard companyId={companyId} overdue={overdue} t={t} manage={manage} />
      <SalesKpisCard kpis={kpis} currency={currency} t={t} />
      <SalesScheduleCard companyId={companyId} documents={documents} schedules={schedules} t={t} manage={manage} />
      <SalesAgingCard companyId={companyId} aging={aging} currency={currency} t={t} />
      <SalesRemindersHistoryCard companyId={companyId} reminders={reminders} documents={documents} t={t} manage={manage} />
      <SalesReminderPolicyCard companyId={companyId} policy={policy} t={t} manage={manage} />
    </>
  );
}

async function CreateView({ companyId, t }: { companyId: string; t: Dictionary }) {
  const [partners, rates] = await Promise.all([
    getPartners(companyId, { active: true, limit: 200, offset: 0 }), getTaxRates(companyId),
  ]);
  if (partners.total === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>{t.sales.createTitle}</CardTitle></CardHeader>
        <CardContent>
          <p className="mb-3 text-sm">{t.sales.firstPartnerHint}</p>
          <Button asChild variant="outline">
            <Link href={`/dossiers/${companyId}/tiers#fiche-tiers`}>{t.sales.openPartners}</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }
  return <SalesCreateDocumentCard companyId={companyId} partners={partners} rateOptions={activeRateOptions(rates)} t={t} />;
}

export default async function SalesPage({ params, searchParams }: PageProps<"/[lang]/dossiers/[companyId]/ventes">) {
  const { companyId } = await params;
  const [query, { t }, company] = await Promise.all([searchParams, getDictionary(), getCompany(companyId)]);
  const manage = can(company, "sales:manage");
  const canPost = can(company, "entries:post");
  const base = `/dossiers/${companyId}/ventes`;
  const sections = [
    { id: "documents", label: t.sales.listTitle, href: base },
    { id: "encaissements", label: t.sales.paymentsView, href: `${base}?vue=encaissements` },
    { id: "recouvrement", label: t.sales.collectionView, href: `${base}?vue=recouvrement` },
  ];
  const selected = query.vue === "nouveau" && manage ? "nouveau"
    : sections.find((section) => section.id === query.vue)?.id ?? "documents";

  return (
    <>
      <PageHeader title={t.sales.title} subtitle={t.sales.subtitle} actions={manage && selected !== "nouveau" ? (
        <Button asChild className="min-h-11 self-start">
          <Link href={`${base}?vue=nouveau`}>{t.sales.createInvoice}</Link>
        </Button>
      ) : undefined} />
      <nav aria-label={t.sales.title} className="mb-5 flex flex-wrap gap-x-3 border-b sm:gap-x-5">
        {sections.map(({ id, href, label }) => (
          <Link key={id} href={href} aria-current={id === selected ? "page" : undefined}
            className="text-muted-foreground hover:text-foreground aria-[current=page]:border-primary aria-[current=page]:text-primary inline-flex min-h-11 items-center border-b-2 border-transparent text-sm font-medium">
            {label}
          </Link>
        ))}
      </nav>
      <p className="text-muted-foreground mb-4 max-w-prose text-sm">{t.sales.noPostingNotice}</p>
      {selected === "documents" && <DocumentsView companyId={companyId} query={query} manage={manage} canPost={canPost} t={t} />}
      {selected === "encaissements" && <PaymentsView companyId={companyId} manage={manage} canPost={canPost} t={t} />}
      {selected === "recouvrement" && <CollectionView companyId={companyId} currency={company.company.currency} manage={manage} t={t} />}
      {selected === "nouveau" && <CreateView companyId={companyId} t={t} />}
    </>
  );
}

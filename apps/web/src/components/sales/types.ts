import type {
  getPartners,
  getSalesAging,
  getSalesDocuments,
  getSalesOverdue,
  getSalesPayments,
  getSalesReminderPolicy,
  getSalesSchedules,
  getSalesKpis,
  getSalesReminders,
  getTaxRates,
} from "@/lib/dal";
import type { fr } from "@/lib/i18n/fr";

/** Types dérivés du DAL (import type : aucun import serveur au runtime). */
export type SalesDocumentsPage = Awaited<ReturnType<typeof getSalesDocuments>>;
export type SalesDocument = SalesDocumentsPage["items"][number];
export type SalesPaymentsPage = Awaited<ReturnType<typeof getSalesPayments>>;
export type SalesPayment = SalesPaymentsPage["items"][number];
export type SalesAging = Awaited<ReturnType<typeof getSalesAging>>;
export type SalesOverdue = Awaited<ReturnType<typeof getSalesOverdue>>;
export type SalesRemindersPage = Awaited<ReturnType<typeof getSalesReminders>>;
export type SalesReminder = SalesRemindersPage["items"][number];
export type SalesReminderPolicy = Awaited<ReturnType<typeof getSalesReminderPolicy>>;
export type SalesSchedules = Awaited<ReturnType<typeof getSalesSchedules>>;
export type SalesKpis = Awaited<ReturnType<typeof getSalesKpis>>;
export type PartnersPage = Awaited<ReturnType<typeof getPartners>>;
export type Partner = PartnersPage["items"][number];
export type TaxRateList = Awaited<ReturnType<typeof getTaxRates>>;
export type TaxRate = TaxRateList[number];

export type Dictionary = typeof fr;
export type SalesDict = typeof fr["sales"];
export type CommonDict = typeof fr["common"];

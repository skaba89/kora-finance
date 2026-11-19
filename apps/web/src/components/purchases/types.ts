import type {
  getPartners,
  getPayablesAging,
  getPurchaseDocuments,
  getPurchasePayments,
  getTaxRates,
} from "@/lib/dal";
import type { fr } from "@/lib/i18n/fr";

/** Types dérivés du DAL (import type : aucun import serveur au runtime). */
export type PurchaseDocumentsPage = Awaited<ReturnType<typeof getPurchaseDocuments>>;
export type PurchaseDocument = PurchaseDocumentsPage["items"][number];
export type PurchasePaymentsPage = Awaited<ReturnType<typeof getPurchasePayments>>;
export type PurchasePayment = PurchasePaymentsPage["items"][number];
export type PayablesAging = Awaited<ReturnType<typeof getPayablesAging>>;
export type PartnersPage = Awaited<ReturnType<typeof getPartners>>;
export type TaxRateList = Awaited<ReturnType<typeof getTaxRates>>;

export type Dictionary = typeof fr;

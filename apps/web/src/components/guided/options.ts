import type { components } from "@/lib/api/schema";
import type { Locale } from "@/lib/i18n/config";
import type { Dictionary } from "@/lib/i18n/server";

import type { AccountOption, GuidedFormLabels, NatureOption } from "./guided-form";

/**
 * Préparation de la saisie guidée à partir des options de l'API : commune à la page en
 * ligne et à la saisie hors connexion (options conservées sur l'appareil).
 */

type GuidedOptions = components["schemas"]["GuidedOptions"];
type Operation = components["schemas"]["Operation"];

export const GUIDED_GROUPS: { key: "income" | "expenses" | "treasury"; operations: Operation[] }[] = [
  { key: "income", operations: ["VENTE_COMPTANT", "FACTURE_CLIENT", "ENCAISSEMENT_CLIENT"] },
  { key: "expenses", operations: ["ACHAT_COMPTANT", "FACTURE_FOURNISSEUR", "PAIEMENT_FOURNISSEUR"] },
  { key: "treasury", operations: ["VIREMENT_INTERNE"] },
];
const INCOMING: readonly Operation[] = ["VENTE_COMPTANT", "ENCAISSEMENT_CLIENT"];
const INVOICES: readonly Operation[] = ["FACTURE_CLIENT", "FACTURE_FOURNISSEUR", "ENCAISSEMENT_CLIENT", "PAIEMENT_FOURNISSEUR"];

export type GuidedChoices = {
  natures: NatureOption[] | null;
  treasury: AccountOption[] | null;
  target: AccountOption[] | null;
  parties: AccountOption[] | null;
  vat: { ratePercent: string; verified: boolean } | null;
  /** Choix sans aucun compte disponible (formulaire impossible), sinon null. */
  missing: string | null;
  labels: GuidedFormLabels;
};

export function guidedChoices(
  options: GuidedOptions,
  operation: Operation,
  t: Dictionary["guided"],
  locale: Locale,
): GuidedChoices | null {
  const spec = options.operations.find((o) => o.code === operation);
  if (!spec) return null;
  const toOption = ({ id, number, label }: AccountOption) => ({ id, number, label });
  const natures = spec.nature
    ? (options.natures[spec.nature] ?? []).map((choice) => ({
        id: choice.account.id,
        label: `${locale === "en" ? choice.label_en : choice.label} (${choice.account.number})`,
        vatPossible: choice.vat_possible,
      }))
    : null;
  const treasury = spec.treasury ? options.treasury_accounts.map(toOption) : null;
  const parties = spec.party ? (options.party_accounts[spec.party] ?? []).map(toOption) : null;
  const missing =
    [
      natures && natures.length === 0 ? (spec.nature === "PRODUIT" ? t.natureIncome : t.natureExpense) : null,
      treasury && treasury.length === 0 ? t.paidFrom : null,
      parties && parties.length === 0 ? (spec.party === "CLIENT" ? t.client : t.supplier) : null,
    ].find((value): value is string => Boolean(value)) ?? null;
  const vat = options.vat
    ? {
        ratePercent: (options.vat.rate_basis_points / 100).toLocaleString(locale === "en" ? "en-US" : "fr-FR"),
        verified: options.vat.verified,
      }
    : null;

  return {
    natures,
    treasury,
    target: spec.target_treasury ? treasury : null,
    parties,
    vat,
    missing,
    labels: {
      date: t.date,
      amount: t.amount,
      amountHint: t.amountHint,
      nature: spec.nature === "PRODUIT" ? t.natureIncome : t.natureExpense,
      treasury: spec.target_treasury ? t.from : INCOMING.includes(operation) ? t.receivedOn : t.paidFrom,
      target: spec.target_treasury ? t.to : null,
      party: spec.party === "CLIENT" ? t.client : spec.party === "FOURNISSEUR" ? t.supplier : null,
      vatIncluded: t.vatIncluded,
      vatUnverified: t.vatUnverified,
      label: t.label,
      labelHint: t.labelHint,
      reference: INVOICES.includes(operation) ? t.invoiceNumber : t.reference,
      choose: t.choose,
      preview: t.preview,
      saveDraft: t.saveDraft,
      saveAndPost: t.saveAndPost,
      pending: t.pending,
      previewTitle: t.previewTitle,
      journal: t.journal,
      account: t.account,
      debit: t.debit,
      credit: t.credit,
      openDraft: t.openDraft,
    },
  };
}

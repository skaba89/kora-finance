import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { type AccountOption, GuidedForm } from "@/components/guided/guided-form";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { guidedEntryAction } from "@/lib/actions/guided";
import type { components } from "@/lib/api/schema";
import { can, getCompany, getGuidedOptions } from "@/lib/dal";
import { currencyDecimals } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

type Operation = components["schemas"]["Operation"];

const GROUPS: { key: "income" | "expenses" | "treasury"; operations: Operation[] }[] = [
  { key: "income", operations: ["VENTE_COMPTANT", "FACTURE_CLIENT", "ENCAISSEMENT_CLIENT"] },
  { key: "expenses", operations: ["ACHAT_COMPTANT", "FACTURE_FOURNISSEUR", "PAIEMENT_FOURNISSEUR"] },
  { key: "treasury", operations: ["VIREMENT_INTERNE"] },
];
const ALL: readonly string[] = GROUPS.flatMap((g) => g.operations);
const INCOMING: readonly Operation[] = ["VENTE_COMPTANT", "ENCAISSEMENT_CLIENT"];
const INVOICES: readonly Operation[] = ["FACTURE_CLIENT", "FACTURE_FOURNISSEUR", "ENCAISSEMENT_CLIENT", "PAIEMENT_FOURNISSEUR"];

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.guided.title };
}

export default async function GuidedEntryPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/saisie-guidee">) {
  const { companyId } = await params;
  const { operation: raw } = await searchParams;
  const [{ t, locale }, company] = await Promise.all([getDictionary(), getCompany(companyId)]);
  if (!can(company, "entries:write")) notFound();
  const base = `/dossiers/${companyId}/saisie-guidee`;
  const operation = typeof raw === "string" && ALL.includes(raw) ? (raw as Operation) : null;

  if (!operation) {
    return (
      <>
        <PageHeader title={t.guided.title} subtitle={t.guided.subtitle} />
        {GROUPS.map((group) => (
          <section key={group.key} className="mb-6" aria-labelledby={`group-${group.key}`}>
            <h2 id={`group-${group.key}`} className="mb-2 font-medium">
              {t.guided.groups[group.key]}
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {group.operations.map((code) => (
                <li key={code}>
                  <Link href={`${base}?operation=${code}`} className="block h-full">
                    <Card className="hover:bg-muted/50 h-full transition-colors">
                      <CardHeader>
                        <CardTitle className="text-base">{t.guided.operations[code].title}</CardTitle>
                        <CardDescription>{t.guided.operations[code].description}</CardDescription>
                      </CardHeader>
                    </Card>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <p className="text-muted-foreground text-sm">{t.guided.expertNotice}</p>
      </>
    );
  }

  const options = await getGuidedOptions(companyId);
  const spec = options.operations.find((o) => o.code === operation);
  if (!spec) notFound();
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

  const what = [
    natures && natures.length === 0 ? (spec.nature === "PRODUIT" ? t.guided.natureIncome : t.guided.natureExpense) : null,
    treasury && treasury.length === 0 ? t.guided.paidFrom : null,
    parties && parties.length === 0 ? (spec.party === "CLIENT" ? t.guided.client : t.guided.supplier) : null,
  ].find(Boolean);

  const currency = company.company.currency;
  const vat = options.vat
    ? {
        ratePercent: (options.vat.rate_basis_points / 100).toLocaleString(locale === "en" ? "en-US" : "fr-FR"),
        verified: options.vat.verified,
      }
    : null;

  return (
    <>
      <PageHeader title={t.guided.operations[operation].title} subtitle={t.guided.operations[operation].description} />
      {what ? (
        <Alert variant="destructive" role="alert" className="mb-4 max-w-xl">
          <AlertDescription>{interpolate(t.guided.noAccount, { what })}</AlertDescription>
        </Alert>
      ) : (
        <GuidedForm
          action={guidedEntryAction.bind(null, companyId, operation, currencyDecimals(currency))}
          labels={{
            date: t.guided.date,
            amount: t.guided.amount,
            amountHint: t.guided.amountHint,
            nature: spec.nature === "PRODUIT" ? t.guided.natureIncome : t.guided.natureExpense,
            treasury: spec.target_treasury
              ? t.guided.from
              : INCOMING.includes(operation)
                ? t.guided.receivedOn
                : t.guided.paidFrom,
            target: spec.target_treasury ? t.guided.to : null,
            party: spec.party === "CLIENT" ? t.guided.client : spec.party === "FOURNISSEUR" ? t.guided.supplier : null,
            vatIncluded: t.guided.vatIncluded,
            vatUnverified: t.guided.vatUnverified,
            label: t.guided.label,
            labelHint: t.guided.labelHint,
            reference: INVOICES.includes(operation) ? t.guided.invoiceNumber : t.guided.reference,
            choose: t.guided.choose,
            preview: t.guided.preview,
            saveDraft: t.guided.saveDraft,
            saveAndPost: t.guided.saveAndPost,
            pending: t.guided.pending,
            previewTitle: t.guided.previewTitle,
            journal: t.guided.journal,
            account: t.guided.account,
            debit: t.guided.debit,
            credit: t.guided.credit,
            openDraft: t.guided.openDraft,
          }}
          natures={natures}
          treasury={treasury}
          target={spec.target_treasury ? treasury : null}
          parties={parties}
          vat={vat}
          defaultDate={new Date().toISOString().slice(0, 10)}
          canPost={can(company, "entries:post")}
          currency={currency}
          locale={locale}
          companyId={companyId}
        />
      )}
      <p className="text-muted-foreground mt-6 max-w-xl text-sm">{t.guided.expertNotice}</p>
      <p className="mt-4">
        <Link href={base} className="text-sm underline underline-offset-4">
          {t.guided.otherOperation}
        </Link>
      </p>
    </>
  );
}

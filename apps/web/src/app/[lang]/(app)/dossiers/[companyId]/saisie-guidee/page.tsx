import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { GuidedForm } from "@/components/guided/guided-form";
import { GUIDED_GROUPS, guidedChoices } from "@/components/guided/options";
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

const ALL: readonly string[] = GUIDED_GROUPS.flatMap((g) => g.operations);

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
        {GUIDED_GROUPS.map((group) => (
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
  const choices = guidedChoices(options, operation, t.guided, locale);
  if (!choices) notFound();
  const currency = company.company.currency;

  return (
    <>
      <PageHeader title={t.guided.operations[operation].title} subtitle={t.guided.operations[operation].description} />
      {choices.missing ? (
        <Alert variant="destructive" role="alert" className="mb-4 max-w-xl">
          <AlertDescription>{interpolate(t.guided.noAccount, { what: choices.missing })}</AlertDescription>
        </Alert>
      ) : (
        <GuidedForm
          action={guidedEntryAction.bind(null, companyId, operation, currencyDecimals(currency))}
          labels={choices.labels}
          natures={choices.natures}
          treasury={choices.treasury}
          target={choices.target}
          parties={choices.parties}
          vat={choices.vat}
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

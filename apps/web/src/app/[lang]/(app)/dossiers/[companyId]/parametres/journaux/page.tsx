import type { Metadata } from "next";
import { DataTable } from "@/components/data-table";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { createJournalAction, toggleJournalAction } from "@/lib/actions/ledger";
import { can, getCompany, getJournals } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.journals.title };
}

const KINDS = ["ACHATS", "VENTES", "TRESORERIE", "OPERATIONS_DIVERSES", "A_NOUVEAUX"] as const;

export default async function JournalsPage({ params }: PageProps<"/[lang]/dossiers/[companyId]/parametres/journaux">) {
  const { companyId } = await params;
  const [{ t }, company, journals] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getJournals(companyId),
  ]);
  const manage = can(company, "journals:manage");
  return (
    <>
      <PageHeader title={t.journals.title} subtitle={t.journals.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.common.expertNotice}</p>
      <DataTable label={t.journals.title}>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">{t.journals.code}</TableHead>
            <TableHead>{t.journals.label}</TableHead>
            <TableHead className="hidden sm:table-cell">{t.journals.kind}</TableHead>
            {manage ? <TableHead className="w-32">{t.common.actions}</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {journals.map((journal) => (
            <TableRow key={journal.id} className={journal.is_active ? undefined : "opacity-60"}>
              <TableCell className="font-mono">{journal.code}</TableCell>
              <TableCell className="whitespace-normal">
                {journal.label}
                {!journal.is_active ? (
                  <Badge variant="outline" className="ml-2">
                    {t.journals.inactive}
                  </Badge>
                ) : null}
              </TableCell>
              <TableCell className="hidden sm:table-cell">{t.journals.kinds[journal.kind]}</TableCell>
              {manage ? (
                <TableCell>
                  <InlineAction
                    action={toggleJournalAction.bind(null, companyId, journal.id, !journal.is_active)}
                    label={journal.is_active ? t.journals.deactivate : t.journals.activate}
                    pendingLabel={t.common.pending}
                  />
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </DataTable>

      {manage ? (
        <Card className="mt-8 max-w-xl">
          <CardHeader>
            <CardTitle className="text-base">{t.journals.addTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={createJournalAction.bind(null, companyId)}
              submitLabel={t.common.create}
              pendingLabel={t.common.pending}
              resetOnSuccess
            >
              <Field
                label={t.journals.code}
                name="code"
                required
                maxLength={8}
                pattern="[A-Za-z0-9]{1,8}"
                hint={t.journals.codeHint}
                className="uppercase"
              />
              <Field label={t.journals.label} name="label" required maxLength={120} />
              <SelectField
                label={t.journals.kind}
                name="kind"
                defaultValue="TRESORERIE"
                options={KINDS.map((kind) => ({ value: kind, label: t.journals.kinds[kind] }))}
              />
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

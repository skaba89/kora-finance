import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createPartnerAction,
  setPartnerActiveAction,
  updatePartnerAction,
} from "@/lib/actions/partners";
import { can, getActiveAccounts, getCompany, getPartner, getPartners } from "@/lib/dal";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.partners.title };
}

const KINDS = ["CLIENT", "FOURNISSEUR"] as const;

/** Page référentiel des tiers (4A) : fiches clients et fournisseurs. Créer ou
 * modifier un tier n'écrit rien en comptabilité — le référentiel prépare la
 * facturation (4B), les règlements (4C) et les relances (4D). */
export default async function PartnersPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/tiers">) {
  const { companyId } = await params;
  const { q, kind, tous, edit } = await searchParams;
  const qParam = typeof q === "string" ? q : undefined;
  const kindParam =
    typeof kind === "string" && KINDS.includes(kind as (typeof KINDS)[number])
      ? (kind as (typeof KINDS)[number])
      : undefined;
  const showInactive = tous === "1";
  const editParam = typeof edit === "string" ? edit : undefined;
  const [{ t }, company, partners, glAccounts] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getPartners(companyId, {
      q: qParam || undefined,
      kind: kindParam,
      active: showInactive ? undefined : true,
      limit: 200,
      offset: 0,
    }),
    getActiveAccounts(companyId),
  ]);
  const manage = can(company, "partners:manage");
  // Lien « Modifier » périmé (fiche filtrée, id invalide) : retour au formulaire de création.
  let editing = editParam ? (partners.items.find((p) => p.id === editParam) ?? null) : null;
  if (!editing && editParam && manage) {
    try {
      editing = await getPartner(companyId, editParam);
    } catch {
      editing = null;
    }
  }
  // Lier ?edit à la vue courante : les filtres restent appliqués.
  const keepFilters = new URLSearchParams();
  if (qParam) keepFilters.set("q", qParam);
  if (kindParam) keepFilters.set("kind", kindParam);
  if (showInactive) keepFilters.set("tous", "1");
  const withFilters = (extra: Record<string, string>) => {
    const query = new URLSearchParams(keepFilters);
    for (const [key, value] of Object.entries(extra)) query.set(key, value);
    return `?${query.toString()}`;
  };
  const accountOptions = glAccounts
    .filter((account) => /^4/.test(account.number))
    .map((account) => ({ value: account.id, label: `${account.number} — ${account.label}` }));

  const kindBadge = (tier: { is_client: boolean; is_supplier: boolean }) =>
    tier.is_client && tier.is_supplier
      ? t.partners.kinds.both
      : tier.is_client
        ? t.partners.kinds.client
        : t.partners.kinds.supplier;

  return (
    <>
      <PageHeader title={t.partners.title} subtitle={t.partners.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.partners.noPostingNotice}</p>

      <form method="get" className="mb-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">{t.partners.searchLabel}</span>
          <input
            name="q"
            defaultValue={qParam ?? ""}
            placeholder={t.partners.searchPlaceholder}
            className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground text-xs">{t.common.filter}</span>
          <select
            name="kind"
            defaultValue={kindParam ?? ""}
            aria-label={t.common.filter}
            className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          >
            <option value="">{t.partners.filterAll}</option>
            <option value="CLIENT">{t.partners.filterClients}</option>
            <option value="FOURNISSEUR">{t.partners.filterSuppliers}</option>
          </select>
        </label>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" name="tous" value="1" defaultChecked={showInactive} />
          {t.partners.showInactive}
        </label>
        <Button type="submit" size="sm" variant="outline">
          {t.common.filter}
        </Button>
      </form>

      <p className="text-muted-foreground mb-2 text-sm">
        {interpolate(t.partners.total, { total: partners.total })}
      </p>

      {partners.items.length === 0 ? (
        <p className="text-muted-foreground mb-6">{t.partners.empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t.partners.name}</TableHead>
              <TableHead className="hidden sm:table-cell">{t.partners.taxId}</TableHead>
              <TableHead className="hidden md:table-cell">{t.partners.contactName}</TableHead>
              <TableHead className="hidden lg:table-cell">
                {t.partners.defaultClientAccount}
              </TableHead>
              <TableHead className="hidden lg:table-cell">
                {t.partners.defaultSupplierAccount}
              </TableHead>
              <TableHead className="text-right">{t.partners.active}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {partners.items.map((tier) => (
              <TableRow key={tier.id} className={tier.is_active ? undefined : "opacity-60"}>
                <TableCell className="whitespace-normal">
                  <span className="font-medium">{tier.name}</span>
                  <Badge variant="secondary" className="ml-2">
                    {kindBadge(tier)}
                  </Badge>
                  {!tier.is_active ? (
                    <Badge variant="outline" className="ml-2">
                      {t.partners.inactive}
                    </Badge>
                  ) : null}
                  {tier.phone ? (
                    <span className="text-muted-foreground block text-xs">{tier.phone}</span>
                  ) : null}
                </TableCell>
                <TableCell className="hidden font-mono text-xs sm:table-cell">
                  {tier.tax_id}
                </TableCell>
                <TableCell className="hidden whitespace-normal md:table-cell">
                  {tier.contact_name}
                </TableCell>
                <TableCell className="hidden font-mono text-xs lg:table-cell">
                  {glAccounts.find((a) => a.id === tier.default_client_account_id)?.number}
                </TableCell>
                <TableCell className="hidden font-mono text-xs lg:table-cell">
                  {glAccounts.find((a) => a.id === tier.default_supplier_account_id)?.number}
                </TableCell>
                <TableCell className="text-right">
                  {manage ? (
                    <div className="inline-flex items-center justify-end gap-2">
                      <Link
                        href={withFilters({ edit: tier.id })}
                        className="text-sm underline-offset-4 hover:underline"
                      >
                        {t.partners.edit}
                      </Link>
                      <InlineAction
                        action={setPartnerActiveAction.bind(
                          null,
                          companyId,
                          tier.id,
                          !tier.is_active,
                        )}
                        label={tier.is_active ? t.partners.deactivate : t.partners.reactivate}
                        pendingLabel={
                          tier.is_active ? t.partners.deactivate : t.partners.reactivate
                        }
                        confirm={tier.is_active ? t.partners.deactivateConfirm : undefined}
                        variant={tier.is_active ? "outline" : "secondary"}
                      />
                    </div>
                  ) : (
                    <span className="text-muted-foreground text-xs">
                      {tier.is_active ? t.partners.active : t.partners.inactive}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {manage ? (
        <Card id="fiche-tiers" className="mt-8 scroll-mt-4">
          <CardHeader>
            <CardTitle className="text-base">
              {editing ? t.partners.editTitle : t.partners.addTitle}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={
                editing
                  ? updatePartnerAction.bind(null, companyId, editing.id)
                  : createPartnerAction.bind(null, companyId)
              }
              submitLabel={t.common.save}
              pendingLabel={t.common.pending}
              className="max-w-2xl"
            >
              <Field
                label={t.partners.name}
                name="name"
                required
                maxLength={200}
                defaultValue={editing?.name ?? ""}
              />
              <fieldset className="flex flex-wrap gap-6">
                <legend className="text-muted-foreground mb-2 text-xs">{t.partners.kindHint}</legend>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name="is_client"
                    defaultChecked={editing?.is_client ?? false}
                  />
                  {t.partners.isClient}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name="is_supplier"
                    defaultChecked={editing?.is_supplier ?? false}
                  />
                  {t.partners.isSupplier}
                </label>
              </fieldset>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label={t.partners.taxId}
                  name="tax_id"
                  maxLength={50}
                  defaultValue={editing?.tax_id ?? ""}
                />
                <Field
                  label={t.partners.rccm}
                  name="rccm"
                  maxLength={50}
                  defaultValue={editing?.rccm ?? ""}
                />
              </div>
              <Field
                label={t.partners.address}
                name="address"
                maxLength={300}
                defaultValue={editing?.address ?? ""}
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label={t.partners.email}
                  name="email"
                  type="email"
                  maxLength={254}
                  defaultValue={editing?.email ?? ""}
                />
                <Field
                  label={t.partners.phone}
                  name="phone"
                  maxLength={30}
                  defaultValue={editing?.phone ?? ""}
                />
              </div>
              <Field
                label={t.partners.contactName}
                name="contact_name"
                maxLength={120}
                defaultValue={editing?.contact_name ?? ""}
              />
              <SelectField
                label={t.partners.defaultClientAccount}
                name="default_client_account_id"
                hint={t.partners.defaultAccountHint}
                defaultValue={editing?.default_client_account_id ?? ""}
                options={[{ value: "", label: "—" }, ...accountOptions]}
              />
              <SelectField
                label={t.partners.defaultSupplierAccount}
                name="default_supplier_account_id"
                hint={t.partners.defaultAccountHint}
                defaultValue={editing?.default_supplier_account_id ?? ""}
                options={[{ value: "", label: "—" }, ...accountOptions]}
              />
              <Field label={t.partners.notes} name="notes" defaultValue={editing?.notes ?? ""} />
              {editing ? (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" name="is_active" defaultChecked={editing.is_active} />
                  {t.partners.active}
                </label>
              ) : null}
            </ActionForm>
            {editing ? (
              <p className="text-muted-foreground mt-4 text-sm">
                <Link href={withFilters({})} className="underline-offset-4 hover:underline">
                  {t.common.cancel}
                </Link>
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}

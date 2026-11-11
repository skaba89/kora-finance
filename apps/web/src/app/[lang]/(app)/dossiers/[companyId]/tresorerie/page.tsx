import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
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
  createTreasuryAccountAction,
  recordTreasuryMovementAction,
  recordTreasuryTransferAction,
} from "@/lib/actions/treasury";
import {
  can,
  getActiveAccounts,
  getCompany,
  getTreasuryAccounts,
  getTreasuryMovements,
} from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.treasury.title };
}

const KINDS = ["BANQUE", "CAISSE", "MOBILE_MONEY"] as const;
const MOVEMENTS = ["DEPOT", "RETRAIT", "FRAIS"] as const;
const OPERATORS = ["ORANGE_MONEY_GN", "MTN_MOMO_GN"] as const;

/** Page trésorerie : comptes financiers, mouvements et virements internes (3A). */
export default async function TreasuryPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/tresorerie">) {
  const { companyId } = await params;
  const { compte } = await searchParams;
  const compteParam = typeof compte === "string" ? compte : compte?.[0];
  const [{ t, locale }, company, accountList, glAccounts] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getTreasuryAccounts(companyId),
    getActiveAccounts(companyId),
  ]);
  const accounts = accountList.items;
  const manage = can(company, "treasury:manage");
  const selectedId = compteParam ?? accounts[0]?.id;
  const selected = accounts.find((account) => account.id === selectedId);
  const movements = selected ? await getTreasuryMovements(companyId, selected.id) : null;
  const treasuryGl = glAccounts.filter((account) => /^(52|57)/.test(account.number));

  return (
    <>
      <PageHeader title={t.treasury.title} subtitle={t.treasury.subtitle} />
      <p className="text-muted-foreground -mt-4 mb-4 text-xs">{t.treasury.immutableNotice}</p>

      {accounts.length === 0 ? (
        <p className="text-muted-foreground mb-6">{t.treasury.empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t.treasury.name}</TableHead>
              <TableHead className="hidden sm:table-cell">{t.treasury.movementKind}</TableHead>
              <TableHead className="hidden md:table-cell">{t.treasury.glAccount}</TableHead>
              <TableHead className="text-right">{t.treasury.balance}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {accounts.map((account) => (
              <TableRow key={account.id} className={account.is_active ? undefined : "opacity-60"}>
                <TableCell className="whitespace-normal">
                  <Link
                    href={`?compte=${account.id}`}
                    className="font-medium underline-offset-4 hover:underline"
                  >
                    {account.name}
                  </Link>
                  {account.account_number_masked ? (
                    <span className="text-muted-foreground ml-2 font-mono text-xs">
                      {account.account_number_masked}
                    </span>
                  ) : null}
                  {!account.is_active ? (
                    <Badge variant="outline" className="ml-2">
                      {t.treasury.inactive}
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {t.treasury.kinds[account.kind]}
                  {account.operator ? (
                    <span className="text-muted-foreground block text-xs">
                      {(t.treasury.operators as Record<string, string>)[account.operator] ??
                        account.operator}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell className="hidden font-mono text-xs md:table-cell">
                  {account.gl_account_number}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {formatMoney(Number(account.balance), "GNF", locale)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {selected && movements ? (
        <Card className="mt-8">
          <CardHeader>
            <CardTitle className="text-base">
              {t.treasury.movements} — {selected.name}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {movements.items.length === 0 ? (
              <p className="text-muted-foreground">{t.treasury.noMovement}</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-28">{t.treasury.movementDate}</TableHead>
                    <TableHead>{t.treasury.movementKind}</TableHead>
                    <TableHead className="hidden sm:table-cell">{t.treasury.label}</TableHead>
                    <TableHead className="hidden md:table-cell">{t.treasury.counterpart}</TableHead>
                    <TableHead className="text-right">{t.treasury.amount}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {movements.items.map((movement) => (
                    <TableRow key={movement.id}>
                      <TableCell>{movement.movement_date}</TableCell>
                      <TableCell>
                        {t.treasury.movementKinds[movement.kind]}
                        <span className="text-muted-foreground block text-xs">
                          {t.treasury.direction[movement.direction]}
                        </span>
                      </TableCell>
                      <TableCell className="hidden whitespace-normal sm:table-cell">
                        {movement.label}
                        {movement.entry_number ? (
                          <span className="text-muted-foreground block font-mono text-xs">
                            {t.treasury.entryNumber} n°{movement.entry_number}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="hidden font-mono text-xs md:table-cell">
                        {movement.counterpart_number}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatMoney(Number(movement.amount), "GNF", locale)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      ) : null}

      {manage ? (
        <div className="mt-8 grid gap-8 lg:grid-cols-2">
          <Card className="max-w-xl">
            <CardHeader>
              <CardTitle className="text-base">{t.treasury.addTitle}</CardTitle>
            </CardHeader>
            <CardContent>
              <ActionForm
                action={createTreasuryAccountAction.bind(null, companyId)}
                submitLabel={t.common.create}
                pendingLabel={t.common.pending}
                resetOnSuccess
              >
                <Field label={t.treasury.name} name="name" required maxLength={120} />
                <SelectField
                  label={t.treasury.movementKind}
                  name="kind"
                  required
                  options={KINDS.map((kind) => ({ value: kind, label: t.treasury.kinds[kind] }))}
                />
                <SelectField
                  label={t.treasury.operator}
                  name="operator"
                  options={[
                    { value: "", label: "—" },
                    ...OPERATORS.map((operator) => ({
                      value: operator,
                      label: (t.treasury.operators as Record<string, string>)[operator] ?? operator,
                    })),
                  ]}
                />
                <SelectField
                  label={t.treasury.glAccount}
                  name="gl_account_id"
                  required
                  hint={t.treasury.glAccountHint}
                  options={treasuryGl.map((account) => ({
                    value: account.id,
                    label: `${account.number} — ${account.label}`,
                  }))}
                />
                <Field
                  label={t.treasury.maskedNumber}
                  name="account_number_masked"
                  maxLength={40}
                  hint={t.treasury.maskedNumberHint}
                />
              </ActionForm>
            </CardContent>
          </Card>

          <Card className="max-w-xl">
            <CardHeader>
              <CardTitle className="text-base">{t.treasury.addMovementTitle}</CardTitle>
            </CardHeader>
            <CardContent>
              {accounts.length === 0 ? null : (
                <ActionForm
                  action={recordTreasuryMovementAction.bind(null, companyId, selectedId ?? "")}
                  submitLabel={t.treasury.movement}
                  pendingLabel={t.common.pending}
                  resetOnSuccess
                >
                  <SelectField
                    label={t.treasury.movementKind}
                    name="kind"
                    required
                    options={MOVEMENTS.map((kind) => ({
                      value: kind,
                      label: t.treasury.movementKinds[kind],
                    }))}
                  />
                  <Field
                    label={t.treasury.amount}
                    name="amount"
                    type="number"
                    required
                    min="1"
                    step="1"
                  />
                  <Field label={t.treasury.movementDate} name="movement_date" type="date" required />
                  <Field label={t.treasury.label} name="label" required maxLength={200} />
                  <SelectField
                    label={t.treasury.counterpart}
                    name="counterpart_account_id"
                    required
                    hint={t.treasury.counterpartHint}
                    options={glAccounts.map((account) => ({
                      value: account.id,
                      label: `${account.number} — ${account.label}`,
                    }))}
                  />
                  <Field label={t.treasury.reference} name="reference" maxLength={60} />
                </ActionForm>
              )}
            </CardContent>
          </Card>

          <Card className="max-w-xl">
            <CardHeader>
              <CardTitle className="text-base">{t.treasury.transferTitle}</CardTitle>
            </CardHeader>
            <CardContent>
              {accounts.length >= 2 ? (
                <ActionForm
                  action={recordTreasuryTransferAction.bind(null, companyId)}
                  submitLabel={t.treasury.transferTitle}
                  pendingLabel={t.common.pending}
                  resetOnSuccess
                >
                  <SelectField
                    label={t.treasury.source}
                    name="source_account_id"
                    required
                    options={accounts
                      .filter((account) => account.is_active)
                      .map((account) => ({ value: account.id, label: account.name }))}
                  />
                  <SelectField
                    label={t.treasury.target}
                    name="target_account_id"
                    required
                    options={accounts
                      .filter((account) => account.is_active)
                      .map((account) => ({ value: account.id, label: account.name }))}
                  />
                  <Field
                    label={t.treasury.amount}
                    name="amount"
                    type="number"
                    required
                    min="1"
                    step="1"
                  />
                  <Field label={t.treasury.movementDate} name="movement_date" type="date" required />
                  <Field label={t.treasury.label} name="label" required maxLength={200} />
                  <Field label={t.treasury.reference} name="reference" maxLength={60} />
                </ActionForm>
              ) : null}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}

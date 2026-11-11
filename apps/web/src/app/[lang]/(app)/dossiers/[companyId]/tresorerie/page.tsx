import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { InlineAction } from "@/components/forms/inline-action";
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
import { StatementUploadForm } from "@/components/treasury/statement-upload-form";
import {
  createTreasuryAccountAction,
  deleteStatementAction,
  ignoreStatementLineAction,
  importStatementAction,
  matchStatementLineAction,
  recordTreasuryMovementAction,
  recordTreasuryTransferAction,
  restoreStatementLineAction,
  unmatchStatementLineAction,
} from "@/lib/actions/treasury";
import {
  can,
  getActiveAccounts,
  getCompany,
  getMatchCandidates,
  getReconciliationOverview,
  getStatementLines,
  getTreasuryAccounts,
  getTreasuryMovements,
  getTreasuryStatements,
} from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.treasury.title };
}

const KINDS = ["BANQUE", "CAISSE", "MOBILE_MONEY"] as const;
const MOVEMENTS = ["DEPOT", "RETRAIT", "FRAIS"] as const;
const OPERATORS = ["ORANGE_MONEY_GN", "MTN_MOMO_GN"] as const;

/** Page trésorerie : comptes financiers, mouvements et virements internes (3A),
 * relevés bancaires importés (3B), rapprochement assisté (3C). */
export default async function TreasuryPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/tresorerie">) {
  const { companyId } = await params;
  const { compte, releve, ligne } = await searchParams;
  const compteParam = typeof compte === "string" ? compte : compte?.[0];
  const releveParam = typeof releve === "string" ? releve : releve?.[0];
  const ligneParam = typeof ligne === "string" ? ligne : ligne?.[0];
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
  // Les relevés sont visibles dès la lecture (treasury:read) ; import et tri exigent treasury:manage.
  const statements = selected ? await getTreasuryStatements(companyId, selected.id) : null;
  const selectedStatement =
    statements && releveParam ? statements.items.find((item) => item.id === releveParam) : null;
  const statementLines = selectedStatement
    ? await getStatementLines(companyId, selectedStatement.id)
    : null;
  // Rapprochement (3C) : vue d'ensemble du compte, et candidats de la ligne choisie.
  // Lecture pour tout le monde (proposer n'écrit rien) ; confirmer exige treasury:manage.
  const overview = selected ? await getReconciliationOverview(companyId, selected.id) : null;
  const selectedLine = statementLines?.items.find((line) => line.id === ligneParam) ?? null;
  const candidates =
    selectedStatement && selectedLine && selectedLine.status === "PENDING"
      ? await getMatchCandidates(companyId, selectedStatement.id, selectedLine.id)
      : null;
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

      {selected && statements ? (
        <Card className="mt-8" role="region" aria-labelledby="statements-title">
          <CardHeader>
            <CardTitle id="statements-title" className="text-base">
              {t.treasury.releves.title} — {selected.name}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="text-muted-foreground text-sm">{t.treasury.releves.subtitle}</p>
            {overview ? (
              <p className="text-muted-foreground text-xs">
                <span className="font-medium text-foreground">
                  {t.treasury.rapprochement.overview.pending} : {overview.lines_pending}
                </span>
                {"  ·  "}
                {t.treasury.rapprochement.overview.matched} : {overview.lines_matched}
                {"  ·  "}
                {t.treasury.rapprochement.overview.ignored} : {overview.lines_ignored}
                {"  ·  "}
                {t.treasury.rapprochement.overview.pendingNet} :{" "}
                {formatMoney(Number(overview.pending_net), "GNF", locale)}
                {"  ·  "}
                {t.treasury.rapprochement.overview.movements} : {overview.movements_unmatched}
              </p>
            ) : null}
            {selectedStatement && statementLines ? (
              <>
                <p className="text-sm">
                  <Link
                    href={`?compte=${selected.id}`}
                    className="underline underline-offset-4"
                  >
                    {t.treasury.releves.backToList}
                  </Link>
                  <span className="text-muted-foreground ml-2 font-mono text-xs">
                    {selectedStatement.filename} ·{" "}
                    {selectedStatement.line_count} {t.treasury.releves.linesCount.toLowerCase()}
                  </span>
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">{t.treasury.releves.lineNo}</TableHead>
                      <TableHead className="w-28">{t.treasury.releves.lineDate}</TableHead>
                      <TableHead>{t.treasury.releves.lineLabel}</TableHead>
                      <TableHead className="hidden md:table-cell">{t.treasury.releves.lineRef}</TableHead>
                      <TableHead className="text-right">{t.treasury.releves.lineAmount}</TableHead>
                      <TableHead className="w-32">{t.treasury.releves.lineStatus}</TableHead>
                      {manage ? <TableHead className="w-28" /> : null}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {statementLines.items.map((line) => (
                      <TableRow key={line.id} className={line.status === "IGNORED" ? "opacity-60" : undefined}>
                        <TableCell className="font-mono text-xs">{line.line_no}</TableCell>
                        <TableCell>{line.value_date}</TableCell>
                        <TableCell className="whitespace-normal">
                          {line.label}
                          {line.duplicate ? (
                            <Badge variant="outline" className="ml-2">
                              {t.treasury.releves.duplicate}
                            </Badge>
                          ) : null}
                        </TableCell>
                        <TableCell className="hidden font-mono text-xs md:table-cell">
                          {line.reference}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {formatMoney(Number(line.amount), "GNF", locale)}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              line.status === "IGNORED"
                                ? "outline"
                                : line.status === "MATCHED"
                                  ? "secondary"
                                  : "default"
                            }
                          >
                            {t.treasury.releves.statuses[line.status]}
                          </Badge>
                        </TableCell>
                        {manage ? (
                          <TableCell>
                            {line.status === "MATCHED" ? (
                              <InlineAction
                                action={unmatchStatementLineAction.bind(
                                  null,
                                  companyId,
                                  selectedStatement.id,
                                  line.id,
                                )}
                                label={t.treasury.rapprochement.unmatch}
                                pendingLabel={t.common.pending}
                                variant="ghost"
                                confirm={t.treasury.rapprochement.unmatchConfirm}
                              />
                            ) : (
                              <div className="flex flex-wrap items-center gap-3">
                                {line.status === "PENDING" ? (
                                  <Link
                                    href={`?compte=${selected.id}&releve=${selectedStatement.id}&ligne=${line.id}`}
                                    className="text-sm underline underline-offset-4"
                                  >
                                    {t.treasury.rapprochement.propose}
                                  </Link>
                                ) : null}
                                <InlineAction
                                  action={
                                    line.status === "IGNORED"
                                      ? restoreStatementLineAction.bind(
                                          null,
                                          companyId,
                                          selectedStatement.id,
                                          line.id,
                                        )
                                      : ignoreStatementLineAction.bind(
                                          null,
                                          companyId,
                                          selectedStatement.id,
                                          line.id,
                                        )
                                  }
                                  label={
                                    line.status === "IGNORED"
                                      ? t.treasury.releves.restore
                                      : t.treasury.releves.ignore
                                  }
                                  pendingLabel={t.common.pending}
                                  variant="ghost"
                                />
                              </div>
                            )}
                          </TableCell>
                        ) : null}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {candidates ? (
                  <div
                    className="rounded-md border p-4"
                    role="region"
                    aria-labelledby="candidates-title"
                  >
                    <p className="text-sm font-medium" id="candidates-title">
                      {interpolate(t.treasury.rapprochement.candidatesTitle, {
                        line: selectedLine?.line_no ?? "",
                      })}
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs">
                      {selectedLine?.value_date} · {formatMoney(Number(selectedLine?.amount ?? 0), "GNF", locale)} ·{" "}
                      {selectedLine?.label}
                    </p>
                    <p className="text-muted-foreground mt-2 text-xs">
                      {t.treasury.rapprochement.confirmNotice}
                    </p>
                    {candidates.candidates.length === 0 ? (
                      <p className="text-muted-foreground mt-3 text-sm">
                        {t.treasury.rapprochement.noCandidates}
                      </p>
                    ) : (
                      <Table className="mt-3">
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-28">{t.treasury.movementDate}</TableHead>
                            <TableHead>{t.treasury.movementKind}</TableHead>
                            <TableHead>{t.treasury.label}</TableHead>
                            <TableHead className="text-right">{t.treasury.amount}</TableHead>
                            <TableHead className="hidden w-24 sm:table-cell">
                              {t.treasury.rapprochement.daysApart.replace("{days}", "").trim()}
                            </TableHead>
                            {manage ? <TableHead className="w-28" /> : null}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {candidates.candidates.map((candidate) => (
                            <TableRow key={candidate.id}>
                              <TableCell>{candidate.movement_date}</TableCell>
                              <TableCell>
                                {t.treasury.movementKinds[candidate.kind]}
                                <span className="text-muted-foreground block text-xs">
                                  {t.treasury.direction[candidate.direction]}
                                </span>
                              </TableCell>
                              <TableCell className="whitespace-normal">
                                {candidate.label}
                                {candidate.entry_number ? (
                                  <span className="text-muted-foreground block font-mono text-xs">
                                    {interpolate(t.treasury.rapprochement.entryNumber, {
                                      number: candidate.entry_number,
                                    })}
                                  </span>
                                ) : null}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {formatMoney(Number(candidate.amount), "GNF", locale)}
                              </TableCell>
                              <TableCell className="hidden font-mono text-xs sm:table-cell">
                                {candidate.days_apart}
                              </TableCell>
                              {manage ? (
                                <TableCell>
                                  <InlineAction
                                    action={matchStatementLineAction.bind(
                                      null,
                                      companyId,
                                      selectedStatement.id,
                                      selectedLine?.id ?? "",
                                      candidate.id,
                                    )}
                                    label={t.treasury.rapprochement.confirm}
                                    pendingLabel={t.common.pending}
                                    variant="secondary"
                                  />
                                </TableCell>
                              ) : null}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                    <p className="mt-3">
                      <Link
                        href={`?compte=${selected.id}&releve=${selectedStatement.id}`}
                        className="text-sm underline underline-offset-4"
                      >
                        {t.treasury.rapprochement.backToLines}
                      </Link>
                    </p>
                  </div>
                ) : null}
              </>
            ) : statements.items.length === 0 ? (
              <p className="text-muted-foreground">{t.treasury.releves.noStatement}</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t.treasury.releves.filename}</TableHead>
                    <TableHead className="w-20">{t.treasury.releves.format}</TableHead>
                    <TableHead className="hidden sm:table-cell">{t.treasury.releves.period}</TableHead>
                    <TableHead className="text-right">{t.treasury.releves.linesCount}</TableHead>
                    {manage ? <TableHead className="w-40" /> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {statements.items.map((view) => (
                    <TableRow key={view.id}>
                      <TableCell className="break-all font-medium">{view.filename}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{view.format}</Badge>
                      </TableCell>
                      <TableCell className="hidden text-sm sm:table-cell">
                        {view.period_start} → {view.period_end}
                      </TableCell>
                      <TableCell className="text-right font-mono">{view.line_count}</TableCell>
                      {manage ? (
                        <TableCell className="flex flex-wrap items-center gap-3">
                          <Link
                            href={`?compte=${selected.id}&releve=${view.id}`}
                            className="text-sm underline underline-offset-4"
                          >
                            {t.treasury.releves.viewLines}
                          </Link>
                          <InlineAction
                            action={deleteStatementAction.bind(null, companyId, view.id)}
                            label={t.treasury.releves.delete}
                            pendingLabel={t.common.pending}
                            variant="destructive"
                            confirm={t.treasury.releves.deleteConfirm}
                          />
                        </TableCell>
                      ) : null}
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

          {selected ? (
            <Card className="max-w-xl">
              <CardHeader>
                <CardTitle className="text-base">{t.treasury.releves.importTitle}</CardTitle>
              </CardHeader>
              <CardContent>
                <StatementUploadForm
                  action={importStatementAction.bind(null, companyId, selected.id)}
                  labels={{
                    file: t.treasury.releves.file,
                    hint: t.treasury.releves.fileHint,
                    submit: t.treasury.releves.import,
                    pending: t.treasury.releves.importing,
                  }}
                />
              </CardContent>
            </Card>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

"use client";

import { useActionState, useId, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ActionState } from "@/lib/actions/state";
import { IDLE } from "@/lib/actions/state";
import { amountInputValue, parseAmount, sumAmounts } from "@/lib/amounts";
import { formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { interpolate } from "@/lib/i18n/interpolate";
import { cn } from "@/lib/utils";
import { uuidV4 } from "@/lib/uuid";

export type EditorAccount = { id: string; number: string; label: string };
export type EditorJournal = { id: string; code: string; label: string };
export type EditorEntry = {
  id: string;
  journal_id: string;
  entry_date: string;
  reference: string | null;
  label: string;
  lines: { account_id: string; label: string | null; debit: string; credit: string }[];
};

export type EditorLabels = {
  journal: string;
  date: string;
  reference: string;
  referenceHint: string;
  label: string;
  account: string;
  accountPlaceholder: string;
  lineLabel: string;
  debit: string;
  credit: string;
  totals: string;
  difference: string;
  balanced: string;
  addLine: string;
  removeLine: string;
  lineN: string;
  saveDraft: string;
  saveAndPost: string;
  pending: string;
  invalidAmount: string;
  unknownAccount: string;
  oneSide: string;
  noLines: string;
};

type Line = { key: string; account: string; label: string; debit: string; credit: string };

const SEPARATOR = " — ";

function accountText(account: EditorAccount) {
  return `${account.number}${SEPARATOR}${account.label}`;
}

function emptyLine(): Line {
  return { key: uuidV4(), account: "", label: "", debit: "", credit: "" };
}

/**
 * Saisie d'une écriture en partie double. Les montants restent des chaînes de chiffres
 * (unités mineures) et les totaux sont calculés en BigInt : aucune arithmétique flottante.
 */
export function EntryEditor({
  action,
  journals,
  accounts,
  initial,
  defaultDate,
  currency,
  decimals,
  locale,
  canPost,
  labels,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  journals: EditorJournal[];
  accounts: EditorAccount[];
  initial?: EditorEntry;
  defaultDate: string;
  currency: string;
  decimals: number;
  locale: Locale;
  canPost: boolean;
  labels: EditorLabels;
}) {
  const listId = useId();
  const [state, formAction, pending] = useActionState(action, IDLE);
  const [clientId] = useState(() => uuidV4());
  const byId = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);
  const byNumber = useMemo(() => new Map(accounts.map((a) => [a.number, a])), [accounts]);

  // Par défaut : opérations diverses, le journal le plus neutre.
  const defaultJournal = journals.find((j) => j.code === "OD") ?? journals[0];
  const [journalId, setJournalId] = useState(initial?.journal_id ?? defaultJournal?.id ?? "");
  const [entryDate, setEntryDate] = useState(initial?.entry_date ?? defaultDate);
  const [reference, setReference] = useState(initial?.reference ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [lines, setLines] = useState<Line[]>(() =>
    initial
      ? initial.lines.map((l) => {
          const account = byId.get(l.account_id);
          return {
            key: uuidV4(),
            account: account ? accountText(account) : "",
            label: l.label ?? "",
            debit: amountInputValue(l.debit, decimals),
            credit: amountInputValue(l.credit, decimals),
          };
        })
      : [emptyLine(), emptyLine()],
  );
  const [errors, setErrors] = useState<string[]>([]);

  // Brouillon créé par un envoi précédent dont la validation a échoué : on le modifie.
  const savedId = (state.data?.entryId as string | undefined) ?? initial?.id ?? "";

  const resolve = (text: string) => {
    const trimmed = text.trim();
    const number = trimmed.split(SEPARATOR)[0]?.trim() ?? "";
    return byNumber.get(number);
  };

  const parsed = lines.map((line) => ({
    account: resolve(line.account),
    debit: parseAmount(line.debit, decimals),
    credit: parseAmount(line.credit, decimals),
  }));
  const totalDebit = sumAmounts(parsed.map((p) => p.debit ?? "0"));
  const totalCredit = sumAmounts(parsed.map((p) => p.credit ?? "0"));
  const difference = totalDebit - totalCredit;

  const payload = JSON.stringify({
    journal_id: journalId,
    entry_date: entryDate,
    reference: reference.trim() || null,
    label: label.trim(),
    lines: parsed.map((p, index) => ({
      account_id: p.account?.id ?? "",
      label: lines[index]?.label.trim() || null,
      debit: p.debit ?? "0",
      credit: p.credit ?? "0",
    })),
  });

  const validate = () => {
    const found: string[] = [];
    if (lines.length === 0) found.push(labels.noLines);
    parsed.forEach((p, index) => {
      const n = index + 1;
      if (!p.account) found.push(interpolate(labels.unknownAccount, { n }));
      if (p.debit === null || p.credit === null) found.push(interpolate(labels.invalidAmount, { n }));
      else if ((p.debit === "0") === (p.credit === "0")) found.push(interpolate(labels.oneSide, { n }));
    });
    setErrors(found);
    return found.length === 0;
  };

  const update = (key: string, patch: Partial<Line>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  const money = (value: bigint) => formatMoney(value, currency, locale);

  return (
    <form
      action={formAction}
      onSubmit={(event) => {
        if (!validate()) event.preventDefault();
      }}
      className="flex flex-col gap-6"
    >
      <input type="hidden" name="payload" value={payload} />
      <input type="hidden" name="entry_id" value={savedId} />
      <input type="hidden" name="client_id" value={clientId} />
      <datalist id={listId}>
        {accounts.map((account) => (
          <option key={account.id} value={accountText(account)} />
        ))}
      </datalist>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ecriture-journal">{labels.journal}</Label>
          <select
            id="ecriture-journal"
            value={journalId}
            onChange={(e) => setJournalId(e.target.value)}
            className="border-input bg-background h-9 rounded-md border px-3 text-sm"
            required
          >
            {journals.map((journal) => (
              <option key={journal.id} value={journal.id}>
                {journal.code} — {journal.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ecriture-date">{labels.date}</Label>
          <Input id="ecriture-date" type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} required />
        </div>
        <div className="flex flex-col gap-1.5 lg:col-span-2">
          <Label htmlFor="ecriture-libelle">{labels.label}</Label>
          <Input id="ecriture-libelle" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={200} required />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ecriture-piece">{labels.reference}</Label>
          <Input
            id="ecriture-piece"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            maxLength={60}
            aria-describedby="ecriture-piece-aide"
          />
          <p id="ecriture-piece-aide" className="text-muted-foreground text-xs">
            {labels.referenceHint}
          </p>
        </div>
      </div>

      <ol className="flex flex-col gap-3">
        {lines.map((line, index) => {
          const n = index + 1;
          const prefix = `ligne-${line.key}`;
          const p = parsed[index];
          return (
            <li
              key={line.key}
              aria-label={interpolate(labels.lineN, { n })}
              className="grid gap-2 rounded-md border p-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,2fr)_9rem_9rem_auto] sm:items-end sm:border-0 sm:p-0"
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor={`${prefix}-compte`} className={cn(index > 0 && "sm:sr-only")}>
                  {labels.account}
                </Label>
                <Input
                  id={`${prefix}-compte`}
                  list={listId}
                  value={line.account}
                  placeholder={labels.accountPlaceholder}
                  aria-invalid={line.account !== "" && !p?.account}
                  onChange={(e) => update(line.key, { account: e.target.value })}
                  autoComplete="off"
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor={`${prefix}-libelle`} className={cn(index > 0 && "sm:sr-only")}>
                  {labels.lineLabel}
                </Label>
                <Input
                  id={`${prefix}-libelle`}
                  value={line.label}
                  maxLength={200}
                  onChange={(e) => update(line.key, { label: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor={`${prefix}-debit`} className={cn(index > 0 && "sm:sr-only")}>
                  {labels.debit}
                </Label>
                <Input
                  id={`${prefix}-debit`}
                  inputMode={decimals > 0 ? "decimal" : "numeric"}
                  className="text-right tabular-nums"
                  value={line.debit}
                  aria-invalid={p?.debit === null}
                  onChange={(e) => update(line.key, { debit: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor={`${prefix}-credit`} className={cn(index > 0 && "sm:sr-only")}>
                  {labels.credit}
                </Label>
                <Input
                  id={`${prefix}-credit`}
                  inputMode={decimals > 0 ? "decimal" : "numeric"}
                  className="text-right tabular-nums"
                  value={line.credit}
                  aria-invalid={p?.credit === null}
                  onChange={(e) => update(line.key, { credit: e.target.value })}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`${labels.removeLine} ${n}`}
                onClick={() => setLines((current) => current.filter((l) => l.key !== line.key))}
              >
                <span aria-hidden className="hidden sm:inline">
                  ✕
                </span>
                <span aria-hidden className="sm:hidden">
                  {labels.removeLine}
                </span>
              </Button>
            </li>
          );
        })}
      </ol>
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => setLines((c) => [...c, emptyLine()])}>
          {labels.addLine}
        </Button>
      </div>

      <dl
        className="bg-muted/50 grid grid-cols-2 gap-x-4 gap-y-1 rounded-md p-3 text-sm sm:grid-cols-[auto_auto_auto] sm:justify-end"
        aria-live="polite"
      >
        <div className="flex flex-col">
          <dt className="text-muted-foreground">{labels.debit}</dt>
          <dd className="font-medium tabular-nums">{money(totalDebit)}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-muted-foreground">{labels.credit}</dt>
          <dd className="font-medium tabular-nums">{money(totalCredit)}</dd>
        </div>
        <div className="col-span-2 flex flex-col sm:col-span-1">
          <dt className="text-muted-foreground">{labels.difference}</dt>
          <dd
            data-testid="ecart"
            className={cn("font-medium tabular-nums", difference === 0n ? "text-success" : "text-destructive")}
          >
            {difference === 0n && totalDebit > 0n ? labels.balanced : money(difference < 0n ? -difference : difference)}
          </dd>
        </div>
      </dl>

      {errors.length > 0 || (state.status === "error" && state.message) ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>
            {state.status === "error" && state.message && errors.length === 0 ? <p>{state.message}</p> : null}
            <ul className="list-disc pl-5">
              {(errors.length > 0 ? errors : (state.errors ?? [])).map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button type="submit" name="intent" value="draft" variant={canPost ? "outline" : "default"} disabled={pending}>
          {pending ? labels.pending : labels.saveDraft}
        </Button>
        {canPost ? (
          <Button type="submit" name="intent" value="post" disabled={pending}>
            {pending ? labels.pending : labels.saveAndPost}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

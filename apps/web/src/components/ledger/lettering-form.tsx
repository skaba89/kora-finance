"use client";

import { useActionState, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ActionState } from "@/lib/actions/state";
import { IDLE } from "@/lib/actions/state";
import { formatDate, formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { interpolate } from "@/lib/i18n/interpolate";
import { cn } from "@/lib/utils";

export type OpenLine = {
  line_id: string;
  entry_date: string;
  journal_code: string;
  number: number | null;
  reference: string | null;
  label: string;
  debit: string;
  credit: string;
};

/**
 * Sélection des lignes à lettrer : l'écart de la sélection est calculé en BigInt et le
 * bouton ne s'active que lorsqu'il est nul (l'API et la base revérifient).
 */
export function LetteringForm({
  action,
  lines,
  currency,
  locale,
  canManage,
  labels,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  lines: OpenLine[];
  currency: string;
  locale: Locale;
  canManage: boolean;
  labels: {
    selection: string;
    selected: string;
    letter: string;
    selectionHint: string;
    difference: string;
    balanced: string;
    select: string;
    debitSide: string;
    creditSide: string;
    pending: string;
  };
}) {
  const [state, formAction, pending] = useActionState(action, IDLE);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const net = lines
    .filter((line) => selected.has(line.line_id))
    .reduce((total, line) => total + BigInt(line.debit) - BigInt(line.credit), 0n);
  const ready = selected.size >= 2 && net === 0n;
  const money = (value: bigint) => formatMoney(value < 0n ? -value : value, currency, locale);

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <form
      action={async (formData) => {
        await formAction(formData);
        setSelected(new Set());
      }}
      className="flex flex-col gap-4"
    >
      <ul className="divide-y rounded-md border">
        {lines.map((line) => {
          const debit = BigInt(line.debit);
          const amount = debit > 0n ? debit : BigInt(line.credit);
          const description = interpolate(labels.select, {
            date: formatDate(line.entry_date, locale),
            label: line.label,
          });
          return (
            <li key={line.line_id}>
              <label className={cn("flex items-start gap-3 p-3 text-sm", canManage && "cursor-pointer")}>
                {canManage ? (
                  <input
                    type="checkbox"
                    name="line_id"
                    value={line.line_id}
                    checked={selected.has(line.line_id)}
                    onChange={() => toggle(line.line_id)}
                    aria-label={description}
                    className="mt-1 size-4"
                  />
                ) : null}
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="text-muted-foreground flex flex-wrap gap-x-3">
                    <span className="tabular-nums">{formatDate(line.entry_date, locale)}</span>
                    <span className="font-mono">
                      {line.journal_code} {line.number}
                    </span>
                    {line.reference ? <span>{line.reference}</span> : null}
                  </span>
                  <span className="break-words">{line.label}</span>
                </span>
                <span className="text-right whitespace-nowrap tabular-nums">
                  {formatMoney(amount, currency, locale)} {debit > 0n ? labels.debitSide : labels.creditSide}
                </span>
              </label>
            </li>
          );
        })}
      </ul>

      {canManage ? (
        <div className="bg-muted/50 flex flex-wrap items-center justify-between gap-3 rounded-md p-3 text-sm">
          <div aria-live="polite">
            <p className="font-medium">{interpolate(labels.selected, { count: selected.size })}</p>
            <p className={cn("tabular-nums", selected.size > 0 && net !== 0n ? "text-destructive" : "text-muted-foreground")}>
              {selected.size === 0
                ? labels.selectionHint
                : net === 0n
                  ? labels.balanced
                  : `${labels.difference} : ${money(net)} ${net > 0n ? labels.debitSide : labels.creditSide}`}
            </p>
          </div>
          <Button type="submit" disabled={!ready || pending}>
            {pending ? labels.pending : labels.letter}
          </Button>
        </div>
      ) : null}

      {state.status === "error" && state.message ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>
            <p>{state.message}</p>
            {state.errors?.length ? (
              <ul className="list-disc pl-5">
                {state.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
    </form>
  );
}

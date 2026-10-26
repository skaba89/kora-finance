"use client";

import { startTransition, useActionState, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ActionState } from "@/lib/actions/state";
import { formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { uuidV4 } from "@/lib/uuid";

const IDLE: ActionState = { status: "idle" };

export type AccountOption = { id: string; number: string; label: string };
export type NatureOption = { id: string; label: string; vatPossible: boolean };

export type GuidedFormLabels = {
  date: string;
  amount: string;
  amountHint: string;
  nature: string;
  treasury: string;
  target: string | null;
  party: string | null;
  vatIncluded: string;
  vatUnverified: string;
  label: string;
  labelHint: string;
  reference: string;
  choose: string;
  preview: string;
  saveDraft: string;
  saveAndPost: string;
  pending: string;
  previewTitle: string;
  journal: string;
  account: string;
  debit: string;
  credit: string;
  openDraft: string;
};

type Preview = {
  journal_code: string;
  journal_label: string;
  label: string;
  reference: string | null;
  lines: { account_id: string; account_number: string; account_label: string; debit: string; credit: string }[];
  warnings: string[];
};

function AccountSelect({
  id,
  name,
  label,
  accounts,
  placeholder,
  initial,
}: {
  id: string;
  name: string;
  label: string;
  accounts: AccountOption[];
  placeholder: string;
  initial?: string | null;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        name={name}
        required
        defaultValue={initial ?? (accounts.length === 1 ? accounts[0]?.id : "")}
        className="border-input bg-background h-9 rounded-md border px-3 text-sm"
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {accounts.map((account) => (
          <option key={account.id} value={account.id}>
            {account.number} — {account.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Valeurs de départ (saisie hors connexion reprise pour correction). */
export type GuidedInitial = {
  entryDate: string;
  amount: string;
  natureId: string | null;
  treasuryId: string | null;
  targetId: string | null;
  partyId: string | null;
  vatIncluded: boolean;
  label: string | null;
  reference: string | null;
};

/**
 * Formulaire d'une opération de saisie guidée. L'aperçu montre l'écriture exacte que
 * l'API enregistrera ; fonctionne aussi sans JavaScript (envoi classique). Hors
 * connexion, l'aperçu est masqué (`canPreview`) : l'API calculera l'écriture à la
 * synchronisation.
 */
export function GuidedForm({
  action,
  labels,
  natures,
  treasury,
  target,
  parties,
  vat,
  defaultDate,
  canPost,
  currency,
  locale,
  companyId,
  canPreview = true,
  initial,
  clientId: givenClientId,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  labels: GuidedFormLabels;
  natures: NatureOption[] | null;
  treasury: AccountOption[] | null;
  target: AccountOption[] | null;
  parties: AccountOption[] | null;
  vat: { ratePercent: string; verified: boolean } | null;
  defaultDate: string;
  canPost: boolean;
  currency: string;
  locale: Locale;
  companyId: string;
  canPreview?: boolean;
  initial?: GuidedInitial;
  clientId?: string;
}) {
  const [state, formAction, pending] = useActionState(action, IDLE);
  const [clientId] = useState(() => givenClientId ?? uuidV4());
  const [natureId, setNatureId] = useState(
    initial?.natureId ?? (natures?.length === 1 ? natures[0]?.id ?? "" : ""),
  );
  const selectedNature = natures?.find((n) => n.id === natureId);
  // Sans JavaScript, la case reste proposée dès qu'une nature l'autorise ; l'API tranche.
  const showVat = vat !== null && natures !== null && (selectedNature ? selectedNature.vatPossible : natures.some((n) => n.vatPossible));
  const preview = state.status === "success" ? (state.data?.preview as Preview | undefined) : undefined;
  const draftId = typeof state.data?.entryId === "string" ? state.data.entryId : null;
  const money = (value: string) => (value === "0" ? "" : formatMoney(BigInt(value), currency, locale));

  return (
    <form
      action={formAction}
      className="flex max-w-xl flex-col gap-4"
      onSubmit={(event) => {
        // Envoi manuel : React viderait le formulaire après l'aperçu.
        event.preventDefault();
        const submitter = (event.nativeEvent as SubmitEvent).submitter;
        const data = new FormData(event.currentTarget, submitter);
        startTransition(() => formAction(data));
      }}
    >
      <input type="hidden" name="client_id" value={clientId} />
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="guided-date">{labels.date}</Label>
          <Input id="guided-date" name="entry_date" type="date" defaultValue={initial?.entryDate ?? defaultDate} required />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="guided-amount">{labels.amount}</Label>
          <Input
            id="guided-amount"
            name="amount"
            inputMode="decimal"
            autoComplete="off"
            defaultValue={initial?.amount}
            required
          />
          <p className="text-muted-foreground text-xs">{labels.amountHint}</p>
        </div>
      </div>

      {natures ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="guided-nature">{labels.nature}</Label>
          <select
            id="guided-nature"
            name="nature_account_id"
            required
            value={natureId}
            onChange={(event) => setNatureId(event.target.value)}
            className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          >
            <option value="" disabled>
              {labels.choose}
            </option>
            {natures.map((nature) => (
              <option key={nature.id} value={nature.id}>
                {nature.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {treasury ? (
        <AccountSelect id="guided-treasury" name="treasury_account_id" label={labels.treasury} accounts={treasury} placeholder={labels.choose} initial={initial?.treasuryId} />
      ) : null}
      {target && labels.target ? (
        <AccountSelect id="guided-target" name="target_treasury_account_id" label={labels.target} accounts={target} placeholder={labels.choose} initial={initial?.targetId} />
      ) : null}
      {parties && labels.party ? (
        <AccountSelect id="guided-party" name="party_account_id" label={labels.party} accounts={parties} placeholder={labels.choose} initial={initial?.partyId} />
      ) : null}
      {showVat && vat ? (
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" name="vat_included" className="mt-1" defaultChecked={initial?.vatIncluded} />
          <span>
            {labels.vatIncluded.replace("{rate}", vat.ratePercent)}
            {vat.verified ? null : <span className="text-muted-foreground"> ({labels.vatUnverified})</span>}
          </span>
        </label>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="guided-reference">{labels.reference}</Label>
          <Input id="guided-reference" name="reference" maxLength={60} defaultValue={initial?.reference ?? undefined} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="guided-label">{labels.label}</Label>
          <Input id="guided-label" name="label" maxLength={200} defaultValue={initial?.label ?? undefined} />
          <p className="text-muted-foreground text-xs">{labels.labelHint}</p>
        </div>
      </div>

      {state.status === "error" && state.message ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>
            <p>{state.message}</p>
            {state.errors && state.errors.length > 0 ? (
              <ul className="mt-1 list-disc pl-5">
                {state.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            ) : null}
            {draftId ? (
              <a href={`/dossiers/${companyId}/ecritures/${draftId}`} className="mt-1 block underline underline-offset-4">
                {labels.openDraft}
              </a>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {preview ? (
        <section aria-labelledby="guided-preview-title" className="rounded-md border p-3">
          <h2 id="guided-preview-title" className="font-medium">
            {labels.previewTitle}
          </h2>
          <p className="text-muted-foreground mb-2 text-sm">
            {labels.journal} {preview.journal_code} — {preview.journal_label} · {preview.label}
            {preview.reference ? ` · ${preview.reference}` : ""}
          </p>
          {preview.warnings.map((warning) => (
            <p key={warning} role="note" className="mb-2 text-sm text-amber-700 dark:text-amber-400">
              {warning}
            </p>
          ))}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{labels.account}</TableHead>
                <TableHead className="text-right">{labels.debit}</TableHead>
                <TableHead className="text-right">{labels.credit}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.lines.map((line) => (
                <TableRow key={`${line.account_id}-${line.debit}-${line.credit}`}>
                  <TableCell className="whitespace-normal">
                    <span className="font-mono">{line.account_number}</span> {line.account_label}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.debit)}</TableCell>
                  <TableCell className="text-right whitespace-nowrap tabular-nums">{money(line.credit)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      ) : null}

      <div className="flex flex-wrap gap-3">
        {canPreview ? (
          <Button type="submit" name="intent" value="preview" variant="outline" disabled={pending}>
            {labels.preview}
          </Button>
        ) : null}
        <Button type="submit" name="intent" value="draft" variant={canPost ? "secondary" : "default"} disabled={pending}>
          {pending ? labels.pending : labels.saveDraft}
        </Button>
        {canPost ? (
          <Button type="submit" name="intent" value="post" disabled={pending}>
            {labels.saveAndPost}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

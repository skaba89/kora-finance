"use client";

import { useEffect, useState } from "react";

import { GuidedForm, type GuidedInitial } from "@/components/guided/guided-form";
import { GUIDED_GROUPS, guidedChoices } from "@/components/guided/options";
import { type EditorEntry, type EditorLabels, EntryEditor } from "@/components/ledger/entry-editor";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import type { ActionState } from "@/lib/actions/state";
import { amountInputValue } from "@/lib/amounts";
import { currencyDecimals, formatDate } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { interpolate } from "@/lib/i18n/interpolate";
import type { Dictionary } from "@/lib/i18n/server";
import { isExpired, outsideOpenYears, type QueueItem, type Snapshot } from "@/lib/offline/model";
import { useOfflineSupported, useOnline } from "@/lib/offline/hooks";
import { currentUser, getItem, listItems, listSnapshots, onChange, putItem } from "@/lib/offline/store";
import { type EntryIn, type GuidedIn, guidedBody, type Operation, OPERATIONS, parseEntryJson, UUID } from "@/lib/payloads";

import { QueueList } from "./queue-list";
import { NetworkIndicator } from "./network-indicator";

type Phase = "loading" | "unsupported" | "none" | "ready";
type Mode = "free" | "guided";

const SELECT = "border-input bg-background min-h-11 w-full min-w-0 rounded-md border px-3 text-sm";

function today(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function editorInitial(id: string, payload: EntryIn): EditorEntry {
  return {
    id,
    journal_id: payload.journal_id,
    entry_date: payload.entry_date,
    reference: payload.reference ?? null,
    label: payload.label,
    lines: payload.lines.map((l) => ({ account_id: l.account_id, label: l.label ?? null, debit: l.debit, credit: l.credit })),
  };
}

function guidedInitial(payload: GuidedIn, decimals: number): GuidedInitial {
  return {
    entryDate: payload.entry_date,
    amount: amountInputValue(payload.amount, decimals),
    natureId: payload.nature_account_id ?? null,
    treasuryId: payload.treasury_account_id ?? null,
    targetId: payload.target_treasury_account_id ?? null,
    partyId: payload.party_account_id ?? null,
    vatIncluded: payload.vat_included,
    label: payload.label ?? null,
    reference: payload.reference ?? null,
  };
}

/**
 * Saisie sans réseau : page sans aucune donnée côté serveur (mise en cache par le service
 * worker), qui lit les données du dossier conservées sur l'appareil et range chaque
 * saisie dans la file d'attente. Rien n'est validé ici : la synchronisation crée des
 * brouillons à la prochaine connexion. `?dossier=…&modifier=…` reprend une saisie.
 */
export function OfflineEntry({
  labels,
  guidedLabels,
  editorLabels,
  locale,
}: {
  labels: Dictionary["offline"];
  guidedLabels: Dictionary["guided"];
  editorLabels: EditorLabels;
  locale: Locale;
}) {
  const supported = useOfflineSupported();
  const online = useOnline();
  const [loaded, setLoaded] = useState<"loading" | "none" | "ready">("loading");
  const [userId, setUserId] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const [mode, setMode] = useState<Mode>("free");
  const [operation, setOperation] = useState<Operation>("VENTE_COMPTANT");
  const [editing, setEditing] = useState<QueueItem | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [saved, setSaved] = useState<string[] | null>(null);
  const [formKey, setFormKey] = useState(0);

  useEffect(() => {
    if (!supported) return;
    void (async () => {
      const user = await currentUser();
      const now = new Date();
      const usable = user ? (await listSnapshots(user)).filter((s) => !isExpired(s, now)) : [];
      if (!user || usable.length === 0) {
        setLoaded("none");
        return;
      }
      usable.sort((a, b) => a.companyName.localeCompare(b.companyName));
      const params = new URLSearchParams(window.location.search);
      const wanted = params.get("dossier");
      const chosen = usable.find((s) => s.companyId === wanted) ?? usable[0];
      const editId = params.get("modifier");
      const item = editId && UUID.test(editId) ? await getItem(user, editId) : null;
      setUserId(user);
      setSnapshots(usable);
      setCompanyId(chosen?.companyId ?? "");
      if (item && item.status !== "synced" && item.companyId === chosen?.companyId) {
        setEditing(item);
        setMode(item.kind);
        if (item.kind === "guided") setOperation(item.payload.operation);
      }
      setLoaded("ready");
    })().catch((error: unknown) => {
      console.error("Saisie hors connexion : lecture de l'appareil impossible", error);
      setLoaded("none");
    });
  }, [supported]);

  useEffect(() => {
    if (!userId || !companyId) return;
    const reload = () =>
      void listItems(userId, companyId)
        .then(setItems)
        .catch((error: unknown) => console.error("Lecture de la file impossible", error));
    reload();
    return onChange(reload);
  }, [userId, companyId]);

  const phase: Phase = supported === null ? "loading" : supported ? loaded : "unsupported";

  const snapshot = snapshots.find((s) => s.companyId === companyId);

  const stopEditing = () => {
    setEditing(null);
    window.history.replaceState(null, "", "/hors-connexion/saisie");
  };

  const store = async (
    id: string,
    entry: { kind: "free"; payload: EntryIn } | { kind: "guided"; payload: GuidedIn },
  ): Promise<ActionState> => {
    if (!userId || !snapshot) return { status: "error", message: labels.noCompany };
    const now = new Date().toISOString();
    const previous = editing?.id === id ? editing : null;
    await putItem({
      ...entry,
      id,
      userId,
      companyId: snapshot.companyId,
      createdAt: previous?.createdAt ?? now,
      updatedAt: now,
      status: "pending",
    } as QueueItem);
    const notes = [labels.savedLocal];
    if (outsideOpenYears(entry.payload.entry_date, snapshot.openFiscalYears)) {
      notes.push(interpolate(labels.outsideYear, { date: formatDate(entry.payload.entry_date, locale) }));
    }
    setSaved(notes);
    if (previous) stopEditing();
    setFormKey((k) => k + 1);
    return { status: "success" };
  };

  if (phase === "loading") return <p className="text-muted-foreground text-sm">{labels.loading}</p>;
  if (phase === "unsupported" || phase === "none") {
    return (
      <Alert role="alert">
        <AlertDescription>{phase === "unsupported" ? labels.unsupported : labels.noCompany}</AlertDescription>
      </Alert>
    );
  }
  if (!snapshot) return null;

  const decimals = currencyDecimals(snapshot.currency);
  const choices = mode === "guided" ? guidedChoices(snapshot.guided, operation, guidedLabels, locale) : null;

  const saveFree = async (_: ActionState, formData: FormData): Promise<ActionState> => {
    const payload = parseEntryJson(String(formData.get("payload") ?? ""));
    if (!payload) return { status: "error", message: labels.invalidItem };
    const existing = String(formData.get("entry_id") ?? "");
    const id = UUID.test(existing) ? existing : String(formData.get("client_id") ?? "");
    if (!UUID.test(id)) return { status: "error", message: labels.invalidItem };
    return store(id, { kind: "free", payload });
  };

  const saveGuided = async (_: ActionState, formData: FormData): Promise<ActionState> => {
    const parsed = guidedBody(formData, operation, decimals);
    if ("error" in parsed) {
      return { status: "error", message: parsed.error === "amount" ? guidedLabels.invalidAmount : guidedLabels.invalidDate };
    }
    const id = String(formData.get("client_id") ?? "");
    if (!UUID.test(id)) return { status: "error", message: labels.invalidItem };
    return store(id, { kind: "guided", payload: parsed.body });
  };

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <NetworkIndicator online={online} labels={labels} />
      {online ? (
        <Alert role="status">
          <AlertDescription>
            {labels.online}{" "}
            <a href={`/dossiers/${snapshot.companyId}/hors-connexion`} className="underline underline-offset-4">
              {labels.goSync}
            </a>
          </AlertDescription>
        </Alert>
      ) : null}
      <p className="rounded-lg border bg-info/5 p-3 text-info text-sm">{labels.draftOnly}</p>

      <div className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="hors-ligne-dossier">{labels.company}</Label>
          <select
            id="hors-ligne-dossier"
            className={SELECT}
            value={companyId}
            disabled={editing !== null}
            onChange={(e) => {
              setCompanyId(e.target.value);
              setSaved(null);
            }}
          >
            {snapshots.map((s) => (
              <option key={s.companyId} value={s.companyId}>
                {s.companyName}
              </option>
            ))}
          </select>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="hors-ligne-type">{labels.mode}</Label>
          <select
            id="hors-ligne-type"
            className={SELECT}
            value={mode}
            disabled={editing !== null}
            onChange={(e) => {
              setMode(e.target.value === "guided" ? "guided" : "free");
              setSaved(null);
            }}
          >
            <option value="free">{labels.kind.free}</option>
            <option value="guided">{labels.kind.guided}</option>
          </select>
        </div>
        {mode === "guided" ? (
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="hors-ligne-operation">{labels.operation}</Label>
            <select
              id="hors-ligne-operation"
              className={SELECT}
              value={operation}
              disabled={editing !== null}
              onChange={(e) => {
                const value = e.target.value as Operation;
                if (OPERATIONS.includes(value)) setOperation(value);
                setSaved(null);
              }}
            >
              {GUIDED_GROUPS.map((group) => (
                <optgroup key={group.key} label={guidedLabels.groups[group.key]}>
                  {group.operations.map((code) => (
                    <option key={code} value={code}>
                      {guidedLabels.operations[code].title}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      {editing ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <p className="font-medium">{labels.editing}</p>
          <button type="button" className="underline underline-offset-4" onClick={stopEditing}>
            {labels.cancelEdit}
          </button>
        </div>
      ) : null}
      {editing?.status === "rejected" && editing.message ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{editing.message}</AlertDescription>
        </Alert>
      ) : null}
      {saved ? (
        <Alert role="status">
          <AlertDescription>
            {saved.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </AlertDescription>
        </Alert>
      ) : null}

      {mode === "free" ? (
        <EntryEditor
          key={`free-${companyId}-${formKey}-${editing?.id ?? ""}`}
          action={saveFree}
          journals={snapshot.journals}
          accounts={snapshot.accounts}
          initial={editing?.kind === "free" ? editorInitial(editing.id, editing.payload) : undefined}
          defaultDate={today()}
          currency={snapshot.currency}
          decimals={decimals}
          locale={locale}
          canPost={false}
          labels={{ ...editorLabels, saveDraft: labels.saveLocal }}
        />
      ) : choices?.missing ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{interpolate(guidedLabels.noAccount, { what: choices.missing })}</AlertDescription>
        </Alert>
      ) : choices ? (
        <>
          <p className="text-muted-foreground text-sm">{labels.vatAtSync}</p>
          <GuidedForm
            key={`guided-${companyId}-${operation}-${formKey}-${editing?.id ?? ""}`}
            action={saveGuided}
            labels={{ ...choices.labels, saveDraft: labels.saveLocal }}
            natures={choices.natures}
            treasury={choices.treasury}
            target={choices.target}
            parties={choices.parties}
            vat={choices.vat}
            defaultDate={today()}
            canPost={false}
            canPreview={false}
            currency={snapshot.currency}
            locale={locale}
            companyId={snapshot.companyId}
            initial={editing?.kind === "guided" ? guidedInitial(editing.payload, decimals) : undefined}
            clientId={editing?.id}
          />
        </>
      ) : null}

      <section aria-labelledby="hors-ligne-file" className="flex flex-col gap-3">
        <h2 id="hors-ligne-file" className="font-medium">
          {labels.queueTitle}
        </h2>
        <QueueList items={items} currency={snapshot.currency} locale={locale} labels={labels} online={online} />
      </section>
    </div>
  );
}

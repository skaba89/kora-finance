"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Inbox } from "lucide-react";
import { formatDate, formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import type { Dictionary } from "@/lib/i18n/server";
import { itemAmount, itemDate, itemLabel, type QueueItem } from "@/lib/offline/model";
import { deleteItem, putItem } from "@/lib/offline/store";
import { cn } from "@/lib/utils";

/**
 * Saisies faites hors connexion pour un dossier : statut, refus du serveur, actions.
 * `onRetry` relance la synchronisation (en ligne) après remise en attente.
 */
export function QueueList({
  items,
  currency,
  locale,
  labels,
  onRetry,
  online,
}: {
  items: QueueItem[];
  currency: string;
  locale: Locale;
  labels: Dictionary["offline"];
  onRetry?: () => void;
  online: boolean;
}) {
  const statuses = ["pending", "rejected", "synced"] as const;
  const tones = { pending: "bg-warning/10 text-warning", rejected: "bg-destructive/10 text-destructive", synced: "bg-success/10 text-success" };
  return (
    <div className="space-y-4">
      <dl aria-label={labels.queueSummary} className="grid grid-cols-3 gap-2" data-testid="offline-summary">
        {statuses.map((status) => (
          <div key={status} className="min-w-0 rounded-xl border bg-card p-3">
            <dt className="text-muted-foreground break-words text-xs">{labels.status[status]}</dt>
            <dd className={cn("mt-1 text-xl font-semibold tabular-nums", status === "pending" ? "text-warning" : status === "rejected" ? "text-destructive" : "text-success")}>
              {items.filter((item) => item.status === status).length}
            </dd>
          </div>
        ))}
      </dl>
      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          <Inbox aria-hidden="true" className="size-6" />
          <p>{labels.queueEmpty}</p>
        </div>
      ) : (
    <ul className="flex flex-col gap-2" aria-label={labels.queueTitle}>
      {items.map((item) => (
        <li key={item.id} className="min-w-0 rounded-xl border bg-card p-4 text-sm" aria-label={`${itemLabel(item)} — ${labels.status[item.status]}`}>
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="min-w-0 break-words font-medium">
              {formatDate(itemDate(item), locale)} · {itemLabel(item) || labels.kind[item.kind]}
            </p>
            <p className="break-all text-right font-semibold tabular-nums">{formatMoney(itemAmount(item), currency, locale)}</p>
          </div>
          <p className="text-muted-foreground">
            {labels.kind[item.kind]} ·{" "}
            <Badge variant="outline" className={cn("border-transparent", tones[item.status])}>
              {labels.status[item.status]}
            </Badge>
          </p>
          {item.status === "rejected" && item.message ? (
            <div role="alert" className="text-destructive mt-2 break-words rounded-lg bg-destructive/5 p-3">
              <p>{item.message}</p>
              {item.errors && item.errors.length > 0 ? (
                <ul className="list-disc pl-5">
                  {item.errors.map((error) => (
                    <li key={error}>{error}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2">
            {item.status === "synced" && item.entryId && online ? (
              <a href={`/dossiers/${item.companyId}/ecritures/${item.entryId}`} className="inline-flex min-h-11 items-center rounded-md px-2 text-primary underline underline-offset-4">
                {labels.openDraft}
              </a>
            ) : null}
            {item.status !== "synced" ? (
              <a
                href={`/hors-connexion/saisie?dossier=${item.companyId}&modifier=${item.id}`}
                className="inline-flex min-h-11 items-center rounded-md px-2 text-primary underline underline-offset-4"
              >
                {labels.edit}
              </a>
            ) : null}
            {item.status === "rejected" && onRetry ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="min-h-11"
                onClick={() => {
                  void putItem({ ...item, status: "pending", message: undefined, errors: undefined }).then(onRetry);
                }}
              >
                {labels.retryItem}
              </Button>
            ) : null}
            {item.status !== "synced" ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="min-h-11"
                onClick={() => {
                  if (window.confirm(labels.deleteConfirm)) void deleteItem(item.id);
                }}
              >
                {labels.delete}
              </Button>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
      )}
    </div>
  );
}

"use client";

import { Button } from "@/components/ui/button";
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
  if (items.length === 0) return <p className="text-muted-foreground text-sm">{labels.queueEmpty}</p>;
  return (
    <ul className="flex flex-col gap-2" aria-label={labels.queueTitle}>
      {items.map((item) => (
        <li key={item.id} className="rounded-md border p-3 text-sm" aria-label={`${itemLabel(item)} — ${labels.status[item.status]}`}>
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="font-medium">
              {formatDate(itemDate(item), locale)} · {itemLabel(item) || labels.kind[item.kind]}
            </p>
            <p className="tabular-nums">{formatMoney(itemAmount(item), currency, locale)}</p>
          </div>
          <p className="text-muted-foreground">
            {labels.kind[item.kind]} ·{" "}
            <span
              className={cn(
                item.status === "rejected" && "text-destructive font-medium",
                item.status === "synced" && "text-emerald-700",
              )}
            >
              {labels.status[item.status]}
            </span>
          </p>
          {item.status === "rejected" && item.message ? (
            <div role="alert" className="text-destructive mt-1">
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
              <a href={`/dossiers/${item.companyId}/ecritures/${item.entryId}`} className="underline underline-offset-4">
                {labels.openDraft}
              </a>
            ) : null}
            {item.status !== "synced" ? (
              <a
                href={`/hors-connexion/saisie?dossier=${item.companyId}&modifier=${item.id}`}
                className="underline underline-offset-4"
              >
                {labels.edit}
              </a>
            ) : null}
            {item.status === "rejected" && onRetry ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
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
  );
}

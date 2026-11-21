"use client";

import { useCallback, useEffect, useState, useTransition } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { prepareOfflineAction } from "@/lib/actions/offline";
import { formatDate, formatDateTime } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { interpolate } from "@/lib/i18n/interpolate";
import type { Dictionary } from "@/lib/i18n/server";
import { useOfflineSupported, useOnline } from "@/lib/offline/hooks";
import { isExpired, type QueueItem, type Snapshot } from "@/lib/offline/model";
import {
  deleteSnapshot,
  getSnapshot,
  listItems,
  onChange,
  saveSnapshot,
  setCurrentUser,
} from "@/lib/offline/store";
import { syncPending } from "@/lib/offline/sync";

import { sendItem } from "./offline-sync";
import { QueueList } from "./queue-list";
import { NetworkIndicator } from "./network-indicator";

type Message = { tone: "info" | "error"; text: string };

/**
 * Page « Hors connexion » d'un dossier : préparer l'appareil (données du dossier
 * conservées, chiffrées, 7 jours), suivre et synchroniser les saisies faites sans réseau.
 */
export function DevicePanel({
  companyId,
  userId,
  currency,
  locale,
  labels,
}: {
  companyId: string;
  userId: string;
  currency: string;
  locale: Locale;
  labels: Dictionary["offline"];
}) {
  const supported = useOfflineSupported();
  const online = useOnline();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [message, setMessage] = useState<Message | null>(null);
  const [preparing, startPreparing] = useTransition();
  const [syncing, startSyncing] = useTransition();

  const load = useCallback(async () => {
    const [nextSnapshot, nextItems] = await Promise.all([getSnapshot(userId, companyId), listItems(userId, companyId)]);
    setSnapshot(nextSnapshot);
    setItems(nextItems);
  }, [userId, companyId]);

  useEffect(() => {
    if (!supported) return;
    const reload = () => void load().catch((error: unknown) => console.error("Lecture de l'appareil impossible", error));
    void setCurrentUser(userId).then(reload);
    return onChange(reload);
  }, [supported, userId, load]);

  const prepare = () =>
    startPreparing(async () => {
      const result = await prepareOfflineAction(companyId);
      const prepared = result.data?.snapshot as Snapshot | undefined;
      if (result.status !== "success" || !prepared) {
        setMessage({ tone: "error", text: result.message ?? labels.notAllowed });
        return;
      }
      await saveSnapshot(prepared);
      setMessage(null);
    });

  const sync = () =>
    startSyncing(async () => {
      const report = await syncPending(userId, sendItem);
      const parts = [interpolate(labels.syncDone, { n: report.synced })];
      if (report.rejected > 0) parts.push(interpolate(labels.syncRejected, { n: report.rejected }));
      if (report.stopped === "auth") parts.push(labels.needLogin);
      if (report.stopped === "offline") parts.push(labels.stillOffline);
      setMessage({ tone: report.stopped || report.rejected > 0 ? "error" : "info", text: parts.join(" ") });
      await load();
    });

  if (supported === null) return <p className="text-muted-foreground text-sm">{labels.loading}</p>;
  if (!supported) {
    return (
      <Alert role="alert">
        <AlertDescription>{labels.unsupported}</AlertDescription>
      </Alert>
    );
  }

  const expired = snapshot ? isExpired(snapshot, new Date()) : false;
  const hasPending = items.some((i) => i.status === "pending");

  return (
    <div className="flex min-w-0 max-w-5xl flex-col gap-6">
      <NetworkIndicator online={online} labels={labels} />
      <section aria-labelledby="offline-device" className="flex flex-col gap-4 rounded-xl border bg-card p-4 sm:p-6">
        <h2 id="offline-device" className="font-medium">
          {labels.deviceTitle}
        </h2>
        <p role="status" className={`rounded-lg p-3 text-sm ${snapshot && !expired ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`} data-testid="etat-appareil">
          {!snapshot
            ? labels.notPrepared
            : expired
              ? interpolate(labels.expired, { date: formatDate(snapshot.expiresAt.slice(0, 10), locale) })
              : interpolate(labels.preparedUntil, {
                  fetched: formatDateTime(snapshot.fetchedAt, locale),
                  until: formatDate(snapshot.expiresAt.slice(0, 10), locale),
                })}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button type="button" className="min-h-11 whitespace-normal" onClick={prepare} disabled={preparing || !online}>
            {preparing ? labels.preparing : snapshot ? labels.update : labels.prepare}
          </Button>
          {snapshot && !expired ? (
            // Navigation complète (pas de <Link>) : hors connexion, seul le service worker
            // peut servir cette page ; une navigation client de Next échouerait.
            <a
              href={`/hors-connexion/saisie?dossier=${companyId}`}
              className="border-input hover:bg-muted inline-flex min-h-11 items-center rounded-md border px-3 py-2 text-sm"
            >
              {labels.open}
            </a>
          ) : null}
          {snapshot ? (
            <Button type="button" variant="ghost" className="min-h-11 h-auto whitespace-normal" onClick={() => void deleteSnapshot(userId, companyId)}>
              {labels.remove}
            </Button>
          ) : null}
        </div>
        <p className="text-muted-foreground text-sm">{labels.securityNote}</p>
      </section>

      <section aria-labelledby="offline-queue" className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="offline-queue" className="font-medium">
            {labels.queueTitle}
          </h2>
          {hasPending ? (
            <Button type="button" variant="outline" size="sm" onClick={sync} disabled={syncing || !online}>
              {syncing ? labels.syncing : labels.sync}
            </Button>
          ) : null}
        </div>
        {message ? (
          <Alert variant={message.tone === "error" ? "destructive" : "default"} role="status">
            <AlertDescription>{message.text}</AlertDescription>
          </Alert>
        ) : null}
        <QueueList items={items} currency={currency} locale={locale} labels={labels} onRetry={sync} online={online} />
      </section>
    </div>
  );
}

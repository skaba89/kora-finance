import { FileText, ImageIcon } from "lucide-react";

import { InlineAction } from "@/components/forms/inline-action";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { removeAttachmentAction, uploadAttachmentAction } from "@/lib/actions/attachments";
import { formatSize } from "@/lib/attachments";
import { getAttachments } from "@/lib/dal";
import { formatDateTime } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { interpolate } from "@/lib/i18n/interpolate";
import type { Dictionary } from "@/lib/i18n/server";

import { UploadForm } from "./upload-form";

/** Pièces d'une écriture : liste, consultation, ajout et retrait (brouillon seulement). */
export async function AttachmentsSection({
  companyId,
  entryId,
  posted,
  canWrite,
  t,
  locale,
}: {
  companyId: string;
  entryId: string;
  posted: boolean;
  canWrite: boolean;
  t: Dictionary;
  locale: Locale;
}) {
  const attachments = await getAttachments(companyId, entryId);
  const href = (id: string) => `/dossiers/${companyId}/pieces/${id}`;

  return (
    <Card className="mt-8" role="region" aria-labelledby="attachments-title">
      <CardHeader>
        <CardTitle id="attachments-title" className="text-base">
          {t.attachments.title}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {posted && attachments.length > 0 ? (
          <p className="text-muted-foreground text-sm">{t.attachments.keptNotice}</p>
        ) : null}
        {attachments.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t.attachments.empty}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {attachments.map((attachment) => {
              const Icon = attachment.content_type === "application/pdf" ? FileText : ImageIcon;
              return (
                <li key={attachment.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
                  <Icon aria-hidden className="text-muted-foreground size-5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium break-all">{attachment.filename}</p>
                    <p className="text-muted-foreground text-xs">
                      {formatSize(attachment.size_bytes, locale)} ·{" "}
                      {interpolate(t.attachments.addedOn, { date: formatDateTime(attachment.created_at, locale) })}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <a
                      href={href(attachment.id)}
                      target="_blank"
                      rel="noopener"
                      className="underline underline-offset-4"
                      aria-label={`${t.attachments.open} ${attachment.filename}`}
                    >
                      {t.attachments.open}
                    </a>
                    <a
                      href={`${href(attachment.id)}?telecharger=1`}
                      download={attachment.filename}
                      className="underline underline-offset-4"
                      aria-label={`${t.attachments.download} ${attachment.filename}`}
                    >
                      {t.attachments.download}
                    </a>
                    {canWrite && !posted ? (
                      <InlineAction
                        action={removeAttachmentAction.bind(null, companyId, attachment.id)}
                        label={t.attachments.remove}
                        pendingLabel={t.common.pending}
                        variant="ghost"
                        confirm={t.attachments.removeConfirm}
                      />
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {canWrite ? (
          <UploadForm
            action={uploadAttachmentAction.bind(null, companyId, entryId)}
            labels={{
              file: t.attachments.file,
              hint: t.attachments.hint,
              submit: t.attachments.submit,
              pending: t.attachments.pending,
              preparing: t.attachments.preparing,
              tooLarge: t.attachments.tooLarge,
            }}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

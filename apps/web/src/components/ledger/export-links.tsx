import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type ExportKind, exportHref } from "@/lib/exports";

/** Boutons de téléchargement PDF / Excel (liens simples : fonctionnent sans JavaScript). */
export function ExportLinks({
  companyId,
  kind,
  fiscalYearId,
  dateFrom,
  dateTo,
  accountId,
  label,
}: {
  companyId: string;
  kind: ExportKind;
  fiscalYearId: string;
  dateFrom?: string;
  dateTo?: string;
  accountId?: string;
  label: string;
}) {
  const params = { fiscalYearId, dateFrom, dateTo, accountId };
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      {(["pdf", "xlsx"] as const).map((format) => (
        <Button key={format} asChild variant="outline" size="sm">
          <a href={exportHref(companyId, kind, format, params)} download>
            <Download aria-hidden className="size-4" />
            {format === "pdf" ? "PDF" : "Excel"}
          </a>
        </Button>
      ))}
    </div>
  );
}

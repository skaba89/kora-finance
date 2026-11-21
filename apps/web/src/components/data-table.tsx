import type { ReactNode } from "react";
import { Table } from "@/components/ui/table";
import type { TableDensity } from "@/lib/table-preferences";
import { cn } from "@/lib/utils";

/** Table sémantique : contenu et pagination restent sous le contrôle du serveur. */
export function DataTable({ children, label, density = "comfortable" }: {
  children: ReactNode; label: string; density?: TableDensity;
}) {
  return (
    <Table aria-label={label} containerProps={{
      role: "region", "aria-label": label, tabIndex: 0,
      className: "max-h-[65vh] min-w-0 overflow-auto rounded-xl border bg-card",
    }} className={cn("[&_th]:sticky [&_th]:top-0 [&_th]:z-10 [&_th]:bg-muted [&_th]:px-3 [&_td]:px-3 [&_td]:align-middle", density === "compact" ? "[&_td]:py-1.5" : "[&_td]:py-3")}>
      {children}
    </Table>
  );
}

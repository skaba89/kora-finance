import type { TableDensity } from "@/lib/table-preferences";

export function TableDensitySelect({ density, labels }: { density: TableDensity; labels: { density: string; comfortable: string; compact: string } }) {
  return <select name="densite" defaultValue={density} aria-label={labels.density} className="border-input bg-background min-h-11 rounded-lg border px-3 text-sm">
    <option value="comfortable">{labels.comfortable}</option>
    <option value="compact">{labels.compact}</option>
  </select>;
}

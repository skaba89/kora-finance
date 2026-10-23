import type { ApiHealth } from "@/lib/api/health";

const LABELS: Record<ApiHealth, { text: string; className: string }> = {
  operationnelle: { text: "Opérationnelle", className: "bg-emerald-100 text-emerald-900" },
  degradee: { text: "Dégradée", className: "bg-amber-100 text-amber-900" },
  injoignable: { text: "Injoignable", className: "bg-red-100 text-red-900" },
};

export function ApiStatusBadge({ health }: { health: ApiHealth }) {
  const { text, className } = LABELS[health];
  return (
    <span
      role="status"
      data-health={health}
      className={`inline-flex rounded-md px-2 py-1 text-sm font-medium ${className}`}
    >
      {text}
    </span>
  );
}

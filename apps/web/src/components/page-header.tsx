import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="text-muted-foreground mt-1 max-w-2xl text-sm">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="flex animate-pulse flex-col gap-3" aria-hidden>
      <div className="bg-muted h-7 w-48 rounded" />
      <div className="bg-muted h-4 w-80 max-w-full rounded" />
      <div className="bg-muted mt-4 h-40 rounded" />
    </div>
  );
}

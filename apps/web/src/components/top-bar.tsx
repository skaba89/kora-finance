import Link from "next/link";
import { LayoutGrid } from "lucide-react";

/** Structure commune des pages connectées ; les slots de session restent serveur. */
export function TopBar({ appName, companiesLabel, children }: { appName: string; companiesLabel: string; children: React.ReactNode }) {
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex w-full max-w-[1536px] flex-col gap-1 px-4 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6 sm:gap-y-2 sm:py-3 lg:px-8">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 sm:justify-start sm:gap-5">
          <Link href="/dossiers" className="text-primary text-base font-semibold tracking-tight">{appName}</Link>
          <Link href="/dossiers?liste=1" className="text-muted-foreground hover:text-foreground hover:bg-accent flex min-h-11 items-center gap-2 rounded-lg px-2 text-sm">
            <LayoutGrid aria-hidden className="size-4 shrink-0" />{companiesLabel}
          </Link>
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-1 sm:justify-start sm:gap-4">{children}</div>
      </div>
    </header>
  );
}

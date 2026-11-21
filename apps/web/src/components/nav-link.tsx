"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

const subscribe = () => () => {};

/**
 * Lien de navigation surligné quand il correspond à la page courante. Le chemin est
 * lu côté navigateur après hydratation (l'URL visible diffère du chemin réécrit par
 * le proxy de langue).
 */
export function NavLink({ href, exact, children, onNavigate }: { href: string; exact?: boolean; children: React.ReactNode; onNavigate?: () => void }) {
  const routedPath = usePathname();
  const pathname = useSyncExternalStore(
    subscribe,
    () => routedPath ? window.location.pathname : null,
    () => null,
  );
  const active = pathname !== null && (exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`));
  return (
    <Link
      href={href}
      onNavigate={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "hover:bg-accent flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm transition-colors",
        active ? "bg-accent text-accent-foreground font-semibold" : "text-muted-foreground",
      )}
    >
      {children}
    </Link>
  );
}

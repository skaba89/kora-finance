"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

const subscribe = () => () => {};

/**
 * Lien de navigation surligné quand il correspond à la page courante. Le chemin est
 * lu côté navigateur après hydratation (l'URL visible diffère du chemin réécrit par
 * le proxy de langue).
 */
export function NavLink({ href, exact, children }: { href: string; exact?: boolean; children: React.ReactNode }) {
  const pathname = useSyncExternalStore(
    subscribe,
    () => window.location.pathname,
    () => null,
  );
  const active = pathname !== null && (exact ? pathname === href : pathname.startsWith(href));
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "hover:bg-muted rounded-md px-3 py-2 text-sm",
        active ? "bg-muted font-medium" : "text-muted-foreground",
      )}
    >
      {children}
    </Link>
  );
}

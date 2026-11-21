"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeftRight, BookOpen, Building2, CalendarDays, ChartColumn, ClipboardList, FileText, LayoutDashboard, Receipt, Search, ShieldCheck, ShoppingCart, Users, Wallet, WifiOff } from "lucide-react";

import { NavLink } from "@/components/nav-link";
import { filterNavigation, type NavigationGroup } from "@/lib/company-navigation";

const icons = { dashboard: LayoutDashboard, sales: Receipt, purchases: ShoppingCart, partners: Users, treasury: Wallet, forecast: ChartColumn, guided: FileText, entries: ClipboardList, balance: ChartColumn, ledger: BookOpen, lettering: ArrowLeftRight, statements: ChartColumn, company: Building2, calendar: CalendarDays, taxes: Receipt, audit: ShieldCheck, offline: WifiOff, switch: ArrowLeftRight };

export function CompanyNavigation({ groups, searchLabel, emptyLabel }: { groups: NavigationGroup[]; searchLabel: string; emptyLabel: string }) {
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const filtered = filterNavigation(groups, query);
  return (
    <>
      <div className="relative mb-3">
        <Search aria-hidden className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2" />
        <input ref={input} type="search" aria-label={searchLabel} placeholder={searchLabel} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Escape") setQuery(""); }} className="border-input bg-background h-10 w-full rounded-lg border pl-9 pr-2 text-sm" />
      </div>
      <div className="-mx-4 flex gap-2 overflow-x-auto border-b px-4 pb-2 whitespace-nowrap md:mx-0 md:flex-col md:overflow-visible md:border-0 md:px-0 md:pb-0">
        {filtered.map((group, index) => (
          <div key={`${index}-${group.label}`} className="flex gap-1 md:flex-col">
            {group.label && <p className="text-muted-foreground mt-2 hidden px-3 text-xs font-semibold uppercase tracking-wide md:block">{group.label}</p>}
            {group.items.map(item => {
              const Icon = icons[item.icon as keyof typeof icons] ?? FileText;
              return <NavLink key={item.href} href={item.href} exact={item.exact} onNavigate={() => setQuery("")}><Icon aria-hidden className="size-4 shrink-0" />{item.label}</NavLink>;
            })}
          </div>
        ))}
        {filtered.length === 0 && <p role="status" className="text-muted-foreground px-3 py-2 text-sm">{emptyLabel}</p>}
      </div>
    </>
  );
}

"use client";

import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ArrowLeftRight, BookOpen, Building2, CalendarDays, ChartColumn, ClipboardList, FileText, LayoutDashboard, Menu, PanelLeftClose, PanelLeftOpen, Receipt, Search, ShieldCheck, ShoppingCart, Users, Wallet, WifiOff, X } from "lucide-react";

import { NavLink } from "@/components/nav-link";
import { filterNavigation, type NavigationGroup } from "@/lib/company-navigation";

const icons = { dashboard: LayoutDashboard, sales: Receipt, purchases: ShoppingCart, partners: Users, treasury: Wallet, forecast: ChartColumn, guided: FileText, entries: ClipboardList, balance: ChartColumn, ledger: BookOpen, lettering: ArrowLeftRight, statements: ChartColumn, company: Building2, calendar: CalendarDays, taxes: Receipt, audit: ShieldCheck, offline: WifiOff, switch: ArrowLeftRight };

type Labels = { mainMenu: string; searchModules: string; noModules: string; expandSidebar: string; collapseSidebar: string; openMenu: string; closeMenu: string };

export function CompanyNavigation({ groups, labels, header }: { groups: NavigationGroup[]; labels: Labels; header: React.ReactNode }) {
  const [query, setQuery] = useState("");
  const [compact, setCompact] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(true);
  const menuId = useId();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        flushSync(() => { setCompact(false); setMobileOpen(true); });
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const filtered = filterNavigation(groups, query);
  return (
    <nav aria-label={labels.mainMenu} className="company-navigation" data-compact={compact} data-mobile-open={mobileOpen}>
      <div className="flex min-w-0 items-start gap-1">
        <div className="company-navigation-header min-w-0 flex-1">{header}</div>
        <button type="button" className="hover:bg-accent hidden size-10 shrink-0 items-center justify-center rounded-lg md:flex" aria-label={compact ? labels.expandSidebar : labels.collapseSidebar} title={compact ? labels.expandSidebar : labels.collapseSidebar} aria-pressed={compact} onClick={() => { setCompact(!compact); setQuery(""); }}>
          {compact ? <PanelLeftOpen aria-hidden className="size-5" /> : <PanelLeftClose aria-hidden className="size-5" />}
        </button>
        <button type="button" className="hover:bg-accent flex size-11 shrink-0 items-center justify-center rounded-lg md:hidden" aria-label={mobileOpen ? labels.closeMenu : labels.openMenu} aria-expanded={mobileOpen} aria-controls={menuId} onClick={() => { setMobileOpen(!mobileOpen); setQuery(""); }}>
          {mobileOpen ? <X aria-hidden className="size-5" /> : <Menu aria-hidden className="size-5" />}
        </button>
      </div>
      <div id={menuId} className="company-navigation-content">
      <div className="company-navigation-search relative mb-3">
        <Search aria-hidden className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2" />
        <input ref={input} type="search" aria-label={labels.searchModules} placeholder={labels.searchModules} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Escape") setQuery(""); }} className="border-input bg-background h-10 w-full rounded-lg border pl-9 pr-2 text-sm" />
      </div>
      <div className="-mx-4 flex gap-2 overflow-x-auto border-b px-4 pb-2 whitespace-nowrap md:mx-0 md:flex-col md:overflow-visible md:border-0 md:px-0 md:pb-0">
        {filtered.map((group, index) => (
          <div key={`${index}-${group.label}`} className="flex gap-1 md:flex-col">
            {group.label && <p className="company-navigation-group text-muted-foreground mt-2 hidden px-3 text-xs font-semibold uppercase tracking-wide md:block">{group.label}</p>}
            {group.items.map(item => {
              const Icon = icons[item.icon as keyof typeof icons] ?? FileText;
              return <NavLink key={item.href} href={item.href} exact={item.exact} title={item.label} onNavigate={() => setQuery("")}><Icon aria-hidden className="size-4 shrink-0" /><span className="company-navigation-label">{item.label}</span></NavLink>;
            })}
          </div>
        ))}
        {filtered.length === 0 && <p role="status" className="text-muted-foreground px-3 py-2 text-sm">{labels.noModules}</p>}
      </div>
      </div>
    </nav>
  );
}

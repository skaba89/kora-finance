import type { fr } from "@/lib/i18n/fr";

type Labels = typeof fr.nav;
type Item = { href: string; label: string; icon: string; exact?: boolean };
export type NavigationGroup = { label: string; items: Item[] };

/** Seuls les liens autorisés côté serveur sont transmis au navigateur. */
export function companyNavigation(base: string, t: Labels, allowed: (permission: string) => boolean): NavigationGroup[] {
  const item = (path: string, label: string, icon: string, permission: string, exact = false) => ({
    href: `${base}/${path}`, label, icon, permission, exact,
  });
  const groups = [
    { label: t.management, items: [
      item("ventes", t.sales, "sales", "sales:read"),
      item("achats", t.purchases, "purchases", "purchases:read"),
      item("tiers", t.partners, "partners", "partners:read"),
      item("tresorerie", t.treasury, "treasury", "treasury:read", true),
      item("tresorerie/previsions", t.forecast, "forecast", "treasury:read"),
    ] },
    { label: t.accounting, items: [
      item("saisie-guidee", t.guided, "guided", "entries:write"),
      item("ecritures", t.entries, "entries", "entries:read"),
      item("balance", t.balance, "balance", "entries:read"),
      item("grand-livre", t.ledger, "ledger", "entries:read"),
      item("lettrage", t.lettering, "lettering", "entries:read"),
      item("etats-financiers", t.statements, "statements", "entries:read"),
    ] },
    { label: t.settings, items: [
      item("parametres/entreprise", t.company, "company", "company:read"),
      item("parametres/exercices", t.fiscalYears, "calendar", "fiscal_years:read"),
      item("parametres/plan-comptable", t.chart, "ledger", "accounts:read"),
      item("parametres/journaux", t.journals, "entries", "entries:read"),
      item("parametres/taxes", t.taxes, "taxes", "taxes:read"),
      item("parametres/utilisateurs", t.members, "partners", "members:read"),
      item("journal-audit", t.audit, "audit", "audit:read"),
      item("hors-connexion", t.offline, "offline", "entries:write"),
    ] },
  ];
  return [
    { label: "", items: [{ href: base, label: t.dashboard, icon: "dashboard", exact: true }] },
    ...groups.map(group => ({ label: group.label, items: group.items.filter(i => allowed(i.permission)).map(({ href, label, icon, exact }) => ({ href, label, icon, exact })) })).filter(group => group.items.length > 0),
    { label: "", items: [{ href: "/dossiers?liste=1", label: t.switchCompany, icon: "switch", exact: true }] },
  ];
}

const normalize = (value: string) => value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();

export function filterNavigation(groups: NavigationGroup[], query: string): NavigationGroup[] {
  const term = normalize(query);
  if (!term) return groups;
  return groups.map(group => ({ ...group, items: group.items.filter(item => normalize(`${group.label} ${item.label}`).includes(term)) })).filter(group => group.items.length > 0);
}

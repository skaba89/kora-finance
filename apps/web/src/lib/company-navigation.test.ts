import { describe, expect, it } from "vitest";

import { companyNavigation, filterNavigation } from "./company-navigation";
import { fr } from "./i18n/fr";
import { en } from "./i18n/en";

const base = "/dossiers/test";

describe("navigation des dossiers", () => {
  it("conserve tous les 21 liens distincts pour un rôle autorisé", () => {
    const links = companyNavigation(base, fr.nav, () => true).flatMap(g => g.items);
    expect(links).toHaveLength(21);
    expect(new Set(links.map(i => i.href)).size).toBe(21);
  });
  it("ne transmet aucun lien métier non autorisé et masque les groupes vides", () => {
    const groups = companyNavigation(base, fr.nav, p => p === "sales:read");
    expect(groups.flatMap(g => g.items).map(i => i.href)).toEqual([base, `${base}/ventes`, "/dossiers?liste=1"]);
    expect(groups.map(g => g.label)).not.toContain(fr.nav.accounting);
    expect(filterNavigation(groups, "saisie")).toEqual([]);
  });
  it("recherche avec casse et accents indépendants en français et anglais", () => {
    const groups = companyNavigation(base, fr.nav, () => true);
    expect(filterNavigation(groups, " ECRITURES ").flatMap(g => g.items).map(i => i.href)).toEqual([`${base}/ecritures`]);
    expect(filterNavigation(companyNavigation(base, en.nav, () => true), "forecast").flatMap(g => g.items)[0]?.href).toBe(`${base}/tresorerie/previsions`);
    expect(filterNavigation(groups, "" )).toEqual(groups);
  });
});

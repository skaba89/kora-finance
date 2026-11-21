import { describe, expect, it } from "vitest";
import { tablePreferences, tableRange } from "./table-preferences";

describe("préférences de tableau", () => {
  it("conserve le défaut historique", () => {
    expect(tablePreferences({})).toEqual({ size: 50, page: 1, density: "comfortable", offset: 0 });
  });
  it("calcule le décalage serveur selon la taille choisie", () => {
    expect(tablePreferences({ taille: "25", page: "3", densite: "compact" })).toEqual({ size: 25, page: 3, density: "compact", offset: 50 });
  });
  it("ignore les préférences invalides et les offsets non sûrs", () => {
    for (const page of ["-1", "2.5", "1e9", "9007199254740991", "abc"]) {
      expect(tablePreferences({ taille: "999", page, densite: "unknown" })).toEqual({ size: 50, page: 1, density: "comfortable", offset: 0 });
    }
  });
  it("affiche des bornes cohérentes, même en dehors de la dernière page", () => {
    expect(tableRange(51, 50, 1, 25)).toEqual({ from: 51, to: 51, lastPage: 3 });
    expect(tableRange(2, 50, 0, 25)).toEqual({ from: 0, to: 0, lastPage: 1 });
  });
});

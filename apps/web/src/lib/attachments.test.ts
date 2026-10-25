import { describe, expect, it } from "vitest";

import { fitWithin, formatSize, shouldShrink, shrunkName } from "./attachments";

describe("pièces justificatives", () => {
  it("réduit les dimensions en gardant les proportions", () => {
    expect(fitWithin(4000, 3000, 2000)).toEqual({ width: 2000, height: 1500 });
    expect(fitWithin(3000, 4000, 2000)).toEqual({ width: 1500, height: 2000 });
    expect(fitWithin(1200, 800, 2000)).toEqual({ width: 1200, height: 800 });
    expect(fitWithin(10000, 3, 2000)).toEqual({ width: 2000, height: 1 });
  });

  it("ne réduit que les images lourdes", () => {
    expect(shouldShrink({ type: "image/jpeg", size: 4_000_000 })).toBe(true);
    expect(shouldShrink({ type: "image/png", size: 100_000 })).toBe(false);
    expect(shouldShrink({ type: "application/pdf", size: 9_000_000 })).toBe(false);
  });

  it("renomme le fichier réduit en .jpg", () => {
    expect(shrunkName("IMG_2034.HEIC")).toBe("IMG_2034.jpg");
    expect(shrunkName("reçu caisse.png")).toBe("reçu caisse.jpg");
    expect(shrunkName("sans-extension")).toBe("sans-extension.jpg");
    expect(shrunkName(".png")).toBe("photo.jpg");
  });

  it("affiche les tailles en unités françaises", () => {
    expect(formatSize(512, "fr")).toBe("512 o");
    expect(formatSize(300 * 1024, "fr")).toBe("300 Ko");
    expect(formatSize(2.5 * 1024 * 1024, "fr")).toBe("2,5 Mo");
    expect(formatSize(2.5 * 1024 * 1024, "en")).toBe("2.5 MB");
  });
});

import { describe, expect, it } from "vitest";

import { getClientDictionary } from "./client";

describe("getClientDictionary", () => {
  it("renvoie le dictionnaire français pour la locale fr", () => {
    expect(getClientDictionary("fr").errors.title).toBeTruthy();
    expect(getClientDictionary("fr").errors.retry).toBeTruthy();
  });

  it("renvoie le dictionnaire anglais pour la locale en", () => {
    expect(getClientDictionary("en").errors.title).toBeTruthy();
    expect(getClientDictionary("en").common.backHome).toBeTruthy();
  });

  it("replie sur le français pour une locale inconnue", () => {
    expect(getClientDictionary("es")).toEqual(getClientDictionary("fr"));
    expect(getClientDictionary(undefined)).toEqual(getClientDictionary("fr"));
  });

  it("les sections errors des deux langues portent les mêmes clés", () => {
    const fr = getClientDictionary("fr").errors;
    const en = getClientDictionary("en").errors;
    expect(Object.keys(fr).sort()).toEqual(Object.keys(en).sort());
  });
});

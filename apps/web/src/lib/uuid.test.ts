import { describe, expect, it } from "vitest";

import { uuidV4 } from "./uuid";

describe("uuidV4", () => {
  it("produit des UUID v4 valides et distincts", () => {
    const ids = new Set(Array.from({ length: 1000 }, uuidV4));
    expect(ids.size).toBe(1000);
    for (const id of ids) {
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    }
  });
});

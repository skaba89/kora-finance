import { describe, expect, it } from "vitest";

import { tokenFrom } from "./link-token";

describe("tokenFrom", () => {
  const token = "Ab3_-".repeat(9);

  it("lit le jeton d'un lien reçu par email", () => {
    expect(tokenFrom({ jeton: token })).toBe(token);
  });

  it("refuse un jeton absent, multiple, tronqué ou contenant d'autres caractères", () => {
    expect(tokenFrom({})).toBeNull();
    expect(tokenFrom({ jeton: [token, token] })).toBeNull();
    expect(tokenFrom({ jeton: "court" })).toBeNull();
    expect(tokenFrom({ jeton: `${token}<script>` })).toBeNull();
    expect(tokenFrom({ jeton: `${token}&x=1` })).toBeNull();
  });
});

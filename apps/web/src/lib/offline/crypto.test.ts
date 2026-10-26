// @vitest-environment node
import { describe, expect, it } from "vitest";

import { newKey, seal, unseal } from "./crypto";

describe("chiffrement de l'appareil", () => {
  it("restitue la valeur avec la bonne clé et le bon identifiant", async () => {
    const key = await newKey();
    const sealed = await seal(key, "queue:u:1", { montant: "1500000" });
    expect(new TextDecoder().decode(sealed.data)).not.toContain("1500000");
    await expect(unseal(key, "queue:u:1", sealed)).resolves.toEqual({ montant: "1500000" });
  });

  it("refuse un enregistrement déplacé sous un autre identifiant ou une autre clé", async () => {
    const key = await newKey();
    const sealed = await seal(key, "queue:u:1", { montant: "1" });
    await expect(unseal(key, "queue:u:2", sealed)).rejects.toThrow();
    await expect(unseal(await newKey(), "queue:u:1", sealed)).rejects.toThrow();
  });

  it("génère une clé non exportable", async () => {
    const key = await newKey();
    expect(key.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw", key)).rejects.toThrow();
  });
});

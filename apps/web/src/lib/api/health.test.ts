import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createApiClient } from "./client";
import { getApiHealth } from "./health";

function clientRepondant(status: number, body: unknown) {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  return createApiClient(fetchMock as unknown as typeof fetch);
}

describe("getApiHealth", () => {
  beforeEach(() => {
    vi.stubEnv("KORA_API_INTERNAL_URL", "http://api.test");
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("renvoie « operationnelle » quand la sonde répond ok", async () => {
    const client = clientRepondant(200, { status: "ok", database: "ok", redis: "ok" });
    await expect(getApiHealth(client)).resolves.toBe("operationnelle");
  });

  it("renvoie « degradee » quand une dépendance est indisponible (503)", async () => {
    const client = clientRepondant(503, { status: "erreur", database: "erreur", redis: "ok" });
    await expect(getApiHealth(client)).resolves.toBe("degradee");
  });

  it("renvoie « injoignable » quand le réseau échoue", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const client = createApiClient(fetchMock as unknown as typeof fetch);
    await expect(getApiHealth(client)).resolves.toBe("injoignable");
  });

  it("refuse de démarrer sans URL d'API configurée", () => {
    vi.stubEnv("KORA_API_INTERNAL_URL", "");
    expect(() => createApiClient()).toThrow("KORA_API_INTERNAL_URL");
  });
});

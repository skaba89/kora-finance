import { describe, expect, it } from "vitest";

import { isFresh, jwtExpiresAt, safeNextPath } from "./session";

function jwt(payload: object) {
  const encode = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${encode({ alg: "HS256" })}.${encode(payload)}.signature`;
}

describe("safeNextPath", () => {
  it.each([
    ["/dossiers/abc", "/dossiers/abc"],
    [null, "/dossiers"],
    ["https://evil.example", "/dossiers"],
    ["//evil.example", "/dossiers"],
    ["/\\evil.example", "/dossiers"],
  ])("« %s » → « %s »", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });
});

describe("jetons", () => {
  it("lit l'expiration d'un JWT", () => {
    expect(jwtExpiresAt(jwt({ exp: 1_800_000_000 }))).toBe(1_800_000_000);
    expect(jwtExpiresAt("pas-un-jwt")).toBeNull();
  });

  it("considère un jeton proche de l'expiration comme à renouveler", () => {
    const now = 1_000_000;
    expect(isFresh(jwt({ exp: now + 600 }), now)).toBe(true);
    expect(isFresh(jwt({ exp: now + 30 }), now)).toBe(false);
    expect(isFresh(undefined, now)).toBe(false);
  });
});

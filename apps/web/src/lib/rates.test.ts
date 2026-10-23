import { describe, expect, it } from "vitest";

import { percentToBasisPoints } from "./rates";

describe("percentToBasisPoints", () => {
  it.each([
    ["18", 1800],
    ["18,5", 1850],
    ["18.05", 1805],
    ["0", 0],
    ["100", 10_000],
    [" 7,25 ", 725],
  ])("convertit « %s » en %i", (input, expected) => {
    expect(percentToBasisPoints(input)).toBe(expected);
  });

  it.each(["", "abc", "18,555", "-5", "100,01", "1000", "18%"])("refuse « %s »", (input) => {
    expect(percentToBasisPoints(input)).toBeNull();
  });
});

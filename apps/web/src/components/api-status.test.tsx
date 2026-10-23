import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiStatusBadge } from "./api-status";

describe("ApiStatusBadge", () => {
  it.each([
    ["operationnelle", "Opérationnelle"],
    ["degradee", "Dégradée"],
    ["injoignable", "Injoignable"],
  ] as const)("affiche « %s » en français", (health, label) => {
    render(<ApiStatusBadge health={health} />);
    expect(screen.getByRole("status")).toHaveTextContent(label);
  });
});

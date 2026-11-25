import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlatformMfaNotice } from "@/components/admin/platform-mfa-notice";

describe("avis de double authentification plateforme", () => {
  it("explique le refus et renvoie vers la sécurité du compte", () => {
    render(<PlatformMfaNotice refused locale="fr" />);
    expect(screen.getByRole("alert")).toHaveTextContent("double authentification");
    expect(screen.getByRole("link", { name: "Activer la double authentification" }))
      .toHaveAttribute("href", "/compte/securite");
  });

  it("avertit sans bloquer tant que l’exigence n’est pas active", () => {
    render(<PlatformMfaNotice refused={false} locale="en" />);
    expect(screen.getByRole("status")).toHaveTextContent("two-factor authentication");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("link", { name: "Enable two-factor authentication" }))
      .toHaveAttribute("href", "/compte/securite");
  });
});

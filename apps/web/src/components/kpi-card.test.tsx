import { render, screen } from "@testing-library/react";
import { Wallet } from "lucide-react";
import { describe, expect, it } from "vitest";
import { KpiCard } from "./kpi-card";

describe("KpiCard", () => {
  it("préserve les valeurs formatées sans calcul ni arrondi", () => {
    const value = "9\u202f007\u202f199\u202f254\u202f740\u202f993 GNF";
    render(<KpiCard icon={Wallet} label="Trésorerie" value={value} hint="Cumul validé" />);
    expect(screen.getByText("Trésorerie")).toBeInTheDocument();
    expect(screen.getByText(/9.*993 GNF/).textContent).toBe(value);
    expect(screen.getByText("Cumul validé")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("conserve un signe négatif et un lien explicite", () => {
    render(<KpiCard icon={Wallet} label="Trésorerie" value="-10 GNF" href="/dossiers/test/tresorerie" primary negative />);
    expect(screen.getByRole("link", { name: /Trésorerie/ })).toHaveAttribute("href", "/dossiers/test/tresorerie");
    expect(screen.getByText("-10 GNF")).toHaveClass("text-destructive", "tabular-nums");
  });
});

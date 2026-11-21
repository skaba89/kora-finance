import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ForecastChart } from "./forecast-chart";
import type { DailyProjection, Forecast } from "@/lib/cashflow";
import { formatMoney } from "@/lib/format";

const labels = { balance: "Solde", inflow: "Entrées", outflow: "Sorties", week: "Semaine", table: "Prévision", independentScales: "Échelles distinctes" };
const day = (flow_date: string, balance: string, inflow: string): DailyProjection => ({
  flow_date, balance, inflow, outflow: "0", status: "SAIN", committed_inflow: inflow,
  committed_outflow: "0", estimated_inflow: "0", estimated_outflow: "0",
});
const forecast: Forecast = {
  as_of: "2026-11-09", horizon_days: 30, scenario: "NEUTRE", opening_total: "0",
  status: "SAIN", first_critical_date: null, lowest_balance: "0", lowest_balance_date: "2026-11-09",
  beyond_horizon_inflow: "0", beyond_horizon_outflow: "0", insufficient_data: false,
  history_months_used: 1, assumptions: {}, accounts: [], excluded_drafts: [],
  days: [day("2026-11-09", "123", "123"), day("2026-11-16", "9007199254741116", "9007199254740993")],
};

describe("ForecastChart", () => {
  it("expose les montants exacts de la semaine sélectionnée, même au-delà de MAX_SAFE_INTEGER", () => {
    render(<ForecastChart forecast={forecast} locale="fr" currency="GNF" labels={labels} />);
    const select = screen.getByRole("combobox", { name: "Semaine" });
    fireEvent.change(select, { target: { value: "2026-11-16" } });
    const values = screen.getAllByRole("definition").map((node) => node.textContent);
    expect(values).toEqual([formatMoney(9007199254740993n, "GNF"), formatMoney(0n, "GNF"), formatMoney(9007199254741116n, "GNF")]);
    expect(screen.getByText("Échelles distinctes")).toBeInTheDocument();
  });

  it("ne rend pas de graphique sans données", () => {
    const { container } = render(<ForecastChart forecast={{ ...forecast, days: [] }} locale="en" currency="GNF" labels={labels} />);
    expect(container).toBeEmptyDOMElement();
  });
});

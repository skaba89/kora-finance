"use client";

import { useState } from "react";

import { formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { aggregateWeekly, type Forecast } from "@/lib/cashflow";

type Labels = {
  balance: string;
  inflow: string;
  outflow: string;
  week: string;
  table: string;
};

const HEIGHT = 180;
const BAR = 12;
const GAP = 2;
const TOP = 10;

/**
 * Prévision de trésorerie : colonnes groupées des flux hebdomadaires (entrées en
 * bleu, sorties en orange — palette catégorielle validée) et solde projeté de fin
 * de semaine en ligne. Au-delà de 30 jours, l'agrégation hebdomadaire reste lisible
 * sur mobile ; le tableau journalier détaillé reste disponible sous le graphique.
 * Hauteurs et coordonnées calculées en BigInt : montants jamais en flottant.
 */
export function ForecastChart({
  forecast,
  currency,
  locale,
  labels,
}: {
  forecast: Forecast;
  currency: string;
  locale: Locale;
  labels: Labels;
}) {
  const [active, setActive] = useState<number | null>(null);
  const tag = locale === "en" ? "en-GB" : "fr-FR";
  const weeks = aggregateWeekly(forecast.days);
  if (weeks.length === 0) return null;

  const maxFlow = weeks.reduce(
    (m, w) => (w.inflow > m ? w.inflow : w.outflow > m ? w.outflow : m),
    0n,
  );
  const balances = weeks.map((w) => w.end_balance);
  const [minBalance, maxBalance] = balances.reduce(
    ([lo, hi], b) => [b < lo ? b : lo, b > hi ? b : hi],
    [balances[0], balances[0]],
  );
  const span = maxBalance - minBalance || 1n;
  const BAND = BAR * 2 + GAP + 8;

  const weekLabel = (iso: string) =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString(tag, {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    });

  const yOf = (balance: bigint) =>
    TOP + Number(((maxBalance - balance) * BigInt(HEIGHT - TOP - 4)) / span);
  const xOf = (index: number) => index * BAND + 4;

  const linePoints = weeks
    .map((w, i) => `${xOf(i) + BAR},${yOf(w.end_balance)}`)
    .join(" ");

  return (
    <figure>
      <svg
        viewBox={`0 0 ${weeks.length * BAND} ${HEIGHT + 24}`}
        className="w-full"
        role="img"
        aria-label={labels.table}
      >
        {weeks.map((week, index) => {
          const inH = maxFlow > 0n ? Number((week.inflow * BigInt(HEIGHT - TOP)) / maxFlow) : 0;
          const outH = maxFlow > 0n ? Number((week.outflow * BigInt(HEIGHT - TOP)) / maxFlow) : 0;
          const base = HEIGHT;
          return (
            <g
              key={week.week_start}
              onMouseEnter={() => setActive(index)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
              tabIndex={0}
            >
              <rect
                x={xOf(index) - 2}
                y={0}
                width={BAND - 2}
                height={HEIGHT + 24}
                fill={active === index ? "var(--muted)" : "transparent"}
              />
              <rect
                x={xOf(index)}
                y={base - inH}
                width={BAR}
                height={inH}
                fill="var(--chart-1)"
              />
              <rect
                x={xOf(index) + BAR + GAP}
                y={base - outH}
                width={BAR}
                height={outH}
                fill="var(--chart-2)"
              />
              <text x={xOf(index) + BAR} y={HEIGHT + 16} textAnchor="middle" fontSize="9" fill="currentColor">
                {weekLabel(week.week_start)}
              </text>
            </g>
          );
        })}
        <polyline points={linePoints} fill="none" stroke="currentColor" strokeWidth="1.5" />
        {weeks.map((week, index) => (
          <circle
            key={week.week_start}
            cx={xOf(index) + BAR}
            cy={yOf(week.end_balance)}
            r={active === index ? 3 : 1.5}
            fill="currentColor"
          />
        ))}
      </svg>
      <figcaption className="text-sm text-muted-foreground">
        <span className="mr-3">
          <span className="inline-block size-2 rounded-full bg-[var(--chart-1)] align-middle" />{" "}
          {labels.inflow}
        </span>
        <span className="mr-3">
          <span className="inline-block size-2 rounded-full bg-[var(--chart-2)] align-middle" />{" "}
          {labels.outflow}
        </span>
        <span>— {labels.balance}</span>
        {active !== null && (
          <span className="ml-2 font-medium text-foreground">
            {weekLabel(weeks[active].week_start)} :{" "}
            {formatMoney(weeks[active].end_balance.toString(), currency, locale)} ({labels.balance})
          </span>
        )}
      </figcaption>
    </figure>
  );
}

"use client";

import { useState } from "react";

import { formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";

export type MonthPoint = { month: string; revenue: string; expenses: string };

type Labels = { revenue: string; expenses: string; month: string; table: string; title: string };

const HEIGHT = 160;
const BAR = 16;
const GAP = 2;
const BAND = 44;
const TOP = 8;

/**
 * Chiffre d'affaires et charges par mois : colonnes groupées sur une seule échelle,
 * légende, détail au survol ou au clavier, tableau des chiffres. Couleurs : les deux
 * premières teintes de la palette catégorielle validée (bleu, orange), pas de couleur
 * sur le texte. Les hauteurs sont calculées en BigInt (montants jamais en flottant).
 */
export function MonthlyChart({
  points,
  currency,
  locale,
  labels,
}: {
  points: MonthPoint[];
  currency: string;
  locale: Locale;
  labels: Labels;
}) {
  const [active, setActive] = useState<number | null>(null);
  const tag = locale === "en" ? "en-GB" : "fr-FR";
  const monthName = (iso: string, style: "short" | "long") =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString(tag, { month: style, year: style === "long" ? "numeric" : undefined, timeZone: "UTC" });
  const positive = (v: string) => (BigInt(v) > 0n ? BigInt(v) : 0n);
  const max = points.reduce((m, p) => [positive(p.revenue), positive(p.expenses), m].reduce((a, b) => (a > b ? a : b)), 0n);
  const height = (v: string) => (max === 0n ? 0 : Number((positive(v) * BigInt(HEIGHT * 100)) / max) / 100);
  const money = (v: string) => formatMoney(BigInt(v), currency, locale);
  const width = Math.max(points.length * BAND, BAND);
  const shown = active === null ? null : points[active];

  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="sr-only">{labels.title}</figcaption>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" aria-hidden>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm bg-[#2a78d6] dark:bg-[#3987e5]" />
          {labels.revenue}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm bg-[#eb6834] dark:bg-[#d95926]" />
          {labels.expenses}
        </span>
      </div>
      <div className="relative min-w-0 overflow-x-auto rounded-lg border bg-background/50 p-2">
        <svg
          viewBox={`0 0 ${width} ${HEIGHT + TOP + 24}`}
          width={width}
          height={HEIGHT + TOP + 24}
          role="img"
          aria-label={labels.title}
          className="max-w-none"
        >
          <line x1={0} x2={width} y1={TOP} y2={TOP} className="stroke-border" strokeDasharray="2 4" />
          {[1, 2, 3].map(step => <line key={step} x1={0} x2={width} y1={TOP + HEIGHT * step / 4} y2={TOP + HEIGHT * step / 4} className="stroke-border" strokeDasharray="2 4" />)}
          <line x1={0} x2={width} y1={TOP + HEIGHT} y2={TOP + HEIGHT} className="stroke-border" />
          {points.map((p, i) => {
            const x = i * BAND + (BAND - (2 * BAR + GAP)) / 2;
            const hr = height(p.revenue);
            const he = height(p.expenses);
            return (
              <g
                key={p.month}
                tabIndex={0}
                role="button"
                aria-label={`${monthName(p.month, "long")} : ${labels.revenue} ${money(p.revenue)}, ${labels.expenses} ${money(p.expenses)}`}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
                onClick={() => setActive(i)}
                onKeyDown={event => {
                  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(i); }
                  if (event.key === "Escape") setActive(null);
                }}
                className="outline-none focus-visible:[&>rect:first-child]:fill-muted"
              >
                <rect x={i * BAND} y={0} width={BAND} height={HEIGHT + TOP + 24} className={active === i ? "fill-muted" : "fill-transparent"} />
                {hr > 0 ? (
                  <path d={column(x, TOP + HEIGHT, BAR, hr)} className="fill-[#2a78d6] dark:fill-[#3987e5]" />
                ) : null}
                {he > 0 ? (
                  <path d={column(x + BAR + GAP, TOP + HEIGHT, BAR, he)} className="fill-[#eb6834] dark:fill-[#d95926]" />
                ) : null}
                <text x={i * BAND + BAND / 2} y={TOP + HEIGHT + 16} textAnchor="middle" className="fill-muted-foreground text-[11px]">
                  {monthName(p.month, "short")}
                </text>
              </g>
            );
          })}
        </svg>
        {shown ? (
          <div
            role="status"
            className="bg-popover text-popover-foreground pointer-events-none absolute top-0 rounded-md border px-3 py-2 text-xs shadow-sm"
            style={{ left: Math.min((active ?? 0) * BAND, Math.max(width - 200, 0)) }}
          >
            <p className="font-medium">{monthName(shown.month, "long")}</p>
            <p className="tabular-nums">
              {labels.revenue} : {money(shown.revenue)}
            </p>
            <p className="tabular-nums">
              {labels.expenses} : {money(shown.expenses)}
            </p>
          </div>
        ) : null}
      </div>
      <details className="text-sm">
        <summary className="text-muted-foreground hover:text-foreground cursor-pointer py-2 font-medium">{labels.table}</summary>
        <div className="min-w-0 overflow-x-auto">
        <table className="mt-2 w-full min-w-[20rem] text-left">
          <thead>
            <tr className="text-muted-foreground">
              <th className="py-1 font-normal">{labels.month}</th>
              <th className="py-1 text-right font-normal">{labels.revenue}</th>
              <th className="py-1 text-right font-normal">{labels.expenses}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.month} className="border-t">
                <td className="py-1">{monthName(p.month, "long")}</td>
                <td className="py-1 text-right tabular-nums">{money(p.revenue)}</td>
                <td className="py-1 text-right tabular-nums">{money(p.expenses)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </details>
    </figure>
  );
}

/** Colonne posée sur la ligne de base, extrémité arrondie (4 px), base carrée. */
function column(x: number, baseline: number, w: number, h: number): string {
  const r = Math.min(4, h, w / 2);
  const top = baseline - h;
  return `M${x},${baseline} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${baseline} Z`;
}

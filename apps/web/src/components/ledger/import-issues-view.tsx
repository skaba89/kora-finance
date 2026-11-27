"use client";

import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";
import type { fr } from "@/lib/i18n/fr";

type IssueOut = components["schemas"]["ImportIssueOut"];

export type ImportIssuesLabels = Pick<
  typeof fr.imports,
  "issues" | "row" | "code" | "truncated" | "moreIssues" | "loadingMore"
>;

/**
 * Revue des anomalies d'un rapport de précontrôle : tableau des anomalies
 * affichées et chargement par pages du reste conservé côté serveur.
 */
export function ImportIssuesView({ issues, remaining, truncated, loadingMore, onLoadMore, labels: t }: {
  issues: IssueOut[];
  /** Anomalies conservées pas encore affichées (0 : tout est visible). */
  remaining: number;
  /** Le rapport initial était tronqué : la note de pagination s'affiche. */
  truncated: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  labels: ImportIssuesLabels;
}) {
  return <>
    {truncated && <p className="text-sm">{t.truncated}</p>}
    {issues.length > 0 && <table className="w-full text-left text-sm"><thead><tr><th className="p-2">{t.row}</th><th className="p-2">{t.code}</th></tr></thead><tbody>{issues.map((issue, index) => <tr key={`${issue.row}-${index}`} className="border-t"><td className="p-2 tabular-nums">{issue.row}</td><td className="p-2 wrap-anywhere">{issue.code}</td></tr>)}</tbody></table>}
    {remaining > 0 && <Button type="button" variant="outline" className="min-h-11" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? t.loadingMore : `${t.moreIssues} (${remaining})`}</Button>}
  </>;
}

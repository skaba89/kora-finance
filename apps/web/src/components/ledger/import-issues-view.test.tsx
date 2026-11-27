import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ImportIssuesView } from "@/components/ledger/import-issues-view";

const labels = {
  issues: "Anomalies",
  row: "Ligne",
  code: "Code de contrôle",
  truncated:
    "Seules les 200 premières anomalies sont affichées ; les suivantes se chargent depuis le rapport conservé.",
  moreIssues: "Afficher plus d’anomalies",
  loadingMore: "Chargement…",
};

const issues = [
  { row: 2, code: "unknown_journal" },
  { row: 3, code: "unknown_journal" },
];

describe("revue des anomalies de précontrôle", () => {
  it("affiche les anomalies lues et masque la pagination quand tout est visible", () => {
    render(
      <ImportIssuesView
        issues={issues}
        remaining={0}
        truncated={false}
        loadingMore={false}
        onLoadMore={() => {}}
        labels={labels}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(3); // en-tête + 2 anomalies
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.queryByText(labels.truncated)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("annonce la troncature et charge la suite depuis le rapport conservé", () => {
    const loadMore = vi.fn();
    render(
      <ImportIssuesView
        issues={issues}
        remaining={10}
        truncated
        loadingMore={false}
        onLoadMore={loadMore}
        labels={labels}
      />,
    );
    expect(screen.getByText(/Seules les 200 premières anomalies/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Afficher plus d’anomalies \(10\)/ }));
    expect(loadMore).toHaveBeenCalledOnce();
  });

  it("désactive le bouton pendant la lecture d’une page", () => {
    render(
      <ImportIssuesView
        issues={[]}
        remaining={5}
        truncated={false}
        loadingMore
        onLoadMore={() => {}}
        labels={labels}
      />,
    );
    const button = screen.getByRole("button", { name: labels.loadingMore });
    expect(button).toBeDisabled();
  });

  it("n’affiche ni tableau ni pagination sans anomalies", () => {
    render(
      <ImportIssuesView
        issues={[]}
        remaining={0}
        truncated={false}
        loadingMore={false}
        onLoadMore={() => {}}
        labels={labels}
      />,
    );
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

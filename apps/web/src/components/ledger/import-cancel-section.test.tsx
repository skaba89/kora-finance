import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ImportCancelSection } from "@/components/ledger/import-cancel-section";
import type { fr } from "@/lib/i18n/fr";

const labels = {
  cancel: "Annuler ce dépôt",
  cancelPending: "Annulation en cours…",
  cancelHint: "Supprime définitivement le dépôt et les brouillons encore présents.",
  cancelledTitle: "Dépôt annulé",
  cancelledHint: "Le même fichier corrigé peut être redéposé.",
  cancelledDrafts: "Brouillons supprimés",
  lines: "Lignes comptables",
} as unknown as typeof fr.imports;

const cancellation = {
  cancelled_at: "2026-11-28T12:00:00Z",
  entries_removed: 2,
  lines_removed: 4,
};

const base = {
  cancellation: null,
  error: null,
  cancelling: false,
  onCancel: () => {},
  labels,
};

describe("section d’annulation d’un dépôt importé", () => {
  it("propose l’annulation avant l’acte, avec son avertissement définitif", () => {
    const onCancel = vi.fn();
    render(<ImportCancelSection {...base} onCancel={onCancel} />);
    expect(screen.getByText(labels.cancelHint)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: labels.cancel });
    expect(button).toBeEnabled();
    expect(screen.queryByText(labels.cancelledTitle)).toBeNull();
    fireEvent.click(button);
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("désactive le bouton pendant l’annulation", () => {
    render(<ImportCancelSection {...base} cancelling />);
    expect(screen.getByRole("button", { name: labels.cancelPending })).toBeDisabled();
  });

  it("annonce l’annulation avec les brouillons supprimés et masque le bouton", () => {
    render(<ImportCancelSection {...base} cancellation={cancellation} />);
    expect(screen.getByText(labels.cancelledTitle)).toBeInTheDocument();
    expect(screen.getByText(labels.cancelledDrafts)).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument(); // lignes supprimées
    expect(screen.getByText(labels.cancelledHint)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: labels.cancel })).toBeNull();
    expect(screen.queryByRole("button", { name: labels.cancelPending })).toBeNull();
  });

  it("affiche l’échec (écriture validée) et garde la possibilité de réessayer", () => {
    render(
      <ImportCancelSection
        {...base}
        error="Ce batch contient une écriture validée : il ne peut plus être annulé."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("écriture validée");
    expect(screen.getByRole("button", { name: labels.cancel })).toBeEnabled();
  });

  it("n’annonce aucun compteur de brouillons pour un dépôt jamais confirmé", () => {
    render(
      <ImportCancelSection
        {...base}
        cancellation={{ ...cancellation, entries_removed: 0, lines_removed: 0 }}
      />,
    );
    expect(screen.getByText(labels.cancelledTitle)).toBeInTheDocument();
    expect(screen.queryByText(labels.cancelledDrafts)).toBeNull();
  });
});

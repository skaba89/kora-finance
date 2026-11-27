import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ImportConfirmSection } from "@/components/ledger/import-confirm-section";
import type { fr } from "@/lib/i18n/fr";

const labels = {
  confirm: "Comptabiliser en brouillons",
  confirmPending: "Confirmation en cours…",
  confirmHint: "Aucune écriture n’est validée automatiquement.",
  confirmedTitle: "Import comptabilisé en brouillons",
  confirmedHint: "Confirmé le",
  entries: "Écritures détectées",
  lines: "Lignes comptables",
  debit: "Total débit",
  credit: "Total crédit",
  seeEntries: "Voir les écritures",
} as unknown as typeof fr.imports;

const confirmation = {
  confirmed_at: "2026-11-27T12:00:00Z",
  entries: 2,
  lines: 4,
  debit: "4500000",
  credit: "4500000",
};

const base = {
  error: null,
  confirming: false,
  onConfirm: () => {},
  companyId: "11111111-1111-1111-1111-111111111111",
  labels,
  locale: "fr" as const,
};

describe("section de confirmation d’un import", () => {
  it("propose la confirmation avant l’acte, sans aucune écriture validée automatiquement", () => {
    const onConfirm = vi.fn();
    render(<ImportConfirmSection {...base} confirmation={null} onConfirm={onConfirm} />);
    expect(screen.getByText(labels.confirmHint)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: labels.confirm });
    expect(button).toBeEnabled();
    expect(screen.queryByText(labels.confirmedTitle)).toBeNull();
    fireEvent.click(button);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("désactive le bouton pendant la confirmation", () => {
    render(<ImportConfirmSection {...base} confirmation={null} confirming />);
    expect(screen.getByRole("button", { name: labels.confirmPending })).toBeDisabled();
  });

  it("annonce les brouillons créés et masque le bouton une fois confirmé", () => {
    render(<ImportConfirmSection {...base} confirmation={confirmation} />);
    expect(screen.getByText(labels.confirmedTitle)).toBeInTheDocument();
    expect(screen.getAllByText("4 500 000 GNF")).toHaveLength(2); // débit + crédit
    expect(screen.getByText(labels.seeEntries)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: labels.confirm })).toBeNull();
    expect(screen.queryByRole("button", { name: labels.confirmPending })).toBeNull();
  });

  it("affiche l’échec et garde la possibilité de réessayer", () => {
    render(<ImportConfirmSection {...base} confirmation={null} error="Le référentiel a changé depuis le dépôt." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Le référentiel a changé depuis le dépôt.");
    expect(screen.getByRole("button", { name: labels.confirm })).toBeEnabled();
  });
});

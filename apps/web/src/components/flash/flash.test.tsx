import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FLASH_DURATION_MS, FlashProvider, useFlash } from "@/components/flash/flash-context";
import { FlashBanner } from "@/components/flash/flash-banner";
import { ActionForm } from "@/components/forms/action-form";
import type { ActionState } from "@/lib/actions/state";

/** Pont entre le test et le contexte : expose showFlash au monde du test. */
function Probe({ onReady }: { onReady: (show: (message: string) => void) => void }) {
  const ctx = useFlash();
  if (!ctx) throw new Error("Probe doit être rendu dans FlashProvider");
  onReady(ctx.showFlash);
  return <span data-testid="state">{ctx.stored ? "shown" : "empty"}</span>;
}

function Pusher(onReady: (show: (message: string) => void) => void) {
  return (
    <FlashProvider closeLabel="Fermer">
      <Probe onReady={onReady} />
      <FlashBanner />
    </FlashProvider>
  );
}

describe("bandeau de confirmation (flash)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Page courante propre : le pushState du test précédent ne traîne pas.
    window.history.pushState({}, "", "/");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("ne rend rien hors du provider", () => {
    render(<FlashBanner />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("affiche le message poussé puis l'efface automatiquement après 6 s", () => {
    let show: ((message: string) => void) | undefined;
    render(Pusher((fn) => (show = fn)));

    expect(screen.getByTestId("state").textContent).toBe("empty");

    act(() => show?.("Écriture comptabilisée."));
    expect(screen.getByRole("status").textContent).toContain("Écriture comptabilisée.");

    act(() => vi.advanceTimersByTime(FLASH_DURATION_MS));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByTestId("state").textContent).toBe("empty");
  });

  it("efface le bandeau par son bouton de fermeture", () => {
    let show: ((message: string) => void) | undefined;
    render(Pusher((fn) => (show = fn)));

    act(() => show?.("Lettre effectuée."));
    expect(screen.getByRole("status")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fermer" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("efface le bandeau au changement de page (contextuel)", () => {
    let show: ((message: string) => void) | undefined;
    const { rerender } = render(Pusher((fn) => (show = fn)));

    act(() => show?.("Modifications enregistrées."));
    expect(screen.getByRole("status")).toBeInTheDocument();

    // Navigation client : la page suivante re-rend le banner, qui détecte
    // le nouveau pathname via window.location et masque le flash d'ailleurs.
    window.history.pushState({}, "", "/dossiers/1/journal-audit");
    rerender(Pusher((fn) => (show = fn)));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("ActionForm pousse le succès au bandeau sans doubler la confirmation en place", async () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ status: "success", message: "Règlement enregistré." }));
    render(
      <FlashProvider closeLabel="Fermer">
        <FlashBanner />
        <ActionForm action={action} submitLabel="Enregistrer" pendingLabel="Envoi…" />
      </FlashProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    });

    expect(action).toHaveBeenCalledOnce();
    expect(screen.getByRole("status").textContent).toContain("Règlement enregistré.");
    expect(screen.getAllByText("Règlement enregistré.").length).toBe(1);
  });

  it("ActionForm sans provider garde la confirmation en place", async () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ status: "success", message: "Profil mis à jour." }));
    render(<ActionForm action={action} submitLabel="Enregistrer" pendingLabel="Envoi…" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    });

    expect(screen.getByText("Profil mis à jour.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fermer" })).not.toBeInTheDocument();
  });
});

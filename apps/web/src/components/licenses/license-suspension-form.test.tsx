import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LicenseSuspensionForm } from "@/components/licenses/license-suspension-form";
import type { ActionState } from "@/lib/actions/state";

const labels = {
  suspend: "Suspendre",
  reactivate: "Réactiver",
  reason: "Motif de l’intervention",
  reasonHint: "Obligatoire, conservé dans le journal d’audit.",
  confirmSuspend: "Suspendre cette période ? Aucun paiement ni droit comptable n’est modifié.",
  confirmReactivate: "Réactiver cette période ?",
  pending: "Envoi…",
};

function setup(suspended: boolean, result: ActionState = { status: "success", message: "Enregistré" }) {
  const action = vi.fn(async (_state: ActionState, _formData: FormData) => result);
  render(<LicenseSuspensionForm action={action} suspended={suspended} labels={labels} fieldId="test" />);
  return action;
}

describe("formulaire de suspension de licence", () => {
  afterEach(() => vi.restoreAllMocks());

  it("exige un motif borné avant tout envoi", () => {
    setup(false);
    const reason = screen.getByLabelText(labels.reason);
    expect(reason).toBeRequired();
    expect(reason).toHaveAttribute("minLength", "3");
    expect(reason).toHaveAttribute("maxLength", "500");
    expect(reason).toHaveAccessibleDescription(labels.reasonHint);
  });

  it("propose la suspension d’une période active, avec confirmation explicite", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const action = setup(false);
    fireEvent.change(screen.getByLabelText(labels.reason), { target: { value: "Impayé constaté" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: labels.suspend }));
    });
    expect(confirm).toHaveBeenCalledWith(labels.confirmSuspend);
    expect(action).toHaveBeenCalledOnce();
    const formData = action.mock.calls[0]?.[1];
    expect(formData?.get("reason")).toBe("Impayé constaté");
  });

  it("n’envoie rien si l’administrateur annule la confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const action = setup(false);
    fireEvent.change(screen.getByLabelText(labels.reason), { target: { value: "Impayé constaté" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: labels.suspend }));
    });
    expect(action).not.toHaveBeenCalled();
  });

  it("propose la réactivation d’une période suspendue et affiche l’erreur de l’API", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    setup(true, { status: "error", message: "État de licence modifié ; actualisez avant de réessayer." });
    expect(screen.queryByRole("button", { name: labels.suspend })).toBeNull();
    fireEvent.change(screen.getByLabelText(labels.reason), { target: { value: "Paiement reçu" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: labels.reactivate }));
    });
    expect(confirm).toHaveBeenCalledWith(labels.confirmReactivate);
    expect(await screen.findByRole("alert")).toHaveTextContent("actualisez");
  });
});

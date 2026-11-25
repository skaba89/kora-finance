import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LicenseRenewalForm, nextDay, renewalAvailability } from "@/components/licenses/license-renewal-form";
import type { ActionState } from "@/lib/actions/state";

const labels = {
  submit: "Renouveler",
  endsOn: "Nouvelle fin (exclusive)",
  endsOnHint: "La nouvelle période commence le 2041-01-01.",
  kind: "Type",
  kinds: { paid: "Payante", trial: "Essai" },
  reason: "Motif de l’intervention",
  reasonHint: "Obligatoire, conservé dans le journal d’audit.",
  confirm: "Créer cette nouvelle période ? Aucun paiement n’est enregistré.",
  pending: "Envoi…",
};

function setup(result: ActionState = { status: "success", message: "Enregistré" }) {
  const action = vi.fn(async (_state: ActionState, _formData: FormData) => result);
  render(<LicenseRenewalForm action={action} previousEndsOn="2041-01-01" labels={labels} fieldId="t" />);
  return action;
}

describe("renouvellement de licence : disponibilité", () => {
  const period = { id: "a", starts_on: "2040-01-01", ends_on: "2041-01-01", suspended: false };

  it("calcule le lendemain en calendrier UTC, y compris en fin d’année et d’année bissextile", () => {
    expect(nextDay("2040-12-31")).toBe("2041-01-01");
    expect(nextDay("2040-02-28")).toBe("2040-02-29");
  });

  it("n’autorise que la dernière période, non suspendue et non expirée", () => {
    expect(renewalAvailability(period, [period], "2026-11-25")).toBe("available");
    expect(renewalAvailability({ ...period, suspended: true }, [period], "2026-11-25")).toBe("suspended");
    expect(renewalAvailability(period, [period], "2041-01-02")).toBe("expired");
    // Le jour même de la fin (borne exclusive) reste renouvelable, comme côté API.
    expect(renewalAvailability(period, [period], "2041-01-01")).toBe("available");
    const successor = { id: "b", starts_on: "2041-01-01", ends_on: "2042-01-01", suspended: false };
    expect(renewalAvailability(period, [period, successor], "2026-11-25")).toBe("renewed");
  });
});

describe("formulaire de renouvellement de licence", () => {
  afterEach(() => vi.restoreAllMocks());

  it("exige une fin postérieure, un type et un motif borné", () => {
    setup();
    const endsOn = screen.getByLabelText(labels.endsOn);
    expect(endsOn).toBeRequired();
    expect(endsOn).toHaveAttribute("type", "date");
    expect(endsOn).toHaveAttribute("min", "2041-01-02");
    expect(screen.getByLabelText(labels.kind)).toHaveValue("paid");
    const reason = screen.getByLabelText(labels.reason);
    expect(reason).toBeRequired();
    expect(reason).toHaveAttribute("minLength", "3");
    expect(reason).toHaveAttribute("maxLength", "500");
  });

  it("envoie la fin, le type et le motif après confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const action = setup();
    fireEvent.change(screen.getByLabelText(labels.endsOn), { target: { value: "2042-01-01" } });
    fireEvent.change(screen.getByLabelText(labels.kind), { target: { value: "trial" } });
    fireEvent.change(screen.getByLabelText(labels.reason), { target: { value: "Renouvellement annuel" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: labels.submit }));
    });
    expect(confirm).toHaveBeenCalledWith(labels.confirm);
    const formData = action.mock.calls[0]?.[1];
    expect(formData?.get("ends_on")).toBe("2042-01-01");
    expect(formData?.get("kind")).toBe("trial");
    expect(formData?.get("reason")).toBe("Renouvellement annuel");
  });

  it("n’envoie rien si la confirmation est annulée et affiche l’erreur de l’API", async () => {
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const action = setup({ status: "error", message: "Une période commerciale chevauche déjà ces dates." });
    fireEvent.change(screen.getByLabelText(labels.endsOn), { target: { value: "2042-01-01" } });
    fireEvent.change(screen.getByLabelText(labels.reason), { target: { value: "Renouvellement annuel" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: labels.submit }));
    });
    expect(action).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: labels.submit }));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("chevauche");
  });
});

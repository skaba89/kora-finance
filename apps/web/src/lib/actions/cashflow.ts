"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api/server";
import { actionDictionary, failure } from "@/lib/actions/support";
import { SCENARIOS, type ForecastScenario } from "@/lib/cashflow";
import type { ActionState } from "./state";

/**
 * Actions d'écriture de la prévision de trésorerie (Phase 3E) : réglage des
 * seuils d'alerte et figeage d'instantanés. L'API exige treasury:manage pour
 * les deux ; le serveur est la seule source de vérité, le formulaire ne fait
 * qu'améliorer le confort.
 */

/** Enregistre les seuils d'alerte et les défauts d'affichage (audité côté API). */
export async function updateCashflowSettingsAction(
  companyId: string,
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const critical = Number(formData.get("critical_floor_minor"));
  const warningRaw = formData.get("warning_floor_minor");
  const warning =
    typeof warningRaw === "string" && warningRaw.trim() !== "" ? Number(warningRaw) : null;
  const horizon = Number(formData.get("default_horizon_days"));
  const scenarioRaw = formData.get("default_scenario");
  const scenario =
    typeof scenarioRaw === "string" && SCENARIOS.includes(scenarioRaw as ForecastScenario)
      ? (scenarioRaw as ForecastScenario)
      : null;

  // Garde-fous locaux (l'API revalide tout) : entiers non négatifs, horizon
  // borné, scénario connu, surveillance >= critique — sinon messages clairs.
  if (
    !Number.isSafeInteger(critical) ||
    critical < 0 ||
    (warning !== null && (!Number.isSafeInteger(warning) || warning < 0))
  ) {
    const t = await actionDictionary();
    return { status: "error", message: t.cashflow.settingsInvalidAmounts };
  }
  if (warning !== null && warning < critical) {
    const t = await actionDictionary();
    return { status: "error", message: t.cashflow.settingsInvalid };
  }
  if (horizon !== 30 && horizon !== 60 && horizon !== 90) {
    const t = await actionDictionary();
    return { status: "error", message: t.common.unexpectedError };
  }
  if (scenario === null) {
    const t = await actionDictionary();
    return { status: "error", message: t.common.unexpectedError };
  }

  const { error, response } = await (await api()).PUT(
    "/api/v1/companies/{company_id}/cashflow/settings",
    {
      params: { path: { company_id: companyId } },
      body: {
        critical_floor_minor: critical,
        warning_floor_minor: warning,
        default_horizon_days: horizon,
        default_scenario: scenario,
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.cashflow.settingsSaved };
}

/** Fige la prévision courante en un instantané (base du prévisionnel vs réalisé).
 * Le scénario est celui de l'écran au moment du clic : passé en argument lié,
 * jamais par le formulaire. */
export async function createCashflowSnapshotAction(
  companyId: string,
  scenario: ForecastScenario,
): Promise<ActionState> {
  const { error, response } = await (await api()).POST(
    "/api/v1/companies/{company_id}/cashflow/snapshots",
    {
      params: {
        path: { company_id: companyId },
        query: { scenario: SCENARIOS.includes(scenario) ? scenario : "NEUTRE" },
      },
    },
  );
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  refresh();
  return { status: "success", message: t.cashflow.freezeDone };
}

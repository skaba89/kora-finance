import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HORIZONS, SCENARIOS, type ForecastScenario } from "@/lib/cashflow";
import { updateCashflowSettingsAction } from "@/lib/actions/cashflow";
import { can, getCashflowSettings, getCompany } from "@/lib/dal";
import { formatMoney } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.cashflow.settings };
}

const SCENARIO_KEYS: Record<
  ForecastScenario,
  "scenarioOptimiste" | "scenarioNeutre" | "scenarioPrudent"
> = {
  OPTIMISTE: "scenarioOptimiste",
  NEUTRE: "scenarioNeutre",
  PRUDENT: "scenarioPrudent",
};

/**
 * Réglage des seuils d'alerte de la prévision de trésorerie (Phase 3E).
 * Lecture possible dès treasury:read (valeurs effectives affichées) ;
 * l'enregistrement exige treasury:manage — le formulaire n'est rendu que
 * pour ce rôle (l'API revalide de toute façon).
 */
export default async function CashflowSettingsPage({
  params,
}: PageProps<"/[lang]/dossiers/[companyId]/tresorerie/previsions/reglages">) {
  const { companyId } = await params;
  const [{ t, locale }, company, settings] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getCashflowSettings(companyId),
  ]);
  const manage = can(company, "treasury:manage");
  const { currency } = company.company;

  return (
    <>
      <PageHeader title={t.cashflow.settings} subtitle={t.cashflow.settingsSubtitle} />

      <p>
        {t.cashflow.criticalFloor} : <strong>{formatMoney(BigInt(settings.critical_floor), currency, locale)}</strong>{" "}
        · {t.cashflow.warningFloor} :{" "}
        <strong>
          {settings.warning_floor
            ? formatMoney(BigInt(settings.warning_floor), currency, locale)
            : t.cashflow.warningFloorNone}
        </strong>{" "}
        · {t.cashflow.settingsHorizon} : <strong>{interpolate(t.cashflow.horizonDays, { n: settings.default_horizon_days })}</strong>
      </p>

      {manage ? (
        <Card className="max-w-2xl">
          <CardHeader>
            <CardTitle className="text-base">{t.cashflow.settings}</CardTitle>
            <p className="text-muted-foreground text-sm">{t.cashflow.settingsHint}</p>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={updateCashflowSettingsAction.bind(null, companyId)}
              submitLabel={t.common.save}
              pendingLabel={t.common.pending}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label={`${t.cashflow.criticalFloor} (GNF)`}
                  name="critical_floor_minor"
                  inputMode="numeric"
                  required
                  min={0}
                  defaultValue={settings.critical_floor}
                />
                <Field
                  label={`${t.cashflow.warningFloor} (GNF, ${t.common.optional.toLowerCase()})`}
                  name="warning_floor_minor"
                  inputMode="numeric"
                  min={0}
                  defaultValue={settings.warning_floor ?? ""}
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <SelectField
                  label={t.cashflow.settingsHorizon}
                  name="default_horizon_days"
                  defaultValue={String(settings.default_horizon_days)}
                  options={HORIZONS.map((value) => ({
                    value: String(value),
                    label: interpolate(t.cashflow.horizonDays, { n: value }),
                  }))}
                />
                <SelectField
                  label={t.cashflow.settingsScenario}
                  name="default_scenario"
                  defaultValue={settings.default_scenario}
                  options={SCENARIOS.map((value) => ({
                    value,
                    label: t.cashflow[SCENARIO_KEYS[value]],
                  }))}
                />
              </div>
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}

      <Link href=".." className="text-sm underline underline-offset-4">
        {t.cashflow.backToForecast}
      </Link>
    </>
  );
}

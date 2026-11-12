"""Tests du moteur de prévision de trésorerie (Phase 3E) — pures, sans base.

Chaque borne exigée par la mission est couverte : horizons, scénarios (coefficients,
décalages, arrondis entiers), tension (seuils), données insuffisantes, exclusion des
virements internes, projection par compte, invariants de somme. Aucun flottant.
"""

import uuid
from datetime import date, timedelta

import pytest

from kora.cashflow.assumptions import (
    HORIZONS_DAYS,
    ForecastStatus,
    Scenario,
)
from kora.cashflow.engine import (
    AccountHolding,
    DatedFlow,
    ForecastError,
    ForecastResult,
    ForecastSettingsInput,
    MonthlyHistory,
    MonthTotals,
    compute_forecast,
    daily_estimated_rate,
    is_treasury_account_number,
)

AS_OF = date(2026, 11, 12)
ACCOUNT_A = uuid.uuid4()  # 521 — banque
ACCOUNT_B = uuid.uuid4()  # 531 — caisse


def _holdings(**balances: int) -> list[AccountHolding]:
    base = [
        AccountHolding(ACCOUNT_A, "521", "Banque", 0),
        AccountHolding(ACCOUNT_B, "531", "Caisse", 0),
    ]
    if balances:
        base = [
            AccountHolding(h.account_id, h.number, h.label, balances.get(h.number, h.balance_minor))
            for h in base
        ]
    return base


def _history(inflow: int = 3_100_000, outflow: int = 1_550_000, n: int = 3) -> MonthlyHistory:
    """Trois mois complets identiques (août-octobre 2026) : moyenne = montants fournis."""
    months = tuple(
        MonthTotals(2026, month, inflow_minor=inflow, outflow_minor=outflow)
        for month in (8, 9, 10)[:n]
    )
    return MonthlyHistory(months)


def _forecast(
    *,
    as_of: date = AS_OF,
    horizon_days: int = 90,
    scenario: Scenario = Scenario.NEUTRE,
    holdings: list[AccountHolding] | None = None,
    committed_flows: list[DatedFlow] | None = None,
    history: MonthlyHistory | None = None,
    settings: ForecastSettingsInput | None = None,
) -> ForecastResult:
    """Prévision avec les défauts du scénario de référence (facultatif : surcharges)."""
    return compute_forecast(
        as_of=as_of,
        horizon_days=horizon_days,
        scenario=scenario,
        holdings=holdings if holdings is not None else _holdings(**{"521": 1_000_000}),
        committed_flows=committed_flows if committed_flows is not None else [],
        history=history if history is not None else _history(),
        settings=settings if settings is not None else ForecastSettingsInput(),
    )


# ------------------------------------------------------------------------ validation


@pytest.mark.parametrize("horizon", [0, 7, 29, 31, 45, 91, 365, -30])
def test_horizon_invalide_refuse(horizon: int) -> None:
    with pytest.raises(ForecastError, match="Horizon"):
        _forecast(horizon_days=horizon)


@pytest.mark.parametrize("horizon", HORIZONS_DAYS)
def test_horizons_acceptes(horizon: int) -> None:
    result = _forecast(horizon_days=horizon)
    assert len(result.days) == horizon


def test_scenario_invalide_refuse() -> None:
    with pytest.raises((ForecastError, KeyError, ValueError)):
        _forecast(scenario="MIRACLE")  # type: ignore[arg-type]


# ------------------------------------------------------------------------- observe


def test_solde_ouverture_somme_des_comptes() -> None:
    result = _forecast(holdings=_holdings(**{"521": 1_000_000, "531": 250_000}))
    assert result.opening_total_minor == 1_250_000
    assert result.days[0].balance_minor > 0


def test_solde_crediteur_decouvert_est_negatif() -> None:
    result = _forecast(holdings=_holdings(**{"521": -400_000}))
    assert result.opening_total_minor == -400_000


# -------------------------------------------------------------------------- engage


def test_engage_entrant_et_sortant_attribues() -> None:
    flows = [
        DatedFlow(AS_OF.replace(day=20), ACCOUNT_A, 500_000, "Remise de chèque"),
        DatedFlow(date(2026, 12, 1), ACCOUNT_A, -300_000, "Chèque émis"),
    ]
    result = _forecast(committed_flows=flows)
    by_date = {d.flow_date: d for d in result.days}
    assert by_date[date(2026, 11, 20)].committed_inflow_minor == 500_000
    assert by_date[date(2026, 12, 1)].committed_outflow_minor == 300_000


def test_engage_hors_horizon_ignore() -> None:
    flows = [DatedFlow(AS_OF + _timedelta(200), ACCOUNT_A, 999_999)]
    result = _forecast(committed_flows=flows)
    assert all(d.committed_inflow_minor == 0 for d in result.days)
    assert all(a.committed_net_minor == 0 for a in result.accounts)


def _timedelta(days: int) -> timedelta:
    return timedelta(days=days)


def test_engage_meme_jour_entree_et_sortie() -> None:
    flows = [
        DatedFlow(date(2026, 11, 15), ACCOUNT_A, 700_000),
        DatedFlow(date(2026, 11, 15), ACCOUNT_B, -700_000),
    ]
    day = next(
        d for d in _forecast(committed_flows=flows).days if d.flow_date == date(2026, 11, 15)
    )
    # Virement interne entre comptes de trésorerie : neutre sur le consolidé au
    # niveau ENGAGE (les flux estimés du jour, indépendants, s'ajoutent par ailleurs).
    assert day.committed_inflow_minor == day.committed_outflow_minor == 700_000


# -------------------------------------------------------------------------- estime


def test_estime_neutre_repartition_uniforme() -> None:
    # Moyenne 3 100 000 / 30 jours de novembre = 103 333 par jour.
    result = _forecast()
    assert result.days[0].estimated_inflow_minor == 3_100_000 // 30
    assert result.days[0].estimated_outflow_minor == 1_550_000 // 30


def test_estime_tient_compte_de_la_longueur_du_mois() -> None:
    # Février 2027 compte 28 jours : le taux journalier y est plus élevé.
    assert daily_estimated_rate(3_100_000, date(2027, 1, 15)) == 3_100_000 // 31
    assert daily_estimated_rate(3_100_000, date(2027, 2, 15)) == 3_100_000 // 28


def test_estime_optimiste_coefficients() -> None:
    result = _forecast(scenario=Scenario.OPTIMISTE)
    attendu_in = (3_100_000 // 30) * 110 // 100
    attendu_out = (1_550_000 // 30) * 95 // 100
    assert result.days[0].estimated_inflow_minor == attendu_in
    assert result.days[0].estimated_outflow_minor == attendu_out


def test_estime_prudent_coefficients_et_decages() -> None:
    result = _forecast(scenario=Scenario.PRUDENT)
    day1 = result.days[0]
    # Encaissements retardés de 15 jours : le J+1 lit le taux du 29/10 (31 jours) × 0,80.
    assert day1.estimated_inflow_minor == (3_100_000 // 31) * 80 // 100
    # Décaissements avancés de 7 jours : J+1 lit le taux du 20/11 (30 jours) × 1,10,
    # majoré des 7 premiers jours de sorties avancés avant le début de fenêtre.
    taux_out = (1_550_000 // 30) * 110 // 100
    assert day1.estimated_outflow_minor == taux_out + 7 * taux_out


def test_prudent_dernier_jour_lit_source_etendue() -> None:
    result = _forecast(scenario=Scenario.PRUDENT)
    last = result.days[-1]
    # Jour source : as_of+90+7 = 19/02/2027, 28 jours en février.
    assert last.estimated_outflow_minor == (1_550_000 // 28) * 110 // 100


def test_prudent_beyond_horizon_agrege_derniers_jours_sources() -> None:
    result = _forecast(scenario=Scenario.PRUDENT)
    # Sources originelles des 15 derniers jours : 29/01/2027 (31 j) × 5, puis février (28 j) × 10.
    attendu = 5 * ((3_100_000 // 31) * 80 // 100) + 10 * ((3_100_000 // 28) * 80 // 100)
    assert result.beyond_horizon_inflow_minor == attendu


@pytest.mark.parametrize("scenario", [Scenario.NEUTRE, Scenario.OPTIMISTE])
def test_beyond_horizon_nul_sans_decalage(scenario: Scenario) -> None:
    assert _forecast(scenario=scenario).beyond_horizon_inflow_minor == 0


# ------------------------------------------------------------- donnees insuffisantes


def test_historique_vide_insurffisant_data() -> None:
    result = _forecast(history=MonthlyHistory(()))
    assert result.insufficient_data is True
    assert result.history_months_used == 0
    assert all(
        d.estimated_inflow_minor == 0 and d.estimated_outflow_minor == 0 for d in result.days
    )
    assert result.beyond_horizon_inflow_minor == 0


def test_historique_un_seul_mois_est_exploite() -> None:
    result = _forecast(history=_history(n=1))
    assert result.insufficient_data is False
    assert result.history_months_used == 1
    assert result.days[0].estimated_inflow_minor == 3_100_000 // 30


def test_historique_flux_nuls_ne_provoque_pas_derreur() -> None:
    result = _forecast(history=_history(inflow=0, outflow=0))
    assert result.insufficient_data is False
    assert all(d.inflow_minor == 0 for d in result.days)


# --------------------------------------------------------------------------- tension


def test_statut_critique_et_premiere_date() -> None:
    flows = [DatedFlow(date(2026, 11, 17), ACCOUNT_A, -1_600_000)]
    result = _forecast(
        committed_flows=flows,
        history=MonthlyHistory(()),  # seulement OBSERVE + ENGAGE : trajectoire exacte
        settings=ForecastSettingsInput(critical_floor_minor=1_000_000),
    )
    assert result.first_critical_date == date(2026, 11, 17)
    assert result.status is ForecastStatus.CRITIQUE
    # 1 000 000 ouverture - 1 600 000 chèque = -600 000, puis stabilité (aucun estimé).
    assert result.lowest_balance_minor == -600_000
    assert result.lowest_balance_date == date(2026, 11, 17)


def test_statut_sous_surveillance_avec_seuil_dalerte() -> None:
    result = _forecast(
        settings=ForecastSettingsInput(critical_floor_minor=500_000, warning_floor_minor=1_200_000)
    )
    assert result.status is ForecastStatus.SOUS_SURVEILLANCE
    assert all(
        d.status in (ForecastStatus.SOUS_SURVEILLANCE, ForecastStatus.SAIN) for d in result.days
    )
    assert result.first_critical_date is None


def test_statut_sain_sans_tension() -> None:
    result = _forecast(
        holdings=_holdings(**{"521": 50_000_000}),
        settings=ForecastSettingsInput(critical_floor_minor=0, warning_floor_minor=1_000_000),
    )
    assert result.status is ForecastStatus.SAIN
    assert result.first_critical_date is None


def test_seuil_critique_franchi_puis_retabli() -> None:
    flows = [DatedFlow(date(2026, 11, 15), ACCOUNT_A, -1_200_000)]
    remise = [DatedFlow(date(2026, 11, 25), ACCOUNT_A, 2_000_000)]
    result = _forecast(
        committed_flows=flows + remise,
        settings=ForecastSettingsInput(critical_floor_minor=1_000_000),
    )
    assert result.first_critical_date == date(2026, 11, 15)
    assert result.days[-1].status is ForecastStatus.SAIN
    assert result.days[0].flow_date == date(2026, 11, 13)


# --------------------------------------------------------------- projection par compte


def test_projection_compte_observed_plus_engaged_uniquement() -> None:
    flows = [
        DatedFlow(date(2026, 12, 10), ACCOUNT_A, 200_000),
        DatedFlow(date(2026, 12, 2), ACCOUNT_B, -50_000),
    ]
    result = _forecast(horizon_days=60, committed_flows=flows)
    by_number = {a.number: a for a in result.accounts}
    assert by_number["521"].opening_minor == 1_000_000
    assert by_number["521"].committed_net_minor == 200_000
    assert by_number["521"].projected_minor == 1_200_000
    assert by_number["521"].balances_at_marks[30] == 1_200_000
    assert by_number["531"].balances_at_marks[30] == -50_000
    assert 60 in by_number["521"].balances_at_marks
    assert 90 not in by_number["521"].balances_at_marks  # marque au-delà de l'horizon


def test_projection_marques_sur_horizon_30() -> None:
    result = _forecast(horizon_days=30)
    marks = result.accounts[0].balances_at_marks
    assert list(marks) == [30]


def test_estime_non_attribue_aux_comptes() -> None:
    result = _forecast()
    # Les estimés sont consolidés uniquement : la projection par compte n'en porte pas.
    for account in result.accounts:
        assert account.projected_minor == account.opening_minor


# ------------------------------------------------------------------------ invariants


def test_invariant_somme_sources_egale_solde_final() -> None:
    flows = [
        DatedFlow(date(2026, 11, 20), ACCOUNT_A, 800_000),
        DatedFlow(date(2026, 12, 15), ACCOUNT_A, -450_000),
    ]
    result = _forecast(committed_flows=flows)
    final = result.days[-1].balance_minor
    recalcul = result.opening_total_minor + sum(
        d.inflow_minor - d.outflow_minor for d in result.days
    )
    assert final == recalcul


def test_montants_toujours_entiers() -> None:
    result = _forecast(scenario=Scenario.PRUDENT)
    for day in result.days:
        for value in (
            day.inflow_minor,
            day.outflow_minor,
            day.balance_minor,
            day.committed_inflow_minor,
            day.estimated_outflow_minor,
        ):
            assert isinstance(value, int)


def test_flux_jamais_negatifs_dans_les_agregats() -> None:
    result = _forecast(scenario=Scenario.PRUDENT)
    for day in result.days:
        assert day.inflow_minor >= 0
        assert day.outflow_minor >= 0


# ----------------------------------------------------------------- trésorerie périmètre


def test_classification_comptes_tresorerie() -> None:
    assert is_treasury_account_number("5211")
    assert is_treasury_account_number("53")
    assert not is_treasury_account_number("5851")  # virements internes exclus
    assert not is_treasury_account_number("4111")
    assert not is_treasury_account_number("401")


def test_hypotheses_seralisees_dans_le_resultat() -> None:
    result = _forecast(scenario=Scenario.PRUDENT)
    assert result.assumptions["scenario"] == "PRUDENT"
    assert result.assumptions["inflow_coefficient"] == {"numerator": 80, "denominator": 100}
    assert result.assumptions["inflow_delay_days"] == 15
    scope = str(result.assumptions["treasury_scope"])
    rule = str(result.assumptions["committed_rule"])
    assert "58x" in scope
    assert "jamais ajustées" in rule

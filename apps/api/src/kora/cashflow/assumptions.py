"""Hypothèses explicites de la prévision de trésorerie (Phase 3E).

Règle fondatrice : le moteur n'invente jamais une transaction future. Tout flux
projeté provient de l'une des trois sources documentées dans la spécification :

- OBSERVE : soldes réels des comptes de trésorerie à la date de calcul ;
- ENGAGE  : écritures validées datées dans le futur (aucun ajustement possible) ;
- ESTIME  : moyenne mensuelle observée sur l'historique, ajustée par scénario.

Les coefficients ci-dessous sont les **seuls** nombres magiques autorisés : ils sont
copiés tels quels dans `assumptions_jsonb` de chaque instantané, et affichés à
l'utilisateur (« Comment ce chiffre est calculé »).
"""

from dataclasses import dataclass
from enum import StrEnum

# Horizons proposés (jours). Toute autre valeur est refusée à la validation.
HORIZONS_DAYS: tuple[int, ...] = (30, 60, 90)

# Fenêtre d'historique exploitée pour les flux estimés : N mois complets précédant
# la date de calcul (le mois en cours, incomplet, n'est jamais mélangé).
HISTORY_MONTHS = 3


class Scenario(StrEnum):
    OPTIMISTE = "OPTIMISTE"
    NEUTRE = "NEUTRE"
    PRUDENT = "PRUDENT"


class ForecastStatus(StrEnum):
    SAIN = "SAIN"
    SOUS_SURVEILLANCE = "SOUS_SURVEILLANCE"
    CRITIQUE = "CRITIQUE"


@dataclass(frozen=True)
class ScenarioAssumptions:
    """Coefficients d'un scénario, en arithmétique entière (numérateur/dénominateur)."""

    inflow_numerator: int
    inflow_denominator: int
    outflow_numerator: int
    outflow_denominator: int
    # Décalage des flux estimés : encaissements retardés, décaissements avancés.
    # Les flux ENGAGE ne sont jamais décalés ni ajustés.
    inflow_delay_days: int = 0
    outflow_advance_days: int = 0


SCENARIO_ASSUMPTIONS: dict[Scenario, ScenarioAssumptions] = {
    Scenario.OPTIMISTE: ScenarioAssumptions(
        inflow_numerator=110,
        inflow_denominator=100,
        outflow_numerator=95,
        outflow_denominator=100,
    ),
    Scenario.NEUTRE: ScenarioAssumptions(
        inflow_numerator=100,
        inflow_denominator=100,
        outflow_numerator=100,
        outflow_denominator=100,
    ),
    Scenario.PRUDENT: ScenarioAssumptions(
        inflow_numerator=80,
        inflow_denominator=100,
        outflow_numerator=110,
        outflow_denominator=100,
        inflow_delay_days=15,
        outflow_advance_days=7,
    ),
}

# Décalage maximal à anticiper côté alimentation (fenêtre des taux étendue).
MAX_OUTFLOW_ADVANCE_DAYS = max(a.outflow_advance_days for a in SCENARIO_ASSUMPTIONS.values())

ESTIMATION_METHOD = (
    "moyenne des totaux mensuels d'encaissements et de décaissements de trésorerie "
    f"sur les {HISTORY_MONTHS} derniers mois complets, répartie uniformément sur les "
    "jours du mois cible ; virements internes (comptes 58x) et écritures de clôture "
    "exclus ; catégorie de contrepartie conservée à titre de traçabilité"
)
ROUNDING = "division entière par défaut (floor) à chaque étape ; aucun flottant"


def scenario_assumptions_dict(scenario: Scenario, history_months_used: int) -> dict[str, object]:
    """Sérialisation des hypothèses d'un calcul, stockée avec chaque instantané."""
    a = SCENARIO_ASSUMPTIONS[scenario]
    return {
        "scenario": scenario.value,
        "inflow_coefficient": {
            "numerator": a.inflow_numerator,
            "denominator": a.inflow_denominator,
        },
        "outflow_coefficient": {
            "numerator": a.outflow_numerator,
            "denominator": a.outflow_denominator,
        },
        "inflow_delay_days": a.inflow_delay_days,
        "outflow_advance_days": a.outflow_advance_days,
        "history_months_used": history_months_used,
        "estimation_method": ESTIMATION_METHOD,
        "rounding": ROUNDING,
    }

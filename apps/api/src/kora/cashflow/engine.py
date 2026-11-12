"""Moteur de prévision de trésorerie — fonctions pures, sans accès base (Phase 3E).

Déterministe et testable sans PostgreSQL : les entrées sont des structures simples
alimentées par `service.py` (soldes observés, flux engagés, historique mensuel).
Arithmétique 100 % entière en unités mineures : aucun flottant nulle part.

Sémantique des scénarios sur les flux ESTIME :
- le taux journalier d'un jour d est `moyenne_mensuelle // jours_du_mois(d)` ;
- un scénario décalé lit le taux du jour source : encaissements PRUDENT en retard de
  15 jours lisent le taux de `d - 15` (les 15 derniers jours de la fenêtre sortent de
  l'horizon et sont agrégés dans `beyond_horizon_inflow_minor`, jamais perdus) ;
- décaissements PRUDENT avancés de 7 jours lisent le taux de `d + 7` (fenêtre des
  taux étendue d'autant : les sorties futures arrivent plus tôt) ;
- les flux ENGAGE ne sont jamais décalés ni ajustés.
"""

from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from kora.cashflow.assumptions import (
    ESTIMATION_METHOD,
    HORIZONS_DAYS,
    ROUNDING,
    SCENARIO_ASSUMPTIONS,
    ForecastStatus,
    Scenario,
    ScenarioAssumptions,
    scenario_assumptions_dict,
)

# Marques affichées (fin de journée) pour la projection par compte.
HORIZON_MARKS: tuple[int, ...] = (30, 60, 90)

# Comptes de trésorerie : classe 5 hors 58x (virements internes), convention SYSCOHADA.
TREASURY_CLASS_PREFIX = "5"
INTERNAL_TRANSFER_PREFIX = "58"


class ForecastError(ValueError):
    """Entrée invalide du moteur (horizon, scénario, cohérence des dates)."""


@dataclass(frozen=True)
class AccountHolding:
    """Compte de trésorerie observé à la date de calcul."""

    account_id: uuid.UUID
    number: str
    label: str
    balance_minor: int  # signé : débiteur (positif) ou créditeur (découvert)


@dataclass(frozen=True)
class DatedFlow:
    """Flux de trésorerie ENGAGE : ligne de trésorerie d'une écriture validée future."""

    flow_date: date
    account_id: uuid.UUID
    amount_minor: int  # signé : débit trésorerie > 0 (entrée), crédit < 0 (sortie)
    label: str | None = None


@dataclass(frozen=True)
class MonthTotals:
    """Totaux d'encaissements/décaissements de trésorerie d'un mois complet passé."""

    year: int
    month: int
    inflow_minor: int = 0
    outflow_minor: int = 0
    # Ventilation par catégorie de contrepartie (traçabilité, hypothèses du snapshot).
    inflow_by_category: dict[str, int] = field(default_factory=dict)
    outflow_by_category: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MonthlyHistory:
    """Historique exploitable : N mois complets ordonnés du plus ancien au plus récent."""

    months: tuple[MonthTotals, ...]


@dataclass(frozen=True)
class ForecastSettingsInput:
    critical_floor_minor: int = 0
    warning_floor_minor: int | None = None


@dataclass(frozen=True)
class DailyProjection:
    flow_date: date
    inflow_minor: int
    outflow_minor: int
    balance_minor: int  # solde consolidé projeté fin de journée
    status: ForecastStatus
    committed_inflow_minor: int
    committed_outflow_minor: int
    estimated_inflow_minor: int
    estimated_outflow_minor: int


@dataclass(frozen=True)
class AccountProjection:
    account_id: uuid.UUID
    number: str
    label: str
    opening_minor: int
    committed_net_minor: int  # net des engagés tombant dans l'horizon
    projected_minor: int  # fin d'horizon (OBSERVE + ENGAGE ; estimés non attribués par compte)
    balances_at_marks: dict[int, int]  # {30: …, 60: …, 90: …} marques <= horizon


@dataclass(frozen=True)
class ForecastResult:
    as_of: date
    horizon_days: int
    scenario: Scenario
    opening_total_minor: int
    status: ForecastStatus
    days: list[DailyProjection]
    accounts: list[AccountProjection]
    first_critical_date: date | None
    lowest_balance_minor: int
    lowest_balance_date: date
    beyond_horizon_inflow_minor: int
    beyond_horizon_outflow_minor: int
    insufficient_data: bool
    history_months_used: int
    assumptions: dict[str, object]


def is_treasury_account_number(number: str) -> bool:
    """Classe 5 (trésorerie) hors 58x (virements internes) — convention SYSCOHADA."""
    return number.startswith(TREASURY_CLASS_PREFIX) and not number.startswith(
        INTERNAL_TRANSFER_PREFIX
    )


def daily_estimated_rate(monthly_average_minor: int, day: date) -> int:
    """Taux journalier estimé : moyenne mensuelle répartie uniformément sur le mois."""
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    return monthly_average_minor // days_in_month


def _aggregate_committed_flows(
    *,
    as_of: date,
    horizon_end: date,
    committed_flows: list[DatedFlow],
) -> tuple[
    dict[date, int],
    dict[date, int],
    dict[uuid.UUID, dict[date, int]],
    dict[uuid.UUID, int],
]:
    """Agrégation journalière des flux ENGAGE, consolidée et par compte."""
    committed_in: dict[date, int] = defaultdict(int)
    committed_out: dict[date, int] = defaultdict(int)
    account_daily_net: dict[uuid.UUID, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    committed_net_by_account: dict[uuid.UUID, int] = defaultdict(int)
    for flow in committed_flows:
        if not (as_of < flow.flow_date <= horizon_end):
            continue  # hors horizon : ni projeté ni compté (requête source déjà bornée)
        if flow.amount_minor >= 0:
            committed_in[flow.flow_date] += flow.amount_minor
        else:
            committed_out[flow.flow_date] += -flow.amount_minor
        account_daily_net[flow.account_id][flow.flow_date] += flow.amount_minor
        committed_net_by_account[flow.account_id] += flow.amount_minor
    return committed_in, committed_out, account_daily_net, committed_net_by_account


def _estimated_flows(
    *,
    as_of: date,
    horizon_days: int,
    assumptions: ScenarioAssumptions,
    avg_in: int,
    avg_out: int,
    insufficient_data: bool,
) -> tuple[dict[date, int], dict[date, int], int]:
    """Flux ESTIME journaliers du scénario + agrégat beyond_horizon des encaissements retardés."""
    estimated_in: dict[date, int] = {}
    estimated_out: dict[date, int] = {}
    for offset in range(1, horizon_days + 1):
        day = as_of + timedelta(days=offset)
        # Encaissements : retard éventuel (on lit le taux du jour source antérieur).
        source_in = day - timedelta(days=assumptions.inflow_delay_days)
        raw_in = daily_estimated_rate(avg_in, source_in) if not insufficient_data else 0
        # Décaissements : avance éventuelle (taux du jour source postérieur ; la
        # fenêtre des taux est étendue d'autant — voir docstring du module).
        source_out = day + timedelta(days=assumptions.outflow_advance_days)
        raw_out = daily_estimated_rate(avg_out, source_out) if not insufficient_data else 0
        estimated_in[day] = raw_in * assumptions.inflow_numerator // assumptions.inflow_denominator
        estimated_out[day] = (
            raw_out * assumptions.outflow_numerator // assumptions.outflow_denominator
        )

    # Encaissements retardés sortant de l'horizon : les jours sources de la fin de la
    # fenêtre (as_of+H-delai+1 … as_of+H) arrivent désormais après l'horizon. Agrégés,
    # jamais silencieusement perdus.
    beyond_in = 0
    if not insufficient_data and assumptions.inflow_delay_days > 0:
        for offset in range(horizon_days - assumptions.inflow_delay_days + 1, horizon_days + 1):
            source = as_of + timedelta(days=offset)
            beyond_in += (
                daily_estimated_rate(avg_in, source)
                * assumptions.inflow_numerator
                // assumptions.inflow_denominator
            )

    # Décaissements avancés tombant avant le début de la fenêtre (jours sources
    # as_of+1 … as_of+avance) : concentrés sur le premier jour projeté — perte nulle,
    # pression de trésorerie montrée immédiatement.
    if not insufficient_data and assumptions.outflow_advance_days > 0:
        pre_window_out = 0
        for offset in range(1, assumptions.outflow_advance_days + 1):
            source = as_of + timedelta(days=offset)
            pre_window_out += (
                daily_estimated_rate(avg_out, source)
                * assumptions.outflow_numerator
                // assumptions.outflow_denominator
            )
        first_day = as_of + timedelta(days=1)
        estimated_out[first_day] = estimated_out.get(first_day, 0) + pre_window_out

    return estimated_in, estimated_out, beyond_in


def _project_daily(
    *,
    as_of: date,
    horizon_days: int,
    opening_total: int,
    committed_in: dict[date, int],
    committed_out: dict[date, int],
    estimated_in: dict[date, int],
    estimated_out: dict[date, int],
    settings: ForecastSettingsInput,
) -> tuple[list[DailyProjection], date | None, int, date, ForecastStatus]:
    """Projection journalière consolidée : soldes, statuts, premier jour critique."""
    days: list[DailyProjection] = []
    balance = opening_total
    first_critical_date: date | None = None
    lowest_balance = opening_total
    lowest_balance_date = as_of
    any_watch = False
    for offset in range(1, horizon_days + 1):
        day = as_of + timedelta(days=offset)
        c_in, c_out = committed_in.get(day, 0), committed_out.get(day, 0)
        e_in, e_out = estimated_in.get(day, 0), estimated_out.get(day, 0)
        balance += (c_in + e_in) - (c_out + e_out)
        status = _day_status(balance, settings)
        if status is ForecastStatus.CRITIQUE and first_critical_date is None:
            first_critical_date = day
        if status is ForecastStatus.SOUS_SURVEILLANCE:
            any_watch = True
        if balance < lowest_balance:
            lowest_balance, lowest_balance_date = balance, day
        days.append(
            DailyProjection(
                flow_date=day,
                inflow_minor=c_in + e_in,
                outflow_minor=c_out + e_out,
                balance_minor=balance,
                status=status,
                committed_inflow_minor=c_in,
                committed_outflow_minor=c_out,
                estimated_inflow_minor=e_in,
                estimated_outflow_minor=e_out,
            )
        )

    if first_critical_date is not None:
        global_status = ForecastStatus.CRITIQUE
    elif any_watch:
        global_status = ForecastStatus.SOUS_SURVEILLANCE
    else:
        global_status = ForecastStatus.SAIN
    return days, first_critical_date, lowest_balance, lowest_balance_date, global_status


def _project_accounts(
    *,
    as_of: date,
    horizon_days: int,
    holdings: list[AccountHolding],
    account_daily_net: dict[uuid.UUID, dict[date, int]],
    committed_net_by_account: dict[uuid.UUID, int],
) -> list[AccountProjection]:
    """Projection par compte (OBSERVE + ENGAGE uniquement, estimés non attribués)."""
    accounts: list[AccountProjection] = []
    for holding in sorted(holdings, key=lambda h: h.number):
        running = holding.balance_minor
        marks: dict[int, int] = {}
        daily = account_daily_net.get(holding.account_id, {})
        for offset in range(1, horizon_days + 1):
            running += daily.get(as_of + timedelta(days=offset), 0)
            if offset in HORIZON_MARKS:
                marks[offset] = running
        accounts.append(
            AccountProjection(
                account_id=holding.account_id,
                number=holding.number,
                label=holding.label,
                opening_minor=holding.balance_minor,
                committed_net_minor=committed_net_by_account.get(holding.account_id, 0),
                projected_minor=running,
                balances_at_marks=marks,
            )
        )
    return accounts


def _assumptions_payload(
    *,
    scenario: Scenario,
    months_used: int,
    insufficient_data: bool,
    history: MonthlyHistory,
) -> dict[str, object]:
    """Hypothèses sérialisées pour l'instantané et l'affichage des calculs."""
    # Ventilation par catégorie de contrepartie sur la fenêtre d'historique (traçabilité
    # des hypothèses : le snapshot conserve ce que la moyenne a effectivement agrégé).
    categories_in: dict[str, int] = defaultdict(int)
    categories_out: dict[str, int] = defaultdict(int)
    for month in history.months:
        for category, amount in month.inflow_by_category.items():
            categories_in[category] += amount
        for category, amount in month.outflow_by_category.items():
            categories_out[category] += amount
    return {
        **scenario_assumptions_dict(scenario, months_used),
        "estimation_method": ESTIMATION_METHOD,
        "rounding": ROUNDING,
        "treasury_scope": "classe 5 hors 58x (virements internes)",
        "committed_rule": "écritures validées datées dans l'horizon, jamais ajustées",
        "categories_inflow": dict(categories_in),
        "categories_outflow": dict(categories_out),
        "estimated_rule": (
            "estimés exclus si l'historique exploitable est vide (INSUFFISANT_DATA)"
            if insufficient_data
            else "estimés dérivés de l'historique, ajustés par le scénario"
        ),
    }


def compute_forecast(
    *,
    as_of: date,
    horizon_days: int,
    scenario: Scenario,
    holdings: list[AccountHolding],
    committed_flows: list[DatedFlow],
    history: MonthlyHistory,
    settings: ForecastSettingsInput,
) -> ForecastResult:
    """Calcule la prévision consolidée et par compte (fonction pure)."""
    if horizon_days not in HORIZONS_DAYS:
        raise ForecastError(f"Horizon invalide : {horizon_days} (attendu parmi {HORIZONS_DAYS}).")
    if as_of < date(2000, 1, 1):  # garde-fou de cohérence, pas une règle métier
        raise ForecastError("Date de calcul incohérente.")
    if horizon_days < 1:  # inaccessible via HORIZONS_DAYS, défense en profondeur
        raise ForecastError("L'horizon doit être positif.")
    assumptions = SCENARIO_ASSUMPTIONS[scenario]

    opening_total = sum(h.balance_minor for h in holdings)
    horizon_end = as_of + timedelta(days=horizon_days)

    committed_in, committed_out, account_daily_net, committed_net_by_account = (
        _aggregate_committed_flows(
            as_of=as_of, horizon_end=horizon_end, committed_flows=committed_flows
        )
    )

    months_used = len(history.months)
    insufficient_data = months_used == 0
    avg_in = sum(m.inflow_minor for m in history.months) // months_used if months_used else 0
    avg_out = sum(m.outflow_minor for m in history.months) // months_used if months_used else 0
    estimated_in, estimated_out, beyond_in = _estimated_flows(
        as_of=as_of,
        horizon_days=horizon_days,
        assumptions=assumptions,
        avg_in=avg_in,
        avg_out=avg_out,
        insufficient_data=insufficient_data,
    )

    days, first_critical_date, lowest_balance, lowest_balance_date, global_status = _project_daily(
        as_of=as_of,
        horizon_days=horizon_days,
        opening_total=opening_total,
        committed_in=committed_in,
        committed_out=committed_out,
        estimated_in=estimated_in,
        estimated_out=estimated_out,
        settings=settings,
    )

    accounts = _project_accounts(
        as_of=as_of,
        horizon_days=horizon_days,
        holdings=holdings,
        account_daily_net=account_daily_net,
        committed_net_by_account=committed_net_by_account,
    )

    return ForecastResult(
        as_of=as_of,
        horizon_days=horizon_days,
        scenario=scenario,
        opening_total_minor=opening_total,
        status=global_status,
        days=days,
        accounts=accounts,
        first_critical_date=first_critical_date,
        lowest_balance_minor=lowest_balance,
        lowest_balance_date=lowest_balance_date,
        beyond_horizon_inflow_minor=beyond_in,
        beyond_horizon_outflow_minor=0,
        insufficient_data=insufficient_data,
        history_months_used=months_used,
        assumptions=_assumptions_payload(
            scenario=scenario,
            months_used=months_used,
            insufficient_data=insufficient_data,
            history=history,
        ),
    )


def _day_status(balance_minor: int, settings: ForecastSettingsInput) -> ForecastStatus:
    if balance_minor < settings.critical_floor_minor:
        return ForecastStatus.CRITIQUE
    if settings.warning_floor_minor is not None and balance_minor < settings.warning_floor_minor:
        return ForecastStatus.SOUS_SURVEILLANCE
    return ForecastStatus.SAIN

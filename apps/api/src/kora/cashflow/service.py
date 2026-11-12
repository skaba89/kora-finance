"""Service de prévision de trésorerie (Phase 3E) : alimentation du moteur, instantanés.

Séparation stricte : ce module ne fait qu'alimenter les structures pures du moteur
(`engine.py`) depuis la base, puis persister les résultats. Aucun calcul métier ici.

Trois sources, jamais mélangées (voir SPEC_PHASE_3E §2) :
- OBSERVE : soldes des comptes classe 5 hors 58x, écritures validées à `as_of` inclus ;
- ENGAGE  : lignes de trésorerie d'écritures validées MANUELLES datées dans l'horizon
  (les écritures d'origine CLOSING — à-nouveaux et contre-passations de clôture — sont
  exclues : elles restituent des soldes, elles ne créent pas de flux) ;
- ESTIME  : totaux mensuels des N mois complets précédant `as_of`, contrepartie
  hors trésorerie (les virements internes entre comptes de trésorerie sont exclus des
  deux côtés pour ne pas gonfler les encaissements et décaissements).

Toutes les lectures d'un calcul passent par `lecture_instantanee` (KF-05) : un seul
état de la base pour les soldes, les engagés et l'historique.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Subquery, and_, func, select
from sqlalchemy.orm import Session

from kora.cashflow import engine
from kora.cashflow.assumptions import (
    HISTORY_MONTHS,
    HORIZONS_DAYS,
    Scenario,
)
from kora.cashflow.engine import (
    AccountHolding,
    DatedFlow,
    ForecastResult,
    ForecastSettingsInput,
    MonthlyHistory,
    MonthTotals,
    is_treasury_account_number,
)
from kora.core.errors import BusinessRuleError, NotFoundError
from kora.db.snapshot import lecture_instantanee
from kora.models.accounting import Account
from kora.models.cashflow import CashflowSettings, CashflowSnapshot, CashflowSnapshotLine
from kora.models.ledger import EntryOrigin, EntryStatus, JournalEntry, JournalLine

DEFAULT_SETTINGS = ForecastSettingsInput(critical_floor_minor=0, warning_floor_minor=None)


@dataclass(frozen=True)
class ExcludedDraft:
    """Brouillon futur touchant la trésorerie : signalé, jamais projeté."""

    entry_date: date
    label: str
    net_treasury_minor: int


_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("411", "CLIENTS"),
    ("401", "FOURNISSEURS"),
    ("42", "PERSONNEL"),
    ("43", "ORGANISMES_SOCIAUX"),
    ("44", "ETAT"),
    ("45", "ASSOCIES"),
)


def cashflow_category(counterpart_number: str) -> str:
    """Catégorie de contrepartie d'un flux de trésorerie (traçabilité des hypothèses)."""
    for prefix, category in _CATEGORY_PREFIXES:
        if counterpart_number.startswith(prefix):
            return category
    return "AUTRES"


# ---------------------------------------------------------------------- alimentation


def _posted_lines_window(company_id: uuid.UUID, date_to: date) -> Subquery:
    """Sous-requête des lignes signées d'écritures validées jusqu'à date_to inclus."""
    return (
        select(
            JournalLine.account_id.label("account_id"),
            (JournalLine.debit - JournalLine.credit).label("signed"),
        )
        .join(
            JournalEntry,
            and_(
                JournalEntry.tenant_id == JournalLine.tenant_id,
                JournalEntry.id == JournalLine.entry_id,
            ),
        )
        .where(
            JournalLine.tenant_id == company_id,
            JournalEntry.status == EntryStatus.POSTED.value,
            JournalEntry.entry_date <= date_to,
        )
        .subquery()
    )


def load_holdings(
    snapshot_session: Session, company_id: uuid.UUID, as_of: date
) -> list[AccountHolding]:
    """Soldes observés : classe 5 hors 58x, actifs, écritures validées à as_of inclus."""
    lines = _posted_lines_window(company_id, as_of)
    rows = snapshot_session.execute(
        select(
            Account.id,
            Account.number,
            Account.label,
            func.coalesce(func.sum(lines.c.signed), 0),
        )
        .outerjoin(lines, lines.c.account_id == Account.id)
        .where(
            Account.tenant_id == company_id,
            Account.is_active.is_(True),
            Account.number.like("5%"),
            ~Account.number.like("58%"),
        )
        .group_by(Account.id, Account.number, Account.label)
        .order_by(Account.number)
    ).all()
    return [
        AccountHolding(account_id=row[0], number=row[1], label=row[2], balance_minor=row[3])
        for row in rows
    ]


def load_committed_flows(
    snapshot_session: Session, company_id: uuid.UUID, as_of: date, horizon_end: date
) -> list[DatedFlow]:
    """Flux engagés : trésorerie d'écritures validées manuelles datées (as_of, horizon]."""
    rows = snapshot_session.execute(
        select(
            JournalEntry.entry_date,
            JournalLine.account_id,
            JournalLine.debit - JournalLine.credit,
            JournalEntry.label,
        )
        .join(
            JournalEntry,
            and_(
                JournalEntry.tenant_id == JournalLine.tenant_id,
                JournalEntry.id == JournalLine.entry_id,
            ),
        )
        .join(
            Account,
            and_(
                Account.tenant_id == JournalLine.tenant_id,
                Account.id == JournalLine.account_id,
            ),
        )
        .where(
            JournalLine.tenant_id == company_id,
            JournalEntry.status == EntryStatus.POSTED.value,
            JournalEntry.origin == EntryOrigin.MANUAL.value,
            JournalEntry.entry_date > as_of,
            JournalEntry.entry_date <= horizon_end,
            Account.number.like("5%"),
            ~Account.number.like("58%"),
        )
        .order_by(JournalEntry.entry_date)
    ).all()
    return [
        DatedFlow(
            flow_date=row[0],
            account_id=row[1],
            amount_minor=row[2],
            label=row[3],
        )
        for row in rows
    ]


@dataclass(frozen=True)
class EntryFlow:
    """Flux de trésorerie d'une écriture validée, avec sa contrepartie principale."""

    flow_date: date
    treasury_in_minor: int  # Σ débits des lignes de trésorerie
    treasury_out_minor: int  # Σ crédits des lignes de trésorerie
    category: str


def _entry_flows(
    snapshot_session: Session, company_id: uuid.UUID, date_from: date, date_to: date
) -> list[EntryFlow]:
    """Flux de trésorerie réels des écritures validées (MANUAL) de la fenêtre.

    Une écriture n'est retenue que si elle touche la trésorerie (classe 5 hors 58x) ET
    comporte au moins une contrepartie non trésorerie : les virements internes purs ne
    sont ni encaissement ni décaissement. Origine CLOSING exclue (à-nouveaux : ils
    restituent des soldes, ils ne créent pas de flux). Sert à l'historique estimé
    (groupé par mois) et au réalisé de la comparaison prévisionnel/réalisé (par jour).
    """
    touching = (
        select(JournalLine.entry_id)
        .join(
            Account,
            and_(
                Account.tenant_id == JournalLine.tenant_id,
                Account.id == JournalLine.account_id,
            ),
        )
        .where(
            JournalLine.tenant_id == company_id,
            Account.number.like("5%"),
            ~Account.number.like("58%"),
        )
        .scalar_subquery()
    )
    entry_rows = snapshot_session.execute(
        select(JournalEntry.id, JournalEntry.entry_date).where(
            JournalEntry.tenant_id == company_id,
            JournalEntry.status == EntryStatus.POSTED.value,
            JournalEntry.origin == EntryOrigin.MANUAL.value,
            JournalEntry.entry_date >= date_from,
            JournalEntry.entry_date <= date_to,
            JournalEntry.id.in_(touching),
        )
    ).all()
    if not entry_rows:
        return []

    line_rows = snapshot_session.execute(
        select(
            JournalLine.entry_id,
            JournalLine.line_no,
            Account.number,
            JournalLine.debit,
            JournalLine.credit,
        )
        .join(
            Account,
            and_(
                Account.tenant_id == JournalLine.tenant_id,
                Account.id == JournalLine.account_id,
            ),
        )
        .where(
            JournalLine.tenant_id == company_id,
            JournalLine.entry_id.in_([row[0] for row in entry_rows]),
        )
        .order_by(JournalLine.entry_id, JournalLine.line_no)
    ).all()

    dates_by_entry = {row[0]: row[1] for row in entry_rows}
    per_entry: dict[uuid.UUID, list[tuple[str, int, int]]] = defaultdict(list)
    for entry_id, _line_no, number, debit, credit in line_rows:
        per_entry[entry_id].append((number, debit, credit))

    flows: list[EntryFlow] = []
    for entry_id, lines in per_entry.items():
        treasury_in = sum(
            debit for number, debit, _credit in lines if is_treasury_account_number(number)
        )
        treasury_out = sum(
            credit for number, _debit, credit in lines if is_treasury_account_number(number)
        )
        counterpart = next(
            (number for number, _debit, _credit in lines if not is_treasury_account_number(number)),
            None,
        )
        if counterpart is None:
            continue  # virement interne pur : ni encaissement ni décaissement
        flows.append(
            EntryFlow(
                flow_date=dates_by_entry[entry_id],
                treasury_in_minor=treasury_in,
                treasury_out_minor=treasury_out,
                category=cashflow_category(counterpart),
            )
        )
    return flows


def load_monthly_history(
    snapshot_session: Session, company_id: uuid.UUID, as_of: date
) -> MonthlyHistory:
    """Totaux mensuels des N mois complets précédant as_of (flux réels de trésorerie)."""
    first_of_month = as_of.replace(day=1)
    window_end = first_of_month - timedelta(days=1)  # dernier jour du mois précédent
    window_start = (first_of_month - timedelta(days=HISTORY_MONTHS * 31)).replace(day=1)

    monthly: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0})
    categories: dict[tuple[int, int], dict[str, dict[str, int]]] = defaultdict(
        lambda: {"in": defaultdict(int), "out": defaultdict(int)}
    )
    for flow in _entry_flows(snapshot_session, company_id, window_start, window_end):
        month_key = (flow.flow_date.year, flow.flow_date.month)
        monthly[month_key]["in"] += flow.treasury_in_minor
        monthly[month_key]["out"] += flow.treasury_out_minor
        categories[month_key]["in"][flow.category] += flow.treasury_in_minor
        categories[month_key]["out"][flow.category] += flow.treasury_out_minor

    months = tuple(
        MonthTotals(
            year=key[0],
            month=key[1],
            inflow_minor=totals["in"],
            outflow_minor=totals["out"],
            inflow_by_category=dict(categories[key]["in"]),
            outflow_by_category=dict(categories[key]["out"]),
        )
        for key, totals in sorted(monthly.items())
    )
    return MonthlyHistory(months)


def load_excluded_drafts(
    snapshot_session: Session, company_id: uuid.UUID, as_of: date, horizon_end: date
) -> list[ExcludedDraft]:
    """Brouillons futurs touchant la trésorerie : listés comme exclusions, jamais projetés."""
    rows = snapshot_session.execute(
        select(
            JournalEntry.entry_date,
            JournalEntry.label,
            func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0),
        )
        .join(
            JournalLine,
            and_(
                JournalLine.tenant_id == JournalEntry.tenant_id,
                JournalLine.entry_id == JournalEntry.id,
            ),
        )
        .join(
            Account,
            and_(Account.tenant_id == JournalLine.tenant_id, Account.id == JournalLine.account_id),
        )
        .where(
            JournalEntry.tenant_id == company_id,
            JournalEntry.status == EntryStatus.DRAFT.value,
            JournalEntry.entry_date > as_of,
            JournalEntry.entry_date <= horizon_end,
            Account.number.like("5%"),
            ~Account.number.like("58%"),
        )
        .group_by(JournalEntry.id, JournalEntry.entry_date, JournalEntry.label)
        .order_by(JournalEntry.entry_date)
    ).all()
    return [ExcludedDraft(row[0], row[1], row[2]) for row in rows]


# ----------------------------------------------------------------------- paramétrage


def load_settings_row(session: Session, company_id: uuid.UUID) -> CashflowSettings | None:
    """Ligne de paramétrage du dossier, ou None si jamais paramétré (aucune écriture)."""
    settings_id = _settings_id(session, company_id)
    return session.get(CashflowSettings, settings_id) if settings_id else None


def get_settings_or_default(session: Session, company_id: uuid.UUID) -> ForecastSettingsInput:
    """Seuils effectifs pour le moteur : valeurs stockées si présentes, défauts sinon."""
    row = load_settings_row(session, company_id)
    if row is None:
        return DEFAULT_SETTINGS
    return ForecastSettingsInput(
        critical_floor_minor=row.critical_floor_minor,
        warning_floor_minor=row.warning_floor_minor,
    )


def _settings_id(session: Session, company_id: uuid.UUID) -> uuid.UUID | None:
    return session.execute(
        select(CashflowSettings.id).where(CashflowSettings.tenant_id == company_id)
    ).scalar_one_or_none()


def update_settings(
    session: Session,
    company_id: uuid.UUID,
    *,
    critical_floor_minor: int,
    warning_floor_minor: int | None,
    default_horizon_days: int,
    default_scenario: str,
) -> CashflowSettings:
    settings_id = _settings_id(session, company_id)
    row = session.get(CashflowSettings, settings_id) if settings_id else None
    if row is None:
        row = CashflowSettings(tenant_id=company_id)
        session.add(row)
    row.critical_floor_minor = critical_floor_minor
    row.warning_floor_minor = warning_floor_minor
    row.default_horizon_days = default_horizon_days
    row.default_scenario = default_scenario
    session.flush()
    return row


# ------------------------------------------------------------------------- prévision


def build_forecast(
    session: Session,
    company_id: uuid.UUID,
    *,
    horizon_days: int,
    scenario: Scenario,
    as_of: date | None = None,
) -> tuple[ForecastResult, list[ExcludedDraft]]:
    """Calcule la prévision dans un instantané REPEATABLE READ, puis retourne résultat
    et exclusions. `as_of` par défaut : date UTC du jour (la saisie comptable est datée
    en jours ; l'heure locale du dossier n'influe pas sur la projection journalière)."""
    if horizon_days not in HORIZONS_DAYS:
        raise BusinessRuleError(f"Horizon non pris en charge : {horizon_days}.")
    as_of = as_of or datetime.now(UTC).date()
    horizon_end = as_of + timedelta(days=horizon_days)
    settings = get_settings_or_default(session, company_id)

    with lecture_instantanee(company_id) as snap:
        holdings = load_holdings(snap, company_id, as_of)
        committed = load_committed_flows(snap, company_id, as_of, horizon_end)
        history = load_monthly_history(snap, company_id, as_of)
        drafts = load_excluded_drafts(snap, company_id, as_of, horizon_end)

    result = engine.compute_forecast(
        as_of=as_of,
        horizon_days=horizon_days,
        scenario=scenario,
        holdings=holdings,
        committed_flows=committed,
        history=history,
        settings=settings,
    )
    return result, drafts


def create_snapshot(
    session: Session,
    company_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    horizon_days: int,
    scenario: Scenario,
) -> CashflowSnapshot:
    """Fige la prévision courante : en-tête + une ligne par jour et par source."""
    result, _drafts = build_forecast(
        session, company_id, horizon_days=horizon_days, scenario=scenario
    )
    snapshot = CashflowSnapshot(
        tenant_id=company_id,
        generated_by_user_id=actor_user_id,
        as_of=result.as_of,
        horizon_days=result.horizon_days,
        scenario=result.scenario.value,
        opening_total_minor=result.opening_total_minor,
        status=result.status.value,
        first_critical_date=result.first_critical_date,
        lowest_balance_minor=result.lowest_balance_minor,
        lowest_balance_date=result.lowest_balance_date,
        beyond_horizon_inflow_minor=result.beyond_horizon_inflow_minor,
        beyond_horizon_outflow_minor=result.beyond_horizon_outflow_minor,
        insufficient_data=result.insufficient_data,
        history_months_used=result.history_months_used,
        assumptions_jsonb={
            **result.assumptions,
            "categories": _history_categories(result),
        },
    )
    session.add(snapshot)
    session.flush()

    session.add(
        CashflowSnapshotLine(
            tenant_id=company_id,
            snapshot_id=snapshot.id,
            flow_date=result.as_of,
            source="OBSERVE",
            inflow_minor=0,
            outflow_minor=0,
            projected_balance_minor=result.opening_total_minor,
        )
    )
    for day in result.days:
        if day.committed_inflow_minor or day.committed_outflow_minor:
            session.add(
                CashflowSnapshotLine(
                    tenant_id=company_id,
                    snapshot_id=snapshot.id,
                    flow_date=day.flow_date,
                    source="ENGAGE",
                    inflow_minor=day.committed_inflow_minor,
                    outflow_minor=day.committed_outflow_minor,
                    projected_balance_minor=day.balance_minor,
                )
            )
        if day.estimated_inflow_minor or day.estimated_outflow_minor:
            session.add(
                CashflowSnapshotLine(
                    tenant_id=company_id,
                    snapshot_id=snapshot.id,
                    flow_date=day.flow_date,
                    source="ESTIME",
                    inflow_minor=day.estimated_inflow_minor,
                    outflow_minor=day.estimated_outflow_minor,
                    projected_balance_minor=day.balance_minor,
                )
            )
            # Journée sans aucun flux projeté : la ligne ESTIME nulle ancre le solde
            # projeté du jour dans le snapshot (lecture graphique sans re-calcul).
        elif not (day.committed_inflow_minor or day.committed_outflow_minor):
            session.add(
                CashflowSnapshotLine(
                    tenant_id=company_id,
                    snapshot_id=snapshot.id,
                    flow_date=day.flow_date,
                    source="ESTIME",
                    inflow_minor=0,
                    outflow_minor=0,
                    projected_balance_minor=day.balance_minor,
                )
            )
    session.flush()
    return snapshot


def _history_categories(result: ForecastResult) -> dict[str, object]:
    """Synthèse des catégories d'historique, sérialisée par le moteur dans ses hypothèses."""
    return {
        "inflow": result.assumptions.get("categories_inflow", {}),
        "outflow": result.assumptions.get("categories_outflow", {}),
    }


def get_snapshot(
    session: Session, company_id: uuid.UUID, snapshot_id: uuid.UUID
) -> CashflowSnapshot:
    snapshot = session.get(CashflowSnapshot, snapshot_id)
    if snapshot is None or snapshot.tenant_id != company_id:
        raise NotFoundError("Instantané introuvable.")
    return snapshot


# ------------------------------------------------------------------ prévision vs réalisé


@dataclass(frozen=True)
class VsActualDay:
    flow_date: date
    forecast_net_minor: int  # ENGAGE + ESTIME du snapshot (négatif = décaissement net)
    actual_net_minor: int
    variance_minor: int  # réalisé - prévision


@dataclass(frozen=True)
class VsActualReport:
    snapshot_id: uuid.UUID
    compared_through: date  # dernier jour comparé
    forecast_total_net_minor: int
    actual_total_net_minor: int
    variance_minor: int
    days: list[VsActualDay]
    top_deviations: list[VsActualDay]  # 10 plus forts écarts absolus, antéchronologiques


def compare_snapshot_to_actual(
    snapshot_session: Session, company_id: uuid.UUID, snapshot: CashflowSnapshot
) -> VsActualReport:
    """Réalisé postérieur à `as_of` du snapshot, limité à son horizon et à aujourd'hui.

    Le réalisé applique les mêmes règles que l'historique estimé (écritures validées
    manuelles, virements internes exclus) : l'écart mesure la qualité de la prévision,
    pas une différence de périmètre.
    """
    today = datetime.now(UTC).date()
    horizon_end = snapshot.as_of + timedelta(days=snapshot.horizon_days)
    compared_through = min(today, horizon_end)
    if compared_through <= snapshot.as_of:
        return VsActualReport(
            snapshot_id=snapshot.id,
            compared_through=snapshot.as_of,
            forecast_total_net_minor=0,
            actual_total_net_minor=0,
            variance_minor=0,
            days=[],
            top_deviations=[],
        )

    lines = snapshot_session.execute(
        select(
            CashflowSnapshotLine.flow_date,
            CashflowSnapshotLine.source,
            CashflowSnapshotLine.inflow_minor,
            CashflowSnapshotLine.outflow_minor,
        ).where(
            CashflowSnapshotLine.tenant_id == company_id,
            CashflowSnapshotLine.snapshot_id == snapshot.id,
            CashflowSnapshotLine.source.in_(("ENGAGE", "ESTIME")),
            CashflowSnapshotLine.flow_date > snapshot.as_of,
            CashflowSnapshotLine.flow_date <= compared_through,
        )
    ).all()
    forecast_net: dict[date, int] = defaultdict(int)
    for flow_date, _source, inflow, outflow in lines:
        forecast_net[flow_date] += inflow - outflow

    actual_net: dict[date, int] = defaultdict(int)
    for flow in _entry_flows(snapshot_session, company_id, snapshot.as_of, compared_through):
        actual_net[flow.flow_date] += flow.treasury_in_minor - flow.treasury_out_minor

    days: list[VsActualDay] = []
    forecast_total = 0
    actual_total = 0
    for offset in range(1, (compared_through - snapshot.as_of).days + 1):
        day = snapshot.as_of + timedelta(days=offset)
        forecast_day = forecast_net.get(day, 0)
        actual_day = actual_net.get(day, 0)
        forecast_total += forecast_day
        actual_total += actual_day
        days.append(
            VsActualDay(
                flow_date=day,
                forecast_net_minor=forecast_day,
                actual_net_minor=actual_day,
                variance_minor=actual_day - forecast_day,
            )
        )
    top = sorted(days, key=lambda d: abs(d.variance_minor), reverse=True)[:10]
    return VsActualReport(
        snapshot_id=snapshot.id,
        compared_through=compared_through,
        forecast_total_net_minor=forecast_total,
        actual_total_net_minor=actual_total,
        variance_minor=actual_total - forecast_total,
        days=days,
        top_deviations=top,
    )

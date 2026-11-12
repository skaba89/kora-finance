"""Prévision de trésorerie 30/60/90 jours (Phase 3E).

Consultation (moteur + instantanés + réalisé) : permission `treasury:read` — la
prévision prolonge les comptes de trésorerie (3A) et leurs mouvements ; visible
pour les rôles de lecture. Paramétrage des seuils et figeage d'un instantané :
`treasury:manage`, chaque écriture inscrite au journal d'audit.

La prévision ne modifie jamais la comptabilité : toutes les routes de ce routeur
sont des lectures, hormis le paramétrage des seuils et le figeage des instantanés.
"""

import uuid
from datetime import date
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from kora.api.v1.common import TENANT_ERRORS, Money, SignedMoney
from kora.audit.service import record_event
from kora.auth.deps import Ctx, DbSession
from kora.cashflow import exports as cashflow_exports
from kora.cashflow import service
from kora.cashflow.assumptions import Scenario
from kora.cashflow.engine import (
    AccountProjection,
    DailyProjection,
    ForecastResult,
)
from kora.cashflow.service import ExcludedDraft
from kora.core.errors import BusinessRuleError
from kora.models.cashflow import CashflowSettings, CashflowSnapshot
from kora.tenancy.deps import TreasuryManage, TreasuryRead

router = APIRouter(prefix="/companies/{company_id}", tags=["trésorerie prévisionnelle"])

_ERRORS = {**TENANT_ERRORS, 422: TENANT_ERRORS[404]}

ScenarioQuery = Annotated[
    Scenario,
    Query(
        alias="scenario",
        description="Scénario appliqué aux flux estimés (les flux engagés ne sont jamais ajustés)",
    ),
]
HorizonQuery = Annotated[int, Query(ge=30, le=90, description="Horizon en jours (30, 60 ou 90)")]


def _validate_horizon(horizon: int) -> int:
    if horizon not in (30, 60, 90):
        raise BusinessRuleError("L'horizon doit valoir 30, 60 ou 90 jours.")
    return horizon


# Statuts et scénarios exposés : Literal pour un contrat OpenAPI précis (unions TS).
ForecastStatusLiteral = Literal["SAIN", "SOUS_SURVEILLANCE", "CRITIQUE"]
ScenarioLiteral = Literal["OPTIMISTE", "NEUTRE", "PRUDENT"]


class CoefficientOut(BaseModel):
    """Coefficient de scénario appliqué aux flux estimés (numérateur/dénominateur entiers)."""

    numerator: int
    denominator: int


class AssumptionsOut(BaseModel):
    """Hypothèses sérialisées d'un calcul (identiques à celles figées dans les instantanés)."""

    scenario: ScenarioLiteral
    inflow_coefficient: CoefficientOut
    outflow_coefficient: CoefficientOut
    inflow_delay_days: int
    outflow_advance_days: int
    history_months_used: int
    estimation_method: str
    rounding: str


class DailyProjectionOut(BaseModel):
    flow_date: date
    inflow: Money
    outflow: Money
    balance: SignedMoney
    status: ForecastStatusLiteral
    committed_inflow: Money
    committed_outflow: Money
    estimated_inflow: Money
    estimated_outflow: Money

    @classmethod
    def of(cls, day: DailyProjection) -> "DailyProjectionOut":
        return cls(
            flow_date=day.flow_date,
            inflow=day.inflow_minor,
            outflow=day.outflow_minor,
            balance=day.balance_minor,
            status=day.status.value,
            committed_inflow=day.committed_inflow_minor,
            committed_outflow=day.committed_outflow_minor,
            estimated_inflow=day.estimated_inflow_minor,
            estimated_outflow=day.estimated_outflow_minor,
        )


class AccountProjectionOut(BaseModel):
    account_id: uuid.UUID
    number: str
    label: str
    opening: SignedMoney
    committed_net: SignedMoney
    projected: SignedMoney
    balances_at_marks: dict[int, SignedMoney]

    @classmethod
    def of(cls, account: AccountProjection) -> "AccountProjectionOut":
        return cls(
            account_id=account.account_id,
            number=account.number,
            label=account.label,
            opening=account.opening_minor,
            committed_net=account.committed_net_minor,
            projected=account.projected_minor,
            balances_at_marks=account.balances_at_marks,
        )


class ExcludedDraftOut(BaseModel):
    entry_date: date
    label: str
    net_treasury: SignedMoney

    @classmethod
    def of(cls, draft: ExcludedDraft) -> "ExcludedDraftOut":
        return cls(
            entry_date=draft.entry_date, label=draft.label, net_treasury=draft.net_treasury_minor
        )


class ForecastOut(BaseModel):
    as_of: date
    horizon_days: int
    scenario: ScenarioLiteral
    opening_total: SignedMoney
    status: ForecastStatusLiteral
    first_critical_date: date | None
    lowest_balance: SignedMoney
    lowest_balance_date: date
    beyond_horizon_inflow: Money
    beyond_horizon_outflow: Money
    insufficient_data: bool
    history_months_used: int
    assumptions: AssumptionsOut
    days: list[DailyProjectionOut]
    accounts: list[AccountProjectionOut]
    excluded_drafts: list[ExcludedDraftOut]

    @classmethod
    def of(cls, result: ForecastResult, drafts: list[ExcludedDraft]) -> "ForecastOut":
        return cls(
            as_of=result.as_of,
            horizon_days=result.horizon_days,
            scenario=result.scenario.value,
            opening_total=result.opening_total_minor,
            status=result.status.value,
            first_critical_date=result.first_critical_date,
            lowest_balance=result.lowest_balance_minor,
            lowest_balance_date=result.lowest_balance_date,
            beyond_horizon_inflow=result.beyond_horizon_inflow_minor,
            beyond_horizon_outflow=result.beyond_horizon_outflow_minor,
            insufficient_data=result.insufficient_data,
            history_months_used=result.history_months_used,
            assumptions=AssumptionsOut.model_validate(result.assumptions),
            days=[DailyProjectionOut.of(day) for day in result.days],
            accounts=[AccountProjectionOut.of(account) for account in result.accounts],
            excluded_drafts=[ExcludedDraftOut.of(draft) for draft in drafts],
        )


@router.get("/cashflow/forecast", responses=_ERRORS)
def forecast(
    tenant: TreasuryRead,
    db: DbSession,
    horizon: HorizonQuery = 90,
    scenario: ScenarioQuery = Scenario.NEUTRE,
    as_of: Annotated[
        date | None, Query(description="Date de calcul (défaut : aujourd'hui)")
    ] = None,
) -> ForecastOut:
    """Prévision consolidée et par compte : soldes observés, flux engagés, flux estimés."""
    _validate_horizon(horizon)
    result, drafts = service.build_forecast(
        db, tenant.company_id, horizon_days=horizon, scenario=scenario, as_of=as_of
    )
    return ForecastOut.of(result, drafts)


@router.get("/cashflow/forecast/export", responses=_ERRORS)
def forecast_export(
    tenant: TreasuryRead,
    db: DbSession,
    ctx: Ctx,
    file_format: Annotated[Literal["pdf", "xlsx"], Query(alias="format")],
    horizon: HorizonQuery = 90,
    scenario: ScenarioQuery = Scenario.NEUTRE,
) -> Response:
    """Export PDF ou Excel de la prévision (inscrit au journal d'audit)."""
    _validate_horizon(horizon)
    exported = cashflow_exports.render_forecast_export(
        db,
        tenant.company_id,
        horizon_days=horizon,
        scenario=scenario,
        file_format=file_format,
        actor_user_id=tenant.user.id,
        ip_address=ctx.ip_address,
    )
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{exported.filename}"; '
                f"filename*=UTF-8''{quote(exported.filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


class SettingsOut(BaseModel):
    critical_floor: Money
    warning_floor: Money | None
    default_horizon_days: int
    default_scenario: ScenarioLiteral


class SettingsIn(BaseModel):
    critical_floor_minor: int = Field(ge=0, description="Seuil critique, unités mineures")
    warning_floor_minor: int | None = Field(
        default=None,
        ge=0,
        description="Seuil de surveillance (>= seuil critique), NULL pour désactiver",
    )
    default_horizon_days: int = Field(default=90)
    default_scenario: Scenario = Scenario.NEUTRE


def _settings_out(row: CashflowSettings | None) -> SettingsOut:
    """Valeurs effectives : stockées si présentes, défauts du modèle sinon."""
    return SettingsOut(
        critical_floor=row.critical_floor_minor if row else 0,
        warning_floor=row.warning_floor_minor if row else None,
        default_horizon_days=row.default_horizon_days if row else 90,
        default_scenario=row.default_scenario if row else "NEUTRE",
    )


@router.get("/cashflow/settings", responses=_ERRORS)
def get_settings(tenant: TreasuryRead, db: DbSession) -> SettingsOut:
    """Seuils d'alerte effectifs (valeurs par défaut si jamais paramétrés)."""
    row = service.load_settings_row(db, tenant.company_id)
    return _settings_out(row)


@router.put("/cashflow/settings", responses=_ERRORS)
def put_settings(payload: SettingsIn, tenant: TreasuryManage, db: DbSession) -> SettingsOut:
    """Met à jour les seuils et défauts d'affichage de la prévision (audité)."""
    if (
        payload.warning_floor_minor is not None
        and payload.warning_floor_minor < payload.critical_floor_minor
    ):
        raise BusinessRuleError(
            "Le seuil de surveillance doit rester supérieur ou égal au seuil critique."
        )
    _validate_horizon(payload.default_horizon_days)
    row = service.update_settings(
        db,
        tenant.company_id,
        critical_floor_minor=payload.critical_floor_minor,
        warning_floor_minor=payload.warning_floor_minor,
        default_horizon_days=payload.default_horizon_days,
        default_scenario=payload.default_scenario.value,
    )
    record_event(
        db,
        action="cashflow.settings.update",
        entity_type="cashflow_settings",
        entity_id=row.id,
        payload={
            "critical_floor_minor": row.critical_floor_minor,
            "warning_floor_minor": row.warning_floor_minor,
            "default_horizon_days": row.default_horizon_days,
            "default_scenario": row.default_scenario,
        },
        actor_user_id=tenant.user.id,
    )
    return SettingsOut(
        critical_floor=row.critical_floor_minor,
        warning_floor=row.warning_floor_minor,
        default_horizon_days=row.default_horizon_days,
        default_scenario=row.default_scenario,
    )


class SnapshotOut(BaseModel):
    id: uuid.UUID
    generated_at: str
    as_of: date
    horizon_days: int
    scenario: ScenarioLiteral
    opening_total: SignedMoney
    status: ForecastStatusLiteral
    first_critical_date: date | None
    lowest_balance: SignedMoney
    lowest_balance_date: date
    insufficient_data: bool
    history_months_used: int
    assumptions: AssumptionsOut


@router.get("/cashflow/snapshots", responses=_ERRORS)
def list_snapshots(
    tenant: TreasuryRead,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SnapshotOut]:
    """Historique des instantanés figés, du plus récent au plus ancien."""
    rows = (
        db.execute(
            select(CashflowSnapshot)
            .where(CashflowSnapshot.tenant_id == tenant.company_id)
            .order_by(CashflowSnapshot.generated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        SnapshotOut(
            id=row.id,
            generated_at=row.generated_at.isoformat(),
            as_of=row.as_of,
            horizon_days=row.horizon_days,
            scenario=row.scenario,
            opening_total=row.opening_total_minor,
            status=row.status,
            first_critical_date=row.first_critical_date,
            lowest_balance=row.lowest_balance_minor,
            lowest_balance_date=row.lowest_balance_date,
            insufficient_data=row.insufficient_data,
            history_months_used=row.history_months_used,
            assumptions=AssumptionsOut.model_validate(row.assumptions_jsonb),
        )
        for row in rows
    ]


@router.post("/cashflow/snapshots", responses=_ERRORS, status_code=201)
def create_snapshot(
    tenant: TreasuryManage, db: DbSession, scenario: ScenarioQuery = Scenario.NEUTRE
) -> SnapshotOut:
    """Fige la prévision courante en un instantané (base du prévisionnel vs réalisé)."""
    snapshot = service.create_snapshot(
        db,
        tenant.company_id,
        actor_user_id=tenant.user.id,
        horizon_days=90,
        scenario=scenario,
    )
    record_event(
        db,
        action="cashflow.snapshot.create",
        entity_type="cashflow_snapshot",
        entity_id=snapshot.id,
        payload={"as_of": snapshot.as_of.isoformat(), "scenario": snapshot.scenario},
        actor_user_id=tenant.user.id,
    )
    return SnapshotOut(
        id=snapshot.id,
        generated_at=snapshot.generated_at.isoformat(),
        as_of=snapshot.as_of,
        horizon_days=snapshot.horizon_days,
        scenario=snapshot.scenario,
        opening_total=snapshot.opening_total_minor,
        status=snapshot.status,
        first_critical_date=snapshot.first_critical_date,
        lowest_balance=snapshot.lowest_balance_minor,
        lowest_balance_date=snapshot.lowest_balance_date,
        insufficient_data=snapshot.insufficient_data,
        history_months_used=snapshot.history_months_used,
        assumptions=AssumptionsOut.model_validate(snapshot.assumptions_jsonb),
    )


class VsActualDayOut(BaseModel):
    flow_date: date
    forecast_net: SignedMoney
    actual_net: SignedMoney
    variance: SignedMoney


class VsActualOut(BaseModel):
    snapshot_id: uuid.UUID
    compared_through: date
    forecast_total_net: SignedMoney
    actual_total_net: SignedMoney
    variance: SignedMoney
    days: list[VsActualDayOut]
    top_deviations: list[VsActualDayOut]


@router.get("/cashflow/snapshots/{snapshot_id}/vs-actual", responses=_ERRORS)
def snapshot_vs_actual(snapshot_id: uuid.UUID, tenant: TreasuryRead, db: DbSession) -> VsActualOut:
    """Compare un instantané au réalisé postérieur (écritures validées)."""
    snapshot = service.get_snapshot(db, tenant.company_id, snapshot_id)
    report = service.compare_snapshot_to_actual(db, tenant.company_id, snapshot)
    return VsActualOut(
        snapshot_id=report.snapshot_id,
        compared_through=report.compared_through,
        forecast_total_net=report.forecast_total_net_minor,
        actual_total_net=report.actual_total_net_minor,
        variance=report.variance_minor,
        days=[
            VsActualDayOut(
                flow_date=day.flow_date,
                forecast_net=day.forecast_net_minor,
                actual_net=day.actual_net_minor,
                variance=day.variance_minor,
            )
            for day in report.days
        ],
        top_deviations=[
            VsActualDayOut(
                flow_date=day.flow_date,
                forecast_net=day.forecast_net_minor,
                actual_net=day.actual_net_minor,
                variance=day.variance_minor,
            )
            for day in report.top_deviations
        ],
    )

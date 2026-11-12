"""Tables tenant de la prévision de trésorerie : paramétrage, instantanés, lignes (Phase 3E).

Garanties portées par la base (migration 20261112_0011) :
- isolation par RLS (ENABLE + FORCE + policy tenant_isolation), comme toutes les tables tenant ;
- horizons limités à 30/60/90 jours et scénarios fermés par contraintes CHECK ;
- les flux sont des montants positifs : le signe n'existe que sur les soldes ;
- les lignes d'un instantané disparaissent avec lui (CASCADE).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, updated_at_column, uuid_pk


class CashflowSettings(Base):
    """Seuils d'alerte et défauts d'affichage de la prévision (une ligne par dossier).

    `critical_floor_minor` : sous ce solde projeté, la journée est CRITIQUE.
    `warning_floor_minor` : si renseigné, doit rester >= critical_floor (la surveillance
    précède la critique) ; NULL désactive l'alerte intermédiaire.
    """

    __tablename__ = "cashflow_settings"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    critical_floor_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    warning_floor_minor: Mapped[int | None] = mapped_column(BigInteger)
    default_horizon_days: Mapped[int] = mapped_column(SmallInteger, server_default="90")
    default_scenario: Mapped[str] = mapped_column(String(16), server_default="NEUTRE")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_cashflow_settings_tenant_id"),
        UniqueConstraint("tenant_id", "id", name="uq_cashflow_settings_tenant_id_id"),
        CheckConstraint("critical_floor_minor >= 0", name="critical_floor_non_negative"),
        CheckConstraint(
            "warning_floor_minor IS NULL OR warning_floor_minor >= critical_floor_minor",
            name="warning_above_critical",
        ),
        CheckConstraint("default_horizon_days IN (30, 60, 90)", name="default_horizon_valid"),
        CheckConstraint(
            "default_scenario IN ('OPTIMISTE', 'NEUTRE', 'PRUDENT')", name="default_scenario_valid"
        ),
    )


class CashflowSnapshot(Base):
    """Instantané de prévision figé : base de la comparaison prévisionnel/réalisé.

    `assumptions_jsonb` porte la copie intégrale des hypothèses du calcul (scénario,
    coefficients, fenêtre d'historique, méthode, exclusions) : un snapshot se lit et
    s'audite sans ré-exécuter le moteur.
    """

    __tablename__ = "cashflow_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    as_of: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(SmallInteger)
    scenario: Mapped[str] = mapped_column(String(16))
    opening_total_minor: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24))
    first_critical_date: Mapped[date | None] = mapped_column(Date)
    lowest_balance_minor: Mapped[int] = mapped_column(BigInteger)
    lowest_balance_date: Mapped[date] = mapped_column(Date)
    beyond_horizon_inflow_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    beyond_horizon_outflow_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    insufficient_data: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    history_months_used: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    assumptions_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cashflow_snapshots_tenant_id_id"),
        CheckConstraint("horizon_days IN (30, 60, 90)", name="horizon_valid"),
        CheckConstraint("scenario IN ('OPTIMISTE', 'NEUTRE', 'PRUDENT')", name="scenario_valid"),
        CheckConstraint("status IN ('SAIN', 'SOUS_SURVEILLANCE', 'CRITIQUE')", name="status_valid"),
        Index("ix_cashflow_snapshots_tenant_generated", "tenant_id", "generated_at"),
    )


class CashflowSnapshotLine(Base):
    """Une ligne par jour et par source de l'horizon d'un instantané.

    Source OBSERVE : la seule ligne d'ancrage (jour `as_of`, flux nuls, solde d'ouverture).
    Sources ENGAGE et ESTIME : flux journaliers projetés ; `projected_balance_minor`
    répète le solde consolidé fin de journée (identique sur les lignes du même jour).
    """

    __tablename__ = "cashflow_snapshot_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    snapshot_id: Mapped[uuid.UUID]
    flow_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(8))
    inflow_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    outflow_minor: Mapped[int] = mapped_column(BigInteger, server_default="0")
    projected_balance_minor: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "snapshot_id", "flow_date", "source", name="uq_cashflow_lines_day_source"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_cashflow_lines_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["cashflow_snapshots.tenant_id", "cashflow_snapshots.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("source IN ('OBSERVE', 'ENGAGE', 'ESTIME')", name="source_valid"),
        CheckConstraint("inflow_minor >= 0 AND outflow_minor >= 0", name="flows_non_negative"),
        Index("ix_cashflow_lines_tenant_date", "tenant_id", "flow_date"),
    )

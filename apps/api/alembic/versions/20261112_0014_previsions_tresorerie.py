"""Prévision de trésorerie : seuils, instantanés et lignes (Phase 3E).

Révision : 0014
Parente  : 0013 (rapprochement bancaire 3C) — renumérotée depuis 0011 : les
révisions 0011/0012/0013 (comptes financiers 3A, relevés 3B, unicité 3C) sont
arrivées sur `main` entre-temps.

Trois tables tenant avec RLS activé, forcé et policy `tenant_isolation` (convention
des migrations 0002/0003/0005) :
- `cashflow_settings`      : seuils d'alerte et défauts d'affichage (une ligne par dossier) ;
- `cashflow_snapshots`     : instantanés de prévision figés (prévisionnel vs réalisé) ;
- `cashflow_snapshot_lines`: une ligne par jour et par source de l'horizon figé.

Les clés étrangères vers les cibles multi-tenant sont composites (tenant_id, id) afin
qu'aucune référence ne franchisse les dossiers, comme dans la comptabilité générale
(migration 0005). Descente : suppression des trois tables dans l'ordre inverse des
dépendances.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cashflow_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("critical_floor_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("warning_floor_minor", sa.BigInteger(), nullable=True),
        sa.Column("default_horizon_days", sa.SmallInteger(), server_default="90", nullable=False),
        sa.Column("default_scenario", sa.String(16), server_default="NEUTRE", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name=op.f("fk_cashflow_settings_tenant_id_companies"),
        ),
        sa.CheckConstraint("critical_floor_minor >= 0", name="critical_floor_non_negative"),
        sa.CheckConstraint(
            "warning_floor_minor IS NULL OR warning_floor_minor >= critical_floor_minor",
            name="warning_above_critical",
        ),
        sa.CheckConstraint("default_horizon_days IN (30, 60, 90)", name="default_horizon_valid"),
        sa.CheckConstraint(
            "default_scenario IN ('OPTIMISTE', 'NEUTRE', 'PRUDENT')", name="default_scenario_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        op.f("uq_cashflow_settings_tenant_id"), "cashflow_settings", ["tenant_id"]
    )
    op.create_unique_constraint(
        op.f("uq_cashflow_settings_tenant_id_id"), "cashflow_settings", ["tenant_id", "id"]
    )

    op.create_table(
        "cashflow_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.SmallInteger(), nullable=False),
        sa.Column("scenario", sa.String(16), nullable=False),
        sa.Column("opening_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("first_critical_date", sa.Date(), nullable=True),
        sa.Column("lowest_balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("lowest_balance_date", sa.Date(), nullable=False),
        sa.Column(
            "beyond_horizon_inflow_minor", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "beyond_horizon_outflow_minor", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "insufficient_data", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("history_months_used", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("assumptions_jsonb", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name=op.f("fk_cashflow_snapshots_tenant_id_companies"),
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_user_id"],
            ["users.id"],
            name=op.f("fk_cashflow_snapshots_generated_by_user_id_users"),
        ),
        sa.CheckConstraint("horizon_days IN (30, 60, 90)", name="horizon_valid"),
        sa.CheckConstraint("scenario IN ('OPTIMISTE', 'NEUTRE', 'PRUDENT')", name="scenario_valid"),
        sa.CheckConstraint(
            "status IN ('SAIN', 'SOUS_SURVEILLANCE', 'CRITIQUE')", name="status_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        op.f("uq_cashflow_snapshots_tenant_id_id"), "cashflow_snapshots", ["tenant_id", "id"]
    )
    op.create_index(
        "ix_cashflow_snapshots_tenant_generated",
        "cashflow_snapshots",
        ["tenant_id", "generated_at"],
    )

    op.create_table(
        "cashflow_snapshot_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("flow_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("inflow_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("outflow_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("projected_balance_minor", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["cashflow_snapshots.tenant_id", "cashflow_snapshots.id"],
            ondelete="CASCADE",
            name=op.f("fk_cashflow_snapshot_lines_tenant_id_snapshot_id"),
        ),
        sa.CheckConstraint("source IN ('OBSERVE', 'ENGAGE', 'ESTIME')", name="source_valid"),
        sa.CheckConstraint("inflow_minor >= 0 AND outflow_minor >= 0", name="flows_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        op.f("uq_cashflow_lines_day_source"),
        "cashflow_snapshot_lines",
        ["tenant_id", "snapshot_id", "flow_date", "source"],
    )
    op.create_unique_constraint(
        op.f("uq_cashflow_lines_tenant_id_id"), "cashflow_snapshot_lines", ["tenant_id", "id"]
    )
    op.create_index(
        "ix_cashflow_lines_tenant_date", "cashflow_snapshot_lines", ["tenant_id", "flow_date"]
    )

    # Isolation par dossier : identique à toutes les tables tenant du référentiel.
    for table in ("cashflow_settings", "cashflow_snapshots", "cashflow_snapshot_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = kora_current_tenant()) "
            "WITH CHECK (tenant_id = kora_current_tenant())"
        )


def downgrade() -> None:
    for table in ("cashflow_snapshot_lines", "cashflow_snapshots", "cashflow_settings"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_cashflow_lines_tenant_date", table_name="cashflow_snapshot_lines")
    op.drop_table("cashflow_snapshot_lines")
    op.drop_index("ix_cashflow_snapshots_tenant_generated", table_name="cashflow_snapshots")
    op.drop_table("cashflow_snapshots")
    op.drop_table("cashflow_settings")

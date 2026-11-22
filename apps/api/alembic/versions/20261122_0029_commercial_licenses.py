"""Persistance additive des périodes commerciales avec isolation tenant."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ExcludeConstraint

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commercial_license_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("offer_code", sa.String(64), nullable=False),
        sa.Column("offer_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("suspended", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commercial_license_periods")),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(
            ["offer_code", "offer_version"],
            ["commercial_offer_versions.code", "commercial_offer_versions.version"],
        ),
        sa.CheckConstraint("ends_on > starts_on", name="dates_ordered"),
        sa.CheckConstraint("kind IN ('trial', 'paid')", name="kind_valid"),
        ExcludeConstraint(
            ("tenant_id", "="),
            (sa.text("daterange(starts_on, ends_on, '[)')"), "&&"),
            name="commercial_license_periods_no_overlap",
            using="gist",
        ),
    )
    op.create_index(
        "ix_commercial_license_periods_tenant_id", "commercial_license_periods", ["tenant_id"]
    )
    op.execute("ALTER TABLE commercial_license_periods ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE commercial_license_periods FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON commercial_license_periods "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )
    op.execute("REVOKE INSERT, UPDATE, DELETE ON commercial_license_periods FROM kora_app")


def downgrade() -> None:
    op.drop_table("commercial_license_periods")

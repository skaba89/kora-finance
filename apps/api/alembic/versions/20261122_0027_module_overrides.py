"""Configuration des modules par dossier, sans effet sur les accès existants."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_module_overrides",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "module", name=op.f("pk_tenant_module_overrides")),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
        sa.CheckConstraint("module ~ '^[a-z][a-z_]{0,31}$'", name="module_key_valid"),
    )
    op.execute("ALTER TABLE tenant_module_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_module_overrides FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_module_overrides "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.drop_table("tenant_module_overrides")

"""Stockage des versions d'offres, sans attribution ni changement de droits."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commercial_offer_versions",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("modules", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.PrimaryKeyConstraint("code", "version", name=op.f("pk_commercial_offer_versions")),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("code <> '' AND code = btrim(code)", name="code_valid"),
        sa.CheckConstraint("cardinality(modules) > 0", name="modules_nonempty"),
        sa.CheckConstraint("array_position(modules, NULL) IS NULL", name="modules_not_null"),
    )
    # Aucun service de publication n'est encore livré. Le runtime reste en lecture seule.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON commercial_offer_versions FROM kora_app")


def downgrade() -> None:
    op.drop_table("commercial_offer_versions")

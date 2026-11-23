"""Autorise uniquement la mise à jour du drapeau de suspension sous RLS."""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (suspended) ON commercial_license_periods TO kora_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (suspended) ON commercial_license_periods FROM kora_app")

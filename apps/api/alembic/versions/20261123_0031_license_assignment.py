"""Autorise uniquement l'ajout de périodes commerciales sous RLS forcée."""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON commercial_license_periods TO kora_app")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON commercial_license_periods FROM kora_app")

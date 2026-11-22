"""Autorise uniquement la publication de nouvelles versions commerciales."""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON commercial_offer_versions TO kora_app")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON commercial_offer_versions FROM kora_app")

"""Révision de base : point de départ vide de l'historique des migrations.

Les premières tables (tenants, utilisateurs, audit) arrivent en phase 1.

Révision : 0001
Parente  :
Créée le : 2026-10-23
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

"""Trésorerie 3C : rapprochement bancaire (unicité de l'appariement ligne ↔ mouvement).

Révision : 0013
Parente  : 0012

Une ligne de relevé rapprochée pointe vers un mouvement (`matched_movement_id`,
posé en 0012). Cette migration impose l'unicité du couple (dossier, mouvement) :
**un mouvement ne peut être rapproché qu'une seule fois**. Sans cette contrainte,
deux lignes de relevé — même issues de deux relevés distincts — pourraient
désigner le même mouvement et compter l'opération deux fois : exactement le double
comptage que la 3B combattait à l'import.

En PostgreSQL, les valeurs NULL ne se contredisent pas dans une contrainte
d'unicité : les lignes non rapprochées (`matched_movement_id IS NULL`) restent
libres, seules les lignes rapprochées sont contraintes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_bank_statement_lines_tenant_id_matched_movement_id"),
        "bank_statement_lines",
        ["tenant_id", "matched_movement_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_bank_statement_lines_tenant_id_matched_movement_id"),
        "bank_statement_lines",
        type_="unique",
    )

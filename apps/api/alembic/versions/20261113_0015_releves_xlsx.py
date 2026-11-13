"""Relevés : le format Excel (.xlsx) est accepté — Phase 3D.

Révision : 0015
Parente  : 0014 (prévisions de trésorerie 3E).

Les exports Mobile Money (Orange Money, MTN MoMo) parviennent aux comptables en
CSV ou en classeurs Excel. Le lecteur 3B acceptait OFX et CSV ; la contrainte
`format` est élargie à `XLSX`. Aucune donnée existante n'est modifiée : les
relevés déjà importés gardent leur format. Descente : retour à la contrainte
d'origine (elle ne peut être appliquée que si aucun relevé XLSX n'existe).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_bank_statements_format_valid"), "bank_statements", type_="check")
    op.create_check_constraint(
        op.f("ck_bank_statements_format_valid"),
        "bank_statements",
        "format IN ('OFX', 'CSV', 'XLSX')",
    )


def downgrade() -> None:
    # La contrainte resserrée exige des données compatibles : les relevés Excel ne
    # pourraient plus être lus par la version 0014 (son lecteur n'accepte qu'OFX et
    # CSV). Ils sont retirés explicitement — comme la descente de 0012 abandonne de
    # toute façon les fichiers originaux du stockage en supprimant les tables. La
    # RLS est forcée sur ces tables même pour leur propriétaire : elle est levée le
    # temps de la purge, dans la même transaction, puis rétablie à l'identique.
    op.execute("ALTER TABLE bank_statement_lines DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bank_statements DISABLE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM bank_statement_lines WHERE statement_id IN ("
        "SELECT id FROM bank_statements WHERE format NOT IN ('OFX', 'CSV'))"
    )
    op.execute("DELETE FROM bank_statements WHERE format NOT IN ('OFX', 'CSV')")
    op.execute("ALTER TABLE bank_statements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bank_statements FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bank_statement_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bank_statement_lines FORCE ROW LEVEL SECURITY")

    op.drop_constraint(op.f("ck_bank_statements_format_valid"), "bank_statements", type_="check")
    op.create_check_constraint(
        op.f("ck_bank_statements_format_valid"),
        "bank_statements",
        "format IN ('OFX', 'CSV')",
    )

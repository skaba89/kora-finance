"""Rapport de précontrôle persisté et lisible par pages (aucune écriture au journal)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = "accounting_import_batches"
_ISSUES = "accounting_import_issues"


def upgrade() -> None:
    op.add_column(_BATCH, sa.Column("precheck_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_rows", sa.BigInteger(), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_entries", sa.BigInteger(), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_debit", sa.BigInteger(), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_credit", sa.BigInteger(), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_valid", sa.Boolean(), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_issue_count", sa.Integer(), nullable=True))
    op.add_column(_BATCH, sa.Column("precheck_stored_issues", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "precheck_coherent",
        _BATCH,
        "(precheck_at IS NULL AND precheck_rows IS NULL AND precheck_entries IS NULL "
        "AND precheck_debit IS NULL AND precheck_credit IS NULL AND precheck_valid IS NULL "
        "AND precheck_issue_count IS NULL AND precheck_stored_issues IS NULL) "
        "OR (precheck_at IS NOT NULL AND precheck_rows IS NOT NULL "
        "AND precheck_entries IS NOT NULL AND precheck_debit IS NOT NULL "
        "AND precheck_credit IS NOT NULL AND precheck_valid IS NOT NULL "
        "AND precheck_issue_count IS NOT NULL AND precheck_stored_issues IS NOT NULL)",
    )
    op.create_check_constraint(
        "precheck_counts_valid",
        _BATCH,
        "precheck_issue_count >= 0 AND precheck_stored_issues >= 0 "
        "AND precheck_stored_issues <= precheck_issue_count",
    )
    op.create_table(
        _ISSUES,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("batch_id", "seq", name=op.f("pk_accounting_import_issues")),
        sa.ForeignKeyConstraint(["batch_id"], ["accounting_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.CheckConstraint("seq >= 0", name="seq_valid"),
        sa.CheckConstraint("row_number >= 1", name="row_number_valid"),
        sa.CheckConstraint("octet_length(code) > 0", name="code_present"),
    )
    op.execute(f"ALTER TABLE {_ISSUES} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_ISSUES} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_ISSUES} "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.drop_table(_ISSUES)
    op.drop_constraint("precheck_counts_valid", _BATCH, type_="check")
    op.drop_constraint("precheck_coherent", _BATCH, type_="check")
    for column in (
        "precheck_stored_issues",
        "precheck_issue_count",
        "precheck_valid",
        "precheck_credit",
        "precheck_debit",
        "precheck_entries",
        "precheck_rows",
        "precheck_at",
    ):
        op.drop_column(_BATCH, column)

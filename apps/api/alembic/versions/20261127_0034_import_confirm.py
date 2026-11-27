"""Confirmation d'import : marqueur de batch et traçabilité des brouillons générés."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = "accounting_import_batches"
_ENTRIES = "accounting_import_entries"


def upgrade() -> None:
    op.add_column(_BATCH, sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_BATCH, sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(_BATCH, sa.Column("confirmed_entries", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_accounting_import_batches_confirmed_by_user_id",
        _BATCH,
        "users",
        ["confirmed_by_user_id"],
        ["id"],
    )
    op.create_check_constraint(
        "confirmation_coherent",
        _BATCH,
        "(confirmed_at IS NULL AND confirmed_by_user_id IS NULL AND confirmed_entries IS NULL) "
        "OR (confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL "
        "AND confirmed_entries IS NOT NULL)",
    )
    op.create_check_constraint(
        "confirmed_entries_valid",
        _BATCH,
        "confirmed_entries IS NULL OR confirmed_entries >= 1",
    )
    op.create_table(
        _ENTRIES,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("batch_id", "entry_id", name=op.f("pk_accounting_import_entries")),
        sa.ForeignKeyConstraint(["batch_id"], ["accounting_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="CASCADE",
            name="fk_accounting_import_entries_tenant_entry",
        ),
        sa.UniqueConstraint(
            "tenant_id", "entry_id", name="uq_accounting_import_entries_tenant_id_entry_id"
        ),
    )
    op.execute(f"ALTER TABLE {_ENTRIES} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_ENTRIES} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_ENTRIES} "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.drop_table(_ENTRIES)
    op.drop_constraint("confirmed_entries_valid", _BATCH, type_="check")
    op.drop_constraint("confirmation_coherent", _BATCH, type_="check")
    op.drop_constraint(
        "fk_accounting_import_batches_confirmed_by_user_id", _BATCH, type_="foreignkey"
    )
    op.drop_column(_BATCH, "confirmed_entries")
    op.drop_column(_BATCH, "confirmed_by_user_id")
    op.drop_column(_BATCH, "confirmed_at")

"""Métadonnées de staging des imports comptables (aucune écriture au journal)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounting_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("delimiter", sa.String(4), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounting_import_batches")),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "sha256", "format", "currency", "delimiter"),
        sa.CheckConstraint("format IN ('csv', 'fec', 'xlsx')", name="format_valid"),
        sa.CheckConstraint("currency = 'GNF'", name="currency_valid"),
        sa.CheckConstraint(
            "(format = 'fec' AND delimiter IN ('PIPE', 'TAB')) OR "
            "(format <> 'fec' AND delimiter = 'NONE')",
            name="delimiter_valid",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= CASE WHEN format = 'xlsx' "
            "THEN 16777216 ELSE 33554432 END",
            name="size_valid",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        sa.CheckConstraint("expires_at > created_at", name="expiry_valid"),
        sa.CheckConstraint(
            "storage_key = 'imports/' || tenant_id::text || '/' || id::text",
            name="storage_key_valid",
        ),
        sa.CheckConstraint("octet_length(wrapped_key) > 0", name="wrapped_key_present"),
    )
    op.create_index(
        "ix_accounting_import_batches_tenant_expiry",
        "accounting_import_batches",
        ["tenant_id", "expires_at"],
    )
    op.execute("ALTER TABLE accounting_import_batches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE accounting_import_batches FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON accounting_import_batches "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.drop_table("accounting_import_batches")

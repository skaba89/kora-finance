"""Devis, factures et avoirs à numérotation sans trou (Phase 4B).

Révision : 0017
Parente  : 0016

Trois tables :
- `document_sequences` : dernier numéro attribué par type de document et par
  exercice, verrouillée (FOR UPDATE) à chaque émission — un numéro n'est consommé
  que si l'émission aboutit (pas de trou, même en cas de ROLLBACK) ;
- `sales_documents` : en-tête unique des devis, factures et avoirs. Le numéro est
  NULL en brouillon et attribué à l'émission seulement ; l'unicité du numéro
  (type + exercice) est garantie par un index partiel unique, deuxième barrière
  derrière le verrou du compteur ; une annulation conserve le numéro (jamais de
  réutilisation) ;
- `sales_document_lines` : lignes de documents (quantités en millièmes, prix
  unitaire HT en unités mineures, remise en points de base, taux de TVA figé).

Les mentions légales des factures guinéennes sont figées à l'émission dans les
instantanés JSONB (`partner_snapshot`, `issuer_snapshot`). Aucune écriture
comptable n'est générée par ce module : l'intégration comptable est la Phase 4E.

RLS `tenant_isolation` forcée sur les trois tables, comme toutes les tables tenant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_sequences",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("doc_kind", sa.String(length=16), nullable=False),
        sa.Column("fiscal_year_id", sa.Uuid(), nullable=False),
        sa.Column("last_number", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "doc_kind IN ('quote', 'invoice', 'credit_note')",
            name=op.f("ck_document_sequences_doc_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            name=op.f("fk_document_sequences_tenant_id_fiscal_year_id_fiscal_years"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_document_sequences_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "doc_kind", "fiscal_year_id", name=op.f("pk_document_sequences")
        ),
    )

    op.create_table(
        "sales_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("doc_kind", sa.String(length=16), nullable=False),
        sa.Column("fiscal_year_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("partner_id", sa.Uuid(), nullable=False),
        sa.Column("partner_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("issuer_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="GNF", nullable=False),
        sa.Column("total_ht", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_tax", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_ttc", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("origin_document_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_document_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("issued_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(doc_kind, status) IN (('quote','DRAFT'), ('quote','SENT'), ('quote','ACCEPTED'),"
            " ('quote','REJECTED'), ('invoice','DRAFT'), ('invoice','ISSUED'),"
            " ('invoice','CANCELLED'), ('credit_note','DRAFT'), ('credit_note','ISSUED'))",
            name=op.f("ck_sales_documents_kind_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND number IS NULL AND issued_on IS NULL)"
            " OR (status <> 'DRAFT' AND number IS NOT NULL AND issued_on IS NOT NULL)",
            name=op.f("ck_sales_documents_number_follows_emission"),
        ),
        sa.CheckConstraint(
            "total_ht >= 0 AND total_tax >= 0 AND total_ttc >= 0",
            name=op.f("ck_sales_documents_totals_non_negative"),
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name=op.f("ck_sales_documents_currency_iso4217")
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0",
            name=op.f("ck_sales_documents_notes_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_documents_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_documents_issued_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            name=op.f("fk_sales_documents_tenant_id_fiscal_year_id_fiscal_years"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "origin_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_documents_tenant_id_origin_document_id_sales_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name=op.f("fk_sales_documents_tenant_id_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_documents_tenant_id_reverses_document_id_sales_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_documents_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_documents")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sales_documents_tenant_id_id")),
        # Une facture ne peut être annulée que par un seul avoir de contrepassation.
        sa.UniqueConstraint(
            "reverses_document_id", name=op.f("uq_sales_documents_reverses_document_id")
        ),
    )
    op.create_index(
        op.f("ix_sales_documents_tenant_id"), "sales_documents", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_sales_documents_tenant_kind"),
        "sales_documents",
        ["tenant_id", "doc_kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_documents_tenant_status"),
        "sales_documents",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_documents_tenant_partner"),
        "sales_documents",
        ["tenant_id", "partner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_documents_tenant_date"),
        "sales_documents",
        ["tenant_id", "issued_on"],
        unique=False,
    )
    # Unicité du numéro émis par type et exercice (documents émis uniquement).
    op.create_index(
        "uq_sales_documents_number",
        "sales_documents",
        ["tenant_id", "doc_kind", "fiscal_year_id", "number"],
        unique=True,
        postgresql_where=sa_text("number IS NOT NULL"),
    )

    op.create_table(
        "sales_document_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_price_ht", sa.BigInteger(), nullable=False),
        sa.Column("discount_bp", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tax_rate_id", sa.Uuid(), nullable=True),
        sa.Column("tax_bp_snapshot", sa.Integer(), nullable=True),
        sa.Column("line_ht", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("line_tax", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("line_ttc", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("tax_exempt_reason", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "line_no BETWEEN 1 AND 50", name=op.f("ck_sales_document_lines_line_no_range")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sales_document_lines_quantity_positive")),
        sa.CheckConstraint(
            "unit_price_ht >= 0", name=op.f("ck_sales_document_lines_unit_price_non_negative")
        ),
        sa.CheckConstraint(
            "discount_bp BETWEEN 0 AND 10000",
            name=op.f("ck_sales_document_lines_discount_bp_range"),
        ),
        sa.CheckConstraint(
            "length(trim(label)) > 0", name=op.f("ck_sales_document_lines_label_not_blank")
        ),
        sa.CheckConstraint(
            "tax_exempt_reason IS NULL OR length(trim(tax_exempt_reason)) > 0",
            name=op.f("ck_sales_document_lines_tax_exempt_reason_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_document_lines_tenant_id_document_id_sales_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tax_rate_id"],
            ["tax_rates.id"],
            name=op.f("fk_sales_document_lines_tax_rate_id_tax_rates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_document_lines_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_document_lines")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "line_no",
            name=op.f("uq_sales_document_lines_tenant_id_document_id_line_no"),
        ),
    )
    op.create_index(
        op.f("ix_sales_document_lines_tenant_id"),
        "sales_document_lines",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_document_lines_tenant_document"),
        "sales_document_lines",
        ["tenant_id", "document_id"],
        unique=False,
    )

    # RLS : les documents de vente d'un dossier ne sont visibles que dans son contexte.
    for table in ("document_sequences", "sales_documents", "sales_document_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = kora_current_tenant()) "
            "WITH CHECK (tenant_id = kora_current_tenant())"
        )


def downgrade() -> None:
    for table in ("sales_document_lines", "sales_documents", "document_sequences"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_sales_document_lines_tenant_document")
    op.execute("DROP INDEX IF EXISTS ix_sales_document_lines_tenant_id")
    op.drop_table("sales_document_lines")
    op.drop_index("uq_sales_documents_number", table_name="sales_documents")
    op.drop_index(op.f("ix_sales_documents_tenant_date"), table_name="sales_documents")
    op.drop_index(op.f("ix_sales_documents_tenant_partner"), table_name="sales_documents")
    op.drop_index(op.f("ix_sales_documents_tenant_status"), table_name="sales_documents")
    op.drop_index(op.f("ix_sales_documents_tenant_kind"), table_name="sales_documents")
    op.drop_index(op.f("ix_sales_documents_tenant_id"), table_name="sales_documents")
    op.drop_table("sales_documents")
    op.drop_table("document_sequences")

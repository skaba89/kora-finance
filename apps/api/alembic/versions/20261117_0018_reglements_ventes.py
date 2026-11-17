"""Règlements clients et lettrage commercial (Phase 4C).

Révision : 0018
Parente  : 0017

Deux tables :
- `sales_payments` : un encaissement reçu d'un client (date, mode de paiement
  borné à l'énumération, référence facultative, montant = somme des affectations,
  tier unique) ; l'exercice est celui de la date d'encaissement ;
- `sales_payment_allocations` : l'affectation d'un règlement à une facture émise
  (le lettrage commercial qui porte le solde restant dû). Unicité
  (règlement, facture) ; montant strictement positif ; la facture est verrouillée
  FOR UPDATE par le service avant contrôle du solde : deux règlements concurrents
  ne peuvent jamais excéder le TTC ensemble.

Le solde restant dû d'une facture se calcule en lecture : TTC - affectations -
avoirs partiels émis (les avoirs annulateurs passent la facture en CANCELLED et
refusent tout règlement). Aucune écriture comptable n'est générée par ce module :
l'intégration comptable est la Phase 4E.

RLS `tenant_isolation` forcée sur les deux tables, comme toutes les tables tenant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_year_id", sa.Uuid(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="GNF", nullable=False),
        sa.Column("partner_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
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
            "method IN ('CASH', 'BANK_TRANSFER', 'MOBILE_MONEY', 'CHECK', 'CARD', 'OTHER')",
            name=op.f("ck_sales_payments_method_valid"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_sales_payments_amount_positive")),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name=op.f("ck_sales_payments_currency_iso4217")
        ),
        sa.CheckConstraint(
            "reference IS NULL OR length(trim(reference)) > 0",
            name=op.f("ck_sales_payments_reference_not_blank"),
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0",
            name=op.f("ck_sales_payments_notes_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_payments_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            name=op.f("fk_sales_payments_tenant_id_fiscal_year_id_fiscal_years"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name=op.f("fk_sales_payments_tenant_id_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_payments_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_payments")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sales_payments_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_sales_payments_tenant_id"), "sales_payments", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_sales_payments_tenant_partner"),
        "sales_payments",
        ["tenant_id", "partner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_payments_tenant_date"),
        "sales_payments",
        ["tenant_id", "paid_on"],
        unique=False,
    )

    op.create_table(
        "sales_payment_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_sales_payment_allocations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["sales_payments.tenant_id", "sales_payments.id"],
            name=op.f("fk_sales_payment_allocations_tenant_id_payment_id_sales_payments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_payment_allocations_tenant_id_document_id_sales_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_payment_allocations_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_payment_allocations")),
        sa.UniqueConstraint(
            "payment_id",
            "document_id",
            name=op.f("uq_sales_payment_allocations_payment_id_document_id"),
        ),
    )
    op.create_index(
        op.f("ix_sales_payment_allocations_tenant_id"),
        "sales_payment_allocations",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_payment_allocations_tenant_document"),
        "sales_payment_allocations",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_payment_allocations_tenant_payment"),
        "sales_payment_allocations",
        ["tenant_id", "payment_id"],
        unique=False,
    )

    # RLS : les règlements d'un dossier ne sont visibles que dans son contexte.
    for table in ("sales_payments", "sales_payment_allocations"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = kora_current_tenant()) "
            "WITH CHECK (tenant_id = kora_current_tenant())"
        )


def downgrade() -> None:
    for table in ("sales_payment_allocations", "sales_payments"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_sales_payment_allocations_tenant_payment")
    op.execute("DROP INDEX IF EXISTS ix_sales_payment_allocations_tenant_document")
    op.execute("DROP INDEX IF EXISTS ix_sales_payment_allocations_tenant_id")
    op.drop_table("sales_payment_allocations")
    op.execute("DROP INDEX IF EXISTS ix_sales_payments_tenant_date")
    op.execute("DROP INDEX IF EXISTS ix_sales_payments_tenant_partner")
    op.execute("DROP INDEX IF EXISTS ix_sales_payments_tenant_id")
    op.drop_table("sales_payments")

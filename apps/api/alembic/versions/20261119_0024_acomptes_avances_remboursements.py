"""Acomptes clients, avances fournisseurs, trop-perçus, remboursements et
affectation ultérieure (Lot B-3).

Révision : 0024
Parente  : 0023

Deux nouvelles tables et deux colonnes, miroir du module des règlements :

- `sales_refunds` : un remboursement versé à un client — le retour d'un acompte
  ou d'un trop-perçu qui n'est pas lettré. Le disponible au remboursement
  (montant du règlement - affectations - remboursements déjà saisis) est
  contrôlé par le service sous verrou FOR UPDATE du règlement porteur. La date
  est le fait générateur (l'exercice couvrant `refunded_on` doit être ouvert) ;
  `entry_id` (FK composite RESTRICT vers `journal_entries`, sur le modèle établi
  en 0020) reste NULL tant que la comptabilisation explicite n'a pas eu lieu ;
- `purchase_refunds` : le remboursement reçu d'un fournisseur — le retour d'une
  avance ou d'un trop-versé, miroir exact côté achats ;
- `sales_payment_allocations.entry_id` : la couverture comptable de chaque
  affectation — remplie à la comptabilisation du règlement (le crédit du compte
  de tiers couvre les affectations présentes à ce moment) ou à l'écriture de
  transfert de l'acompte (débit 4191 « Clients, avances et acomptes reçus »,
  crédit du compte de tiers) quand l'affectation ultérieure arrive après
  comptabilisation. NULL tant que non couverte ;
- `purchase_payment_allocations.entry_id` : le même mécanisme côté achats
  (débit du compte de tiers fournisseur, crédit 4091 « Fournisseurs, avances et
  acomptes versés »).

Le montant d'un règlement reste strictement positif : aucun changement de
contrainte existant — le reste non affecté est la différence entre le montant
et les affectations, calculé en lecture (aucun statut dérivé stocké). Aucune
écriture comptable n'est générée automatiquement par ces cheminements : la
comptabilisation reste l'acte explicite du comptable (`entries:post`).

RLS `tenant_isolation` forcée sur les deux nouvelles tables, comme toutes les
tables tenant. Les deux colonnes portées par des tables RLS existantes ne
changent rien à l'isolation (mêmes lignes, même politique).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _refund_columns() -> list[sa.Column]:
    """Colonnes communes des deux tables de remboursement (miroir exact)."""
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_year_id", sa.Uuid(), nullable=False),
        sa.Column("refunded_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="GNF", nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=True),
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
    ]


def _refund_checks(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "method IN ('CASH', 'BANK_TRANSFER', 'MOBILE_MONEY', 'CHECK', 'CARD', 'OTHER')",
            name=op.f(f"ck_{table}_method_valid"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f(f"ck_{table}_amount_positive")),
        sa.CheckConstraint("length(trim(currency)) = 3", name=op.f(f"ck_{table}_currency_iso4217")),
        sa.CheckConstraint(
            "reference IS NULL OR length(trim(reference)) > 0",
            name=op.f(f"ck_{table}_reference_not_blank"),
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0", name=op.f(f"ck_{table}_notes_not_blank")
        ),
    ]


def _create_refunds(table: str, payments: str, prefix: str) -> None:
    """Crée une table de remboursement (ventes ou achats) + RLS forcée."""
    op.create_table(
        table,
        *_refund_columns(),
        *_refund_checks(table),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name=op.f(f"fk_{table}_created_by_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            name=op.f(f"fk_{table}_tenant_id_fiscal_year_id_fiscal_years"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            [f"{payments}.tenant_id", f"{payments}.id"],
            name=op.f(f"fk_{table}_tenant_id_payment_id_{payments}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            name=op.f(f"fk_{table}_tenant_id_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f(f"fk_{table}_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f(f"uq_{table}_tenant_id_id")),
    )
    op.create_index(op.f(f"ix_{table}_tenant_id"), table, ["tenant_id"], unique=False)
    op.create_index(
        op.f(f"ix_{prefix}_tenant_payment"), table, ["tenant_id", "payment_id"], unique=False
    )
    op.create_index(
        op.f(f"ix_{prefix}_tenant_date"), table, ["tenant_id", "refunded_on"], unique=False
    )
    # RLS : les remboursements d'un dossier ne sont visibles que dans son contexte.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def upgrade() -> None:
    _create_refunds("sales_refunds", "sales_payments", "sales_refunds")
    _create_refunds("purchase_refunds", "purchase_payments", "purchase_refunds")

    # La couverture comptable des affectations : NULL tant que non couverte —
    # remplie par la comptabilisation du règlement ou par le transfert d'acompte.
    op.add_column(
        "sales_payment_allocations",
        sa.Column("entry_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_sales_payment_allocations_tenant_id_entry_id_journal_entries"),
        "sales_payment_allocations",
        "journal_entries",
        ["tenant_id", "entry_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "purchase_payment_allocations",
        sa.Column("entry_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_purchase_payment_allocations_tenant_id_entry_id_journal_entries"),
        "purchase_payment_allocations",
        "journal_entries",
        ["tenant_id", "entry_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_purchase_payment_allocations_tenant_id_entry_id_journal_entries"),
        "purchase_payment_allocations",
        type_="foreignkey",
    )
    op.drop_column("purchase_payment_allocations", "entry_id")
    op.drop_constraint(
        op.f("fk_sales_payment_allocations_tenant_id_entry_id_journal_entries"),
        "sales_payment_allocations",
        type_="foreignkey",
    )
    op.drop_column("sales_payment_allocations", "entry_id")
    for table, prefix in (
        ("purchase_refunds", "purchase_refunds"),
        ("sales_refunds", "sales_refunds"),
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP INDEX IF EXISTS ix_{prefix}_tenant_date")
        op.execute(f"DROP INDEX IF EXISTS ix_{prefix}_tenant_payment")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_tenant_id")
        op.drop_table(table)

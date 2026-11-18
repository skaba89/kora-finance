"""Achats : factures et avoirs fournisseurs, décaissements et lettrage (Phase 4F).

Révision : 0021
Parente  : 0020

Quatre tables, miroir du module ventes (migrations 0017 et 0018) :
- `purchase_documents` : en-tête des factures et avoirs fournisseurs. Le numéro
  interne est NULL en brouillon et attribué à l'émission seulement ; l'unicité
  du numéro (type + exercice) est garantie par un index partiel unique, deuxième
  barrière derrière le verrou du compteur ; une annulation conserve le numéro
  (jamais de réutilisation). `reference` porte le numéro imprimé sur la facture
  du fournisseur (pièce justificative). La colonne `entry_id` (FK composite
  RESTRICT vers `journal_entries`, sur le modèle établi en 0020) est créée
  d'emblée : la comptabilisation est un acte explicite du comptable, NULL tant
  que non comptabilisé ;
- `purchase_document_lines` : lignes de documents (quantités en millièmes, prix
  unitaire HT en unités mineures, remise en points de base, taux de TVA figé) ;
- `purchase_payments` : un décaissement versé à un fournisseur (date, mode de
  paiement borné à l'énumération, référence facultative, montant = somme des
  affectations) ; l'exercice est celui de la date de décaissement ; `entry_id`
  sur le même modèle ;
- `purchase_payment_allocations` : l'affectation d'un décaissement à une facture
  fournisseur émise (le lettrage commercial fournisseurs qui porte le solde
  restant dû). Unicité (règlement, facture) ; montant strictement positif ; la
  facture est verrouillée FOR UPDATE par le service avant contrôle du solde :
  deux règlements concurrents ne peuvent jamais excéder le TTC ensemble.

Le compteur `document_sequences` s'élargit aux types d'achat : la CHECK
`doc_kind_valid` ajoute 'supplier_invoice' et 'supplier_credit_note' aux trois
types de vente existants — la numérotation sans trou est la même pour les achats
que pour les ventes. Le downgrade restaure la CHECK d'origine : il exige alors
qu'aucun document d'achat n'existe plus (les tables sont tombées avant).

Le solde restant dû d'une facture fournisseur se calcule en lecture :
TTC - affectations - avoirs partiels émis (les avoirs annulateurs passent la
facture en CANCELLED et refusent tout décaissement). Aucune écriture comptable
n'est générée automatiquement : la comptabilisation est la route explicite
`entries:post` (écriture du journal des achats ou de trésorerie).

RLS `tenant_isolation` forcée sur les quatre tables, comme toutes les tables
tenant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# La CHECK d'origine (migration 0017) et sa forme élargie aux achats.
_ORIGINAL_KIND_CHECK = "doc_kind IN ('quote', 'invoice', 'credit_note')"
_WIDENED_KIND_CHECK = (
    "doc_kind IN ('quote', 'invoice', 'credit_note', 'supplier_invoice', 'supplier_credit_note')"
)


def upgrade() -> None:
    # Le compteur de numérotation s'ouvre aux documents d'achat : sa colonne
    # doc_kind passe de 16 à 24 caractères ('supplier_credit_note' = 20).
    op.alter_column(
        "document_sequences",
        "doc_kind",
        existing_type=sa.String(length=16),
        type_=sa.String(length=24),
    )
    op.drop_constraint(
        op.f("ck_document_sequences_doc_kind_valid"),
        "document_sequences",
        type_="check",
    )
    op.create_check_constraint(
        "doc_kind_valid",
        "document_sequences",
        _WIDENED_KIND_CHECK,
    )

    op.create_table(
        "purchase_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("doc_kind", sa.String(length=24), nullable=False),
        sa.Column("fiscal_year_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("partner_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("partner_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("issuer_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="GNF", nullable=False),
        sa.Column("total_ht", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_tax", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_ttc", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("origin_document_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_document_id", sa.Uuid(), nullable=True),
        sa.Column("entry_id", sa.Uuid(), nullable=True),
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
            "(doc_kind, status) IN (('supplier_invoice','DRAFT'), ('supplier_invoice','ISSUED'),"
            " ('supplier_invoice','CANCELLED'), ('supplier_credit_note','DRAFT'),"
            " ('supplier_credit_note','ISSUED'))",
            name=op.f("ck_purchase_documents_kind_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND number IS NULL AND issued_on IS NULL)"
            " OR (status <> 'DRAFT' AND number IS NOT NULL AND issued_on IS NOT NULL)",
            name=op.f("ck_purchase_documents_number_follows_emission"),
        ),
        sa.CheckConstraint(
            "total_ht >= 0 AND total_tax >= 0 AND total_ttc >= 0",
            name=op.f("ck_purchase_documents_totals_non_negative"),
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name=op.f("ck_purchase_documents_currency_iso4217")
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0",
            name=op.f("ck_purchase_documents_notes_not_blank"),
        ),
        sa.CheckConstraint(
            "reference IS NULL OR length(trim(reference)) > 0",
            name=op.f("ck_purchase_documents_reference_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_purchase_documents_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["users.id"],
            name=op.f("fk_purchase_documents_issued_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            name=op.f("fk_purchase_documents_tenant_id_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            name=op.f("fk_purchase_documents_tenant_id_fiscal_year_id_fiscal_years"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "origin_document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            name=op.f("fk_purchase_documents_tenant_id_origin_document_id_purchase_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name=op.f("fk_purchase_documents_tenant_id_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            name=op.f("fk_purchase_documents_tenant_id_reverses_document_id_purchase_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_purchase_documents_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_documents")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_purchase_documents_tenant_id_id")),
        # Une facture fournisseur ne peut être annulée que par un seul avoir.
        sa.UniqueConstraint(
            "reverses_document_id", name=op.f("uq_purchase_documents_reverses_document_id")
        ),
    )
    op.create_index(
        op.f("ix_purchase_documents_tenant_id"), "purchase_documents", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_documents_tenant_kind"),
        "purchase_documents",
        ["tenant_id", "doc_kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_documents_tenant_status"),
        "purchase_documents",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_documents_tenant_partner"),
        "purchase_documents",
        ["tenant_id", "partner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_documents_tenant_date"),
        "purchase_documents",
        ["tenant_id", "issued_on"],
        unique=False,
    )
    # Unicité du numéro émis par type et exercice (documents émis uniquement).
    op.create_index(
        "uq_purchase_documents_number",
        "purchase_documents",
        ["tenant_id", "doc_kind", "fiscal_year_id", "number"],
        unique=True,
        postgresql_where=sa_text("number IS NOT NULL"),
    )

    op.create_table(
        "purchase_document_lines",
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
            "line_no BETWEEN 1 AND 50", name=op.f("ck_purchase_document_lines_line_no_range")
        ),
        sa.CheckConstraint(
            "quantity > 0", name=op.f("ck_purchase_document_lines_quantity_positive")
        ),
        sa.CheckConstraint(
            "unit_price_ht >= 0",
            name=op.f("ck_purchase_document_lines_unit_price_non_negative"),
        ),
        sa.CheckConstraint(
            "discount_bp BETWEEN 0 AND 10000",
            name=op.f("ck_purchase_document_lines_discount_bp_range"),
        ),
        sa.CheckConstraint(
            "length(trim(label)) > 0", name=op.f("ck_purchase_document_lines_label_not_blank")
        ),
        sa.CheckConstraint(
            "tax_exempt_reason IS NULL OR length(trim(tax_exempt_reason)) > 0",
            name=op.f("ck_purchase_document_lines_tax_exempt_reason_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            name=op.f("fk_purchase_document_lines_tenant_id_document_id_purchase_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tax_rate_id"],
            ["tax_rates.id"],
            name=op.f("fk_purchase_document_lines_tax_rate_id_tax_rates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_purchase_document_lines_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_document_lines")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "line_no",
            name=op.f("uq_purchase_document_lines_tenant_id_document_id_line_no"),
        ),
    )
    op.create_index(
        op.f("ix_purchase_document_lines_tenant_id"),
        "purchase_document_lines",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_document_lines_tenant_document"),
        "purchase_document_lines",
        ["tenant_id", "document_id"],
        unique=False,
    )

    op.create_table(
        "purchase_payments",
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
        sa.CheckConstraint(
            "method IN ('CASH', 'BANK_TRANSFER', 'MOBILE_MONEY', 'CHECK', 'CARD', 'OTHER')",
            name=op.f("ck_purchase_payments_method_valid"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_purchase_payments_amount_positive")),
        sa.CheckConstraint(
            "length(trim(currency)) = 3", name=op.f("ck_purchase_payments_currency_iso4217")
        ),
        sa.CheckConstraint(
            "reference IS NULL OR length(trim(reference)) > 0",
            name=op.f("ck_purchase_payments_reference_not_blank"),
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0",
            name=op.f("ck_purchase_payments_notes_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_purchase_payments_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            name=op.f("fk_purchase_payments_tenant_id_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_year_id"],
            ["fiscal_years.tenant_id", "fiscal_years.id"],
            name=op.f("fk_purchase_payments_tenant_id_fiscal_year_id_fiscal_years"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name=op.f("fk_purchase_payments_tenant_id_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_purchase_payments_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_payments")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_purchase_payments_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_purchase_payments_tenant_id"), "purchase_payments", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_payments_tenant_partner"),
        "purchase_payments",
        ["tenant_id", "partner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_payments_tenant_date"),
        "purchase_payments",
        ["tenant_id", "paid_on"],
        unique=False,
    )

    op.create_table(
        "purchase_payment_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "amount > 0", name=op.f("ck_purchase_payment_allocations_amount_positive")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["purchase_documents.tenant_id", "purchase_documents.id"],
            name=op.f("fk_purchase_payment_allocations_tenant_id_document_id_purchase_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["purchase_payments.tenant_id", "purchase_payments.id"],
            name=op.f("fk_purchase_payment_allocations_tenant_id_payment_id_purchase_payments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_purchase_payment_allocations_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_payment_allocations")),
        sa.UniqueConstraint(
            "payment_id",
            "document_id",
            name=op.f("uq_purchase_payment_allocations_payment_id_document_id"),
        ),
    )
    op.create_index(
        op.f("ix_purchase_payment_allocations_tenant_id"),
        "purchase_payment_allocations",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_payment_allocations_tenant_document"),
        "purchase_payment_allocations",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_purchase_payment_allocations_tenant_payment"),
        "purchase_payment_allocations",
        ["tenant_id", "payment_id"],
        unique=False,
    )

    # RLS : les documents d'achat d'un dossier ne sont visibles que dans son contexte.
    for table in (
        "purchase_documents",
        "purchase_document_lines",
        "purchase_payments",
        "purchase_payment_allocations",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = kora_current_tenant()) "
            "WITH CHECK (tenant_id = kora_current_tenant())"
        )


def downgrade() -> None:
    for table in (
        "purchase_payment_allocations",
        "purchase_payments",
        "purchase_document_lines",
        "purchase_documents",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_purchase_payment_allocations_tenant_payment")
    op.execute("DROP INDEX IF EXISTS ix_purchase_payment_allocations_tenant_document")
    op.execute("DROP INDEX IF EXISTS ix_purchase_payment_allocations_tenant_id")
    op.drop_table("purchase_payment_allocations")
    op.drop_index(op.f("ix_purchase_payments_tenant_date"), table_name="purchase_payments")
    op.drop_index(op.f("ix_purchase_payments_tenant_partner"), table_name="purchase_payments")
    op.drop_index(op.f("ix_purchase_payments_tenant_id"), table_name="purchase_payments")
    op.drop_table("purchase_payments")
    op.execute("DROP INDEX IF EXISTS ix_purchase_document_lines_tenant_document")
    op.execute("DROP INDEX IF EXISTS ix_purchase_document_lines_tenant_id")
    op.drop_table("purchase_document_lines")
    op.drop_index("uq_purchase_documents_number", table_name="purchase_documents")
    op.drop_index(op.f("ix_purchase_documents_tenant_date"), table_name="purchase_documents")
    op.drop_index(op.f("ix_purchase_documents_tenant_partner"), table_name="purchase_documents")
    op.drop_index(op.f("ix_purchase_documents_tenant_status"), table_name="purchase_documents")
    op.drop_index(op.f("ix_purchase_documents_tenant_kind"), table_name="purchase_documents")
    op.drop_index(op.f("ix_purchase_documents_tenant_id"), table_name="purchase_documents")
    op.drop_table("purchase_documents")
    # Les tables d'achat sont tombées : les compteurs de numérotation des types
    # d'achat n'ont plus d'existence possible — ils partent avant que la CHECK
    # d'origine (ventes seulement) ne soit rétablie. `document_sequences` porte
    # une RLS FORCÉE (0017) : le rôle de migration ne voit donc aucune ligne
    # (kora_current_tenant() est NULL pour lui) — la RLS est levée le temps du
    # DELETE, sinon les compteurs d'achat survivent invisibles et la CHECK
    # d'origine (dont la validation scanne physiquement la table) est violée.
    op.execute("ALTER TABLE document_sequences NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_sequences DISABLE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM document_sequences "
        "WHERE doc_kind IN ('supplier_invoice', 'supplier_credit_note')"
    )
    op.drop_constraint(
        op.f("ck_document_sequences_doc_kind_valid"),
        "document_sequences",
        type_="check",
    )
    op.create_check_constraint(
        "doc_kind_valid",
        "document_sequences",
        _ORIGINAL_KIND_CHECK,
    )
    # La colonne doc_kind retrouve sa largeur d'origine (les types d'achat ont
    # été purgés ci-dessus : aucune valeur ne dépasse plus 16 caractères).
    op.alter_column(
        "document_sequences",
        "doc_kind",
        existing_type=sa.String(length=24),
        type_=sa.String(length=16),
    )
    # La RLS est rétablie à l'état posé par 0017 (la policy tenant_isolation,
    # jamais supprimée, redevient effective).
    op.execute("ALTER TABLE document_sequences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_sequences FORCE ROW LEVEL SECURITY")

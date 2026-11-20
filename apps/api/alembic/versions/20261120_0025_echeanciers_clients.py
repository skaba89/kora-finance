"""Échéanciers clients : tranches de règlement prévues d'une facture (Lot B-4).

Révision : 0025
Parente  : 0024

Une nouvelle table : `sales_payment_schedule_lines` — une échéance prévue du
règlement d'une facture émise (date et montant attendus d'une tranche, convenus
avec le client). C'est un **outil de planification du recouvrement** :

- le plan d'une facture est remplacé en bloc (sémantique PUT du service) : les
  lignes sont renumérotées 1..N à chaque mise à jour — l'unicité
  (tenant_id, document_id, line_no) fait foi ;
- le montant attendu est strictement positif ; la somme du plan ne peut pas
  dépasser le solde restant dû de la facture (contrôlé par le service sous
  verrou FOR UPDATE du document — sérialisé avec les règlements 4C qui
  réduisent ce solde) ;
- le statut d'une ligne (réglée / en retard / à venir) est **calculé en
  lecture** au jour demandé : aucun statut dérivé n'est stocké, aucune dérive
  possible ;
- aucune écriture comptable : l'échéancier n'est ni un règlement ni une
  écriture — le comptable reste maître de la comptabilisation (4E, acte
  explicite `entries:post`).

RLS `tenant_isolation` forcée, comme toutes les tables tenant. La suppression
d'une facture (brouillon) emporte son plan (CASCADE sur la FK composite) ; une
facture émise n'est jamais supprimée.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_payment_schedule_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("expected_on", sa.Date(), nullable=False),
        sa.Column("expected_amount", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
            "expected_amount > 0",
            name=op.f("ck_sales_payment_schedule_lines_expected_amount_positive"),
        ),
        sa.CheckConstraint(
            "line_no > 0", name=op.f("ck_sales_payment_schedule_lines_line_no_positive")
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(trim(note)) > 0",
            name=op.f("ck_sales_payment_schedule_lines_note_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_payment_schedule_lines_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_payment_schedule_lines_tenant_id_document_id_sales_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_payment_schedule_lines_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_payment_schedule_lines")),
        sa.UniqueConstraint(
            "tenant_id", "id", name=op.f("uq_sales_payment_schedule_lines_tenant_id_id")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "line_no",
            name=op.f("uq_sales_payment_schedule_lines_tenant_id_document_id_line_no"),
        ),
    )
    op.create_index(
        op.f("ix_sales_payment_schedule_lines_tenant_id"),
        "sales_payment_schedule_lines",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_payment_schedule_lines_tenant_document"),
        "sales_payment_schedule_lines",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_schedule_lines_tenant_date"),
        "sales_payment_schedule_lines",
        ["tenant_id", "expected_on"],
        unique=False,
    )

    # RLS : le plan d'un dossier n'est visible que dans son contexte.
    op.execute("ALTER TABLE sales_payment_schedule_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_payment_schedule_lines FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sales_payment_schedule_lines "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sales_payment_schedule_lines")
    op.execute("ALTER TABLE sales_payment_schedule_lines NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_payment_schedule_lines DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        op.f("ix_sales_schedule_lines_tenant_date"), table_name="sales_payment_schedule_lines"
    )
    op.drop_index(
        op.f("ix_sales_payment_schedule_lines_tenant_document"),
        table_name="sales_payment_schedule_lines",
    )
    op.drop_index(
        op.f("ix_sales_payment_schedule_lines_tenant_id"),
        table_name="sales_payment_schedule_lines",
    )
    op.drop_table("sales_payment_schedule_lines")

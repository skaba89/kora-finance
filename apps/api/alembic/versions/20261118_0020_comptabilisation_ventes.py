"""Intégration comptable des ventes (Phase 4E).

Révision : 0020
Parente  : 0019

Deux colonnes de liaison opération → écriture, sur le modèle établi des
mouvements de trésorerie (`financial_movements.entry_id`) :
- `sales_documents.entry_id` : écriture validée du grand livre qui porte la
  facture ou l'avoir émis (journal des ventes) ;
- `sales_payments.entry_id` : écriture validée qui porte l'encaissement
  (journal de trésorerie).

NULL = opération pas encore comptabilisée : l'intégration comptable est un
acte explicite (validation humaine, permission `entries:post`), jamais
automatique — aucun chemin d'émission, de règlement ou de relance n'écrit en
comptabilité. Les colonnes sont NULLables : les documents et règlements créés
avant cette migration restent comptabilisables.

Les tables portent déjà la RLS forcée (migrations 0017 et 0018) : les nouvelles
colonnes suivent la table, rien à ajouter de ce côté.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_documents",
        sa.Column("entry_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_documents_tenant_id_entry_id_journal_entries",
        "sales_documents",
        "journal_entries",
        ["tenant_id", "entry_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "sales_payments",
        sa.Column("entry_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_payments_tenant_id_entry_id_journal_entries",
        "sales_payments",
        "journal_entries",
        ["tenant_id", "entry_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sales_payments_tenant_id_entry_id_journal_entries",
        "sales_payments",
        type_="foreignkey",
    )
    op.drop_column("sales_payments", "entry_id")
    op.drop_constraint(
        "fk_sales_documents_tenant_id_entry_id_journal_entries",
        "sales_documents",
        type_="foreignkey",
    )
    op.drop_column("sales_documents", "entry_id")

"""Relances de factures échues (Phase 4D).

Révision : 0019
Parente  : 0018

Une table : `sales_reminders`. Une relance est l'enregistrement d'un rappel
adressé au client pour une facture échue non soldée : niveau (1re, 2e, 3e…
relance — calculé par le service, jamais saisi), date du rappel, canal borné à
EMAIL (WhatsApp : évolution future), adresse destinataire au moment de l'envoi
(traçabilité : le tier peut changer d'email ensuite) et message personnalisé
facultatif. Une relance est immuable : un email envoyé ne se « désend » pas —
aucune route de suppression, aucune modification.

Deux barrières contre les doublons :
- unicité (dossier, facture, jour du rappel) : une même facture ne reçoit qu'une
  relance par jour — deux courses concurrentes se sérialisent sur ce contraignant
  (le service la traduit en 409) ;
- le niveau est compté sous verrou FOR UPDATE de la facture : deux relances
  concurrentes ne peuvent pas obtenir le même niveau.

Aucune écriture comptable n'est générée par ce module (garde-fou testé, comme en
4A, 4B et 4C) : la relance est un acte commercial documenté, pas un fait
financier. RLS `tenant_isolation` forcée, comme toutes les tables tenant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("partner_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("reminded_on", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("email_to", sa.String(length=254), nullable=False),
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
        sa.CheckConstraint("level >= 1", name=op.f("ck_sales_reminders_level_valid")),
        sa.CheckConstraint("channel IN ('EMAIL')", name=op.f("ck_sales_reminders_channel_valid")),
        sa.CheckConstraint(
            "length(trim(email_to)) > 0", name=op.f("ck_sales_reminders_email_to_not_blank")
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(trim(note)) > 0",
            name=op.f("ck_sales_reminders_note_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_reminders_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_reminders_tenant_id_document_id_sales_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name=op.f("fk_sales_reminders_tenant_id_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_reminders_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_reminders")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sales_reminders_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "reminded_on",
            name=op.f("uq_sales_reminders_tenant_id_document_id_reminded_on"),
        ),
    )
    op.create_index(
        op.f("ix_sales_reminders_tenant_id"), "sales_reminders", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_sales_reminders_tenant_document"),
        "sales_reminders",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_reminders_tenant_partner"),
        "sales_reminders",
        ["tenant_id", "partner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_reminders_tenant_date"),
        "sales_reminders",
        ["tenant_id", "reminded_on"],
        unique=False,
    )

    # RLS : les relances d'un dossier ne sont visibles que dans son contexte.
    op.execute("ALTER TABLE sales_reminders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_reminders FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sales_reminders "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sales_reminders")
    op.execute("ALTER TABLE sales_reminders NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_reminders DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_sales_reminders_tenant_date")
    op.execute("DROP INDEX IF EXISTS ix_sales_reminders_tenant_partner")
    op.execute("DROP INDEX IF EXISTS ix_sales_reminders_tenant_document")
    op.execute("DROP INDEX IF EXISTS ix_sales_reminders_tenant_id")
    op.drop_table("sales_reminders")

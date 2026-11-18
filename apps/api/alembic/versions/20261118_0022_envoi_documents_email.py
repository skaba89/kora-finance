"""Envoi des documents de vente par email avec PDF (Phase 4D-bis).

Révision : 0022
Parente  : 0021

Une table : `sales_document_emails`. Un envoi est l'enregistrement d'un email
adressé au client (ou à un destinataire explicite) portant le PDF du document
de vente numéroté : adresse destinataire figée au moment de la demande
(traçabilité), message personnalisé facultatif, auteur de l'envoi. Un envoi est
immuable : un email parti ne se « désend » pas — aucune route de suppression,
aucune modification.

Contrairement à la relance (4D), pas d'unicité quotidienne : un client peut
redemander l'exemplaire de sa facture plusieurs fois le même jour — chaque
envoi est enregistré et journalisé (`sales_document.emailed`). Le PDF est rendu
dans le worker depuis les instantanés figés à l'émission (4B-bis), jamais depuis
les fiches vivantes. Aucune écriture comptable n'est générée par ce module :
l'envoi est un acte commercial documenté, pas un fait financier.

RLS `tenant_isolation` forcée, comme toutes les tables tenant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_document_emails",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("partner_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "length(trim(email_to)) > 0", name=op.f("ck_sales_document_emails_email_to_not_blank")
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(trim(note)) > 0",
            name=op.f("ck_sales_document_emails_note_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_document_emails_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name=op.f("fk_sales_document_emails_tenant_id_document_id_sales_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name=op.f("fk_sales_document_emails_tenant_id_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_document_emails_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_document_emails")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sales_document_emails_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_sales_document_emails_tenant_id"),
        "sales_document_emails",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_document_emails_tenant_document"),
        "sales_document_emails",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_document_emails_tenant_partner"),
        "sales_document_emails",
        ["tenant_id", "partner_id"],
        unique=False,
    )

    # RLS : les envois d'un dossier ne sont visibles que dans son contexte.
    op.execute("ALTER TABLE sales_document_emails ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_document_emails FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sales_document_emails "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sales_document_emails")
    op.execute("ALTER TABLE sales_document_emails NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_document_emails DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_sales_document_emails_tenant_partner")
    op.execute("DROP INDEX IF EXISTS ix_sales_document_emails_tenant_document")
    op.execute("DROP INDEX IF EXISTS ix_sales_document_emails_tenant_id")
    op.drop_table("sales_document_emails")

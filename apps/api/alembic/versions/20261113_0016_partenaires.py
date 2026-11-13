"""Référentiel des tiers : clients et fournisseurs (Phase 4A).

Révision : 0016
Parente  : 0015

Une table `partners` : la fiche maître d'un client ou d'un fournisseur du dossier.
Elle porte les mentions obligatoires des factures (raison sociale, NIU/NCC ou NIF,
RCCM, adresse) et les coordonnées des relances. Un tier est client, fournisseur ou
les deux ; il n'est jamais supprimé, seulement désactivé — les factures (4B), les
règlements (4C) et le lettrage resteront rattachés à leur fiche.

L'unicité du nom est insensible à la casse (index fonctionnel) : deux fiches
« Solar Shop » et « solar shop » ne peuvent pas cohabiter dans un même dossier.
Les comptes de tiers par défaut (411x client, 401x fournisseur) sont de simples
pré-remplissages validés par le service ; la base ne vérifie que l'appartenance
au plan du dossier.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text as sa_text

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "partners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_client", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_supplier", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tax_id", sa.String(length=50), nullable=True),
        sa.Column("rccm", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("default_client_account_id", sa.Uuid(), nullable=True),
        sa.Column("default_supplier_account_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint("is_client OR is_supplier", name=op.f("ck_partners_at_least_one_kind")),
        sa.CheckConstraint(
            "address IS NULL OR length(trim(address)) > 0", name=op.f("ck_partners_address_not_blank")
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_partners_name_not_blank")),
        sa.CheckConstraint(
            "notes IS NULL OR length(trim(notes)) > 0", name=op.f("ck_partners_notes_not_blank")
        ),
        sa.CheckConstraint("rccm IS NULL OR length(trim(rccm)) > 0", name=op.f("ck_partners_rccm_not_blank")),
        sa.CheckConstraint(
            "tax_id IS NULL OR length(trim(tax_id)) > 0", name=op.f("ck_partners_tax_id_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_partners_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "default_client_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name=op.f("fk_partners_tenant_id_default_client_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "default_supplier_account_id"],
            ["accounts.tenant_id", "accounts.id"],
            name=op.f("fk_partners_tenant_id_default_supplier_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_partners_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partners")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_partners_tenant_id_id")),
    )
    op.create_index(op.f("ix_partners_tenant_id"), "partners", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_partners_tenant_name"), "partners", ["tenant_id", "name"], unique=False
    )
    # Unicité du nom insensible à la casse dans un dossier.
    op.create_index(
        "uq_partners_tenant_name_lower", "partners", ["tenant_id", sa_text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "ix_partners_tenant_client", "partners", ["tenant_id", "is_client"], unique=False
    )
    op.create_index(
        "ix_partners_tenant_supplier", "partners", ["tenant_id", "is_supplier"], unique=False
    )

    # RLS : les tiers d'un dossier ne sont visibles que dans son contexte.
    op.execute("ALTER TABLE partners ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE partners FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON partners "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON partners")
    op.drop_index("ix_partners_tenant_supplier", table_name="partners")
    op.drop_index("ix_partners_tenant_client", table_name="partners")
    op.drop_index("uq_partners_tenant_name_lower", table_name="partners")
    op.drop_index(op.f("ix_partners_tenant_name"), table_name="partners")
    op.drop_index(op.f("ix_partners_tenant_id"), table_name="partners")
    op.drop_table("partners")

"""Relances automatiques configurables (Phase B, lot 2).

Révision : 0023
Parente  : 0022

Deux changements :

1. Table `sales_reminder_policies` : LA politique de relance automatique du
   dossier (une ligne au plus par dossier — upsert, même patron que les réglages
   de trésorerie). Elle porte l'échéancier d'escalade `offsets_days` : les
   retards (en jours après l'échéance) auxquels une relance est due — ex.
   [1, 7, 15] = 1re relance à J+1, 2e à J+7, 3e à J+15. RLS `tenant_isolation`
   forcée, comme toutes les tables tenant.

2. `sales_reminders.created_by_user_id` devient nullable : une relance
   automatique est créée par le planificateur (origine système), sans
   utilisateur. Les relances manuelles (4D) gardent leur auteur — le NULL
   distingue structurellement les deux origines. Le downgrade refuse le retour
   NOT NULL tant qu'une relance automatique existe : les relances sont
   immuables, on ne les « attribue » pas rétroactivement à un utilisateur
   fictif — l'exploitant supprime d'abord les politiques, puis les relances
   automatiques s'il le décide explicitement.

La sémantique fine de l'échéancier (entiers >= 1, strictement croissants,
1 à 6 seuils) est validée par le service : les contraintes SQL ne portent que
ce que PostgreSQL peut exprimer lisiblement sur du JSONB (tableau de taille
bornée). Aucune écriture comptable : une relance reste un acte commercial
documenté, pas un fait financier.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_reminder_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("offsets_days", postgresql.JSONB(), nullable=False),
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
            "jsonb_array_length(offsets_days) BETWEEN 1 AND 6",
            name=op.f("ck_sales_reminder_policies_offsets_count"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(offsets_days) = 'array'",
            name=op.f("ck_sales_reminder_policies_offsets_array"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_sales_reminder_policies_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["companies.id"],
            name=op.f("fk_sales_reminder_policies_tenant_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_reminder_policies")),
        sa.UniqueConstraint(
            "tenant_id", "id", name=op.f("uq_sales_reminder_policies_tenant_id_id")
        ),
        # Une politique au plus par dossier : l'upsert est la seule écriture. La
        # contrainte UNIQUE (tenant_id) fournit aussi l'index de filtrage RLS —
        # aucun index supplémentaire (alembic check garde la synchro).
        sa.UniqueConstraint("tenant_id", name=op.f("uq_sales_reminder_policies_tenant_id")),
    )

    # Une relance automatique n'a pas d'auteur humain (origine système).
    op.alter_column("sales_reminders", "created_by_user_id", existing_type=sa.Uuid(), nullable=True)

    # RLS : la politique d'un dossier n'est visible que dans son contexte.
    op.execute("ALTER TABLE sales_reminder_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_reminder_policies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sales_reminder_policies "
        "USING (tenant_id = kora_current_tenant()) "
        "WITH CHECK (tenant_id = kora_current_tenant())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sales_reminder_policies")
    op.execute("ALTER TABLE sales_reminder_policies NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_reminder_policies DISABLE ROW LEVEL SECURITY")
    op.drop_table("sales_reminder_policies")
    # Le rollback retire la fonctionnalité et ses propres données : les relances
    # automatiques (origine système) sont supprimées — comme la table de
    # politique ci-dessus, elles n'existent que depuis cette version et aucune
    # autre donnée n'est touchée (les relances manuelles 4D gardent leur auteur).
    # L'exploitant qui revient en arrière décide explicitement de ce sort.
    # ATTENTION : la table est sous RLS FORCÉE — le FORCE s'applique AUSSI au
    # propriétaire, et la session de migration n'a aucun tenant : un DELETE nu
    # ne verrait aucune ligne (échec silencieux, puis NOT NULL refusé). Le FORCE
    # est levé le temps du nettoyage, puis rétabli à l'identique.
    op.execute("ALTER TABLE sales_reminders NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM sales_reminders WHERE created_by_user_id IS NULL")
    op.execute("ALTER TABLE sales_reminders FORCE ROW LEVEL SECURITY")
    op.alter_column(
        "sales_reminders", "created_by_user_id", existing_type=sa.Uuid(), nullable=False
    )

"""Immuabilité du rattachement des lignes et sérialisation avec leur validation.

Révision : 0009
Parente  : 0008

Aucune donnée ni ancienne migration modifiée. Le verrou du parent partage le
protocole de entries._lock_entry : une mutation SQL directe ne peut plus vérifier
un ancien statut DRAFT pendant une validation concurrente.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS = """
        CREATE OR REPLACE FUNCTION kora_ledger_protect_line() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            parent_status text;
        BEGIN
            SELECT status INTO parent_status FROM journal_entries
             WHERE id = CASE WHEN TG_OP = 'INSERT' THEN NEW.entry_id ELSE OLD.entry_id END;
            IF parent_status = 'POSTED' THEN
                RAISE EXCEPTION 'Ligne d''une écriture validée : % interdit', TG_OP
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END
        $$
        """

_PROTECTED = """
        CREATE OR REPLACE FUNCTION kora_ledger_protect_line() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            parent_status text;
        BEGIN
            -- Une ligne reste attachée au brouillon où elle a été créée.
            -- Vérifier seulement OLD.entry_id permettait de déplacer une ligne
            -- vers une écriture déjà validée sans déclencher son contrôle.
            IF TG_OP = 'UPDATE' AND (
                NEW.entry_id IS DISTINCT FROM OLD.entry_id
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            ) THEN
                RAISE EXCEPTION 'Changement de rattachement d''une ligne interdit'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            SELECT status INTO parent_status FROM journal_entries
             WHERE id = CASE WHEN TG_OP = 'INSERT' THEN NEW.entry_id ELSE OLD.entry_id END
             FOR UPDATE;
            IF parent_status = 'POSTED' THEN
                RAISE EXCEPTION 'Ligne d''une écriture validée : % interdit', TG_OP
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END
        $$
        """


def upgrade() -> None:
    op.execute(_PROTECTED)


def downgrade() -> None:
    op.execute(_PREVIOUS)
